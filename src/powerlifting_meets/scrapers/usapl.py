from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from bs4 import BeautifulSoup, Tag

from powerlifting_meets.classify import normalize_event_level
from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import clean_street_address, normalize_state
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

EVENTS_URL = "https://www.usapowerlifting.com/events"
# The calendar shows 9 events per page; stop after this many pages regardless.
MAX_PAGES = 60

# USAPL's calendar (moved from /calendar/ to /events) sits behind Cloudflare
# bot protection that 403s non-browser clients; the shared client retries
# those through Jina (see fetch.py). If the live calendar still can't be read,
# the scraper falls back to a browser-captured snapshot committed here.
SNAPSHOT_PATH = Path(__file__).resolve().parents[3] / "snapshots" / "usapl-events.json"


class USAPLScraper(BaseScraper):
    federation = "USAPL"

    def scrape(self) -> list[Meet]:
        try:
            meets = self._scrape_live()
        except httpx.HTTPError as exc:
            logger.warning("USAPL live calendar unavailable (%s); using snapshot", exc)
            return self._scrape_snapshot()
        if not meets:
            logger.warning("USAPL live calendar parsed 0 meets; using snapshot")
            return self._scrape_snapshot()
        return meets

    # ---------- live calendar (/events) ----------

    def _scrape_live(self) -> list[Meet]:
        today = date.today()
        meets: list[Meet] = []
        seen: set[tuple[str, date]] = set()
        total_pages: int | None = None
        page = 1
        while page <= (total_pages or MAX_PAGES):
            logger.info("Fetching USAPL calendar page %d", page)
            resp = self.client.get(EVENTS_URL, params={"page": page})
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            if total_pages is None:
                total_pages = self._total_pages(soup)
            rows = [self._row_from_result(soup, ev) for ev in soup.select(".js-events-result")]
            if not rows:
                break
            for row in rows:
                meet = self._meet_from_row(row, today)
                if meet is None or (meet.name, meet.date_start) in seen:
                    continue
                seen.add((meet.name, meet.date_start))
                meets.append(meet)
            page += 1
        logger.info("Scraped %d USAPL meets from %d calendar pages", len(meets), page - 1)
        return meets

    @staticmethod
    def _total_pages(soup: BeautifulSoup) -> int | None:
        """'234 results' at 9 per page -> 26 pages."""
        text = soup.find(string=re.compile(r"\d+\s+results"))
        if not text:
            return None
        count = int(re.search(r"(\d+)\s+results", text).group(1))
        per_page = len(soup.select(".js-events-result")) or 9
        return min(MAX_PAGES, -(-count // per_page))

    @staticmethod
    def _row_from_result(soup: BeautifulSoup, ev: Tag) -> dict[str, str]:
        """One calendar entry -> the same fields the snapshot stores."""

        def text(sel: str) -> str:
            el = ev.select_one(sel)
            return el.get_text(" ", strip=True) if el else ""

        row = {
            "name": text(".events-result__title"),
            "dates": text(".events-result__date-1"),
            "city": text(".events-result__location-1-city").rstrip(","),
            "state": text(".events-result__location-1-state"),
            "level": "",
            "sanction": "",
            "director": "",
            "info_url": "",
            "registration_url": "",
            "venue_address": "",
        }
        toggle = ev.select_one(".js-events-result-toggle")
        content = soup.find(id=toggle.get("aria-controls")) if toggle else None
        if content is None:
            return row
        leaves = [
            el.get_text(" ", strip=True)
            for el in content.find_all(["div", "span"])
            if not el.find(["div", "span"])
        ]
        row["level"] = next((t for t in leaves if t.endswith("Event")), "")
        row["sanction"] = next((t for t in leaves if re.fullmatch(r"[A-Z]{2,3}-\d{4}-\d+", t)), "")
        for li in content.find_all("li"):
            parts = [t for t in li.get_text("|", strip=True).split("|") if t]
            if parts and parts[-1].lower() == "meet director":
                row["director"] = parts[0]
                break
        for a in content.find_all("a", href=True):
            href, label = a["href"], a.get_text(strip=True).lower()
            if "google.com/maps" in href:
                dest = parse_qs(urlparse(href).query).get("destination", [""])[0]
                row["venue_address"] = row["venue_address"] or dest
            elif "regist" in label:
                row["registration_url"] = row["registration_url"] or href
            elif "info" in label:
                row["info_url"] = row["info_url"] or href
        return row

    # ---------- snapshot fallback ----------

    def _scrape_snapshot(self, path: Path = SNAPSHOT_PATH) -> list[Meet]:
        """Upcoming meets from the committed browser-captured calendar snapshot."""
        data = json.loads(path.read_text(encoding="utf-8"))
        cols = data["columns"]
        today = date.today()
        meets = [
            m
            for m in (self._meet_from_row(dict(zip(cols, row)), today) for row in data["rows"])
            if m is not None
        ]
        logger.info(
            "Loaded %d upcoming USAPL meets from snapshot captured %s",
            len(meets),
            data.get("captured_at"),
        )
        return meets

    # ---------- shared ----------

    @classmethod
    def _meet_from_row(cls, r: dict[str, str], today: date) -> Meet | None:
        if not r.get("name"):
            return None
        date_start, date_end = cls._parse_long_date_range(r.get("dates", ""))
        if date_start is None or date_start < today:
            return None
        state = normalize_state(r.get("state"))
        level = (r.get("level") or "").removesuffix(" Event").strip()
        return Meet(
            name=r["name"],
            federation="USAPL",
            date_start=date_start,
            date_end=date_end,
            state=state,
            city=r.get("city") or None,
            country="United States" if state else None,
            url=r.get("info_url") or None,
            registration_url=r.get("registration_url") or None,
            venue_address=clean_street_address(r.get("venue_address")),
            status="active",
            sanction=r.get("sanction") or None,
            event_level=normalize_event_level(level),
            director_name=r.get("director") or None,
        )

    @staticmethod
    def _parse_long_date_range(text: str) -> tuple[date | None, date | None]:
        """Parse 'October 10, 2026' or 'October 16, 2026 - October 18, 2026'."""
        parts = [p.strip() for p in (text or "").split(" - ")]
        try:
            days = [datetime.strptime(p, "%B %d, %Y").date() for p in parts if p]
        except ValueError:
            return None, None
        if not days:
            return None, None
        start, end = days[0], days[-1]
        return start, (end if end != start else None)
