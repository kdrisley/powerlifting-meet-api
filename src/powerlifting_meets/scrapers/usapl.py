from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

import httpx

from bs4 import BeautifulSoup, Tag

from powerlifting_meets.classify import normalize_event_level
from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import clean_street_address, normalize_state
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://usapowerlifting.com/calendar/"

# USAPL's calendar (now at /events) sits behind Cloudflare bot protection that
# returns 403 to every non-browser client, including GitHub Actions, since
# about 2026-07-16. Until that changes, the scraper falls back to a snapshot
# of the calendar captured in a regular browser session and committed here.
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

    def _scrape_snapshot(self, path: Path = SNAPSHOT_PATH) -> list[Meet]:
        """Upcoming meets from the committed browser-captured calendar snapshot."""
        data = json.loads(path.read_text(encoding="utf-8"))
        cols = data["columns"]
        today = date.today()
        meets: list[Meet] = []
        for row in data["rows"]:
            r = dict(zip(cols, row))
            date_start, date_end = self._parse_long_date_range(r["dates"])
            if date_start is None or date_start < today:
                continue
            level = (r.get("level") or "").removesuffix(" Event").strip()
            meets.append(
                Meet(
                    name=r["name"],
                    federation="USAPL",
                    date_start=date_start,
                    date_end=date_end,
                    state=normalize_state(r.get("state")),
                    city=r.get("city") or None,
                    country="United States" if normalize_state(r.get("state")) else None,
                    url=r.get("info_url") or None,
                    registration_url=r.get("registration_url") or None,
                    venue_address=clean_street_address(r.get("venue_address")),
                    status="active",
                    sanction=r.get("sanction") or None,
                    event_level=normalize_event_level(level),
                    director_name=r.get("director") or None,
                )
            )
        logger.info(
            "Loaded %d upcoming USAPL meets from snapshot captured %s",
            len(meets),
            data.get("captured_at"),
        )
        return meets

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

    def _scrape_live(self) -> list[Meet]:
        logger.info("Fetching USAPL calendar")
        resp = self.client.get(CALENDAR_URL)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        meets: list[Meet] = []
        today = date.today()

        for panel in soup.find_all("div", class_="vc_tta-panel", id=re.compile(r"^event-\d+")):
            meet = self._parse_panel(panel, today)
            if meet is not None:
                meets.append(meet)

        logger.info("Scraped %d USAPL meets", len(meets))
        return meets

    def _parse_panel(self, panel: Tag, today: date) -> Meet | None:
        # Title container has structured divs
        name_div = panel.find("div", class_="event-name")
        date_div = panel.find("div", class_="event-date")
        state_div = panel.find("div", class_="event-state")

        if not name_div or not date_div:
            return None

        name = name_div.get_text(strip=True)
        if not name:
            return None

        date_text = date_div.get_text(strip=True)
        date_start, date_end = self._parse_date_range(date_text)
        if date_start is None:
            return None

        # Skip past events
        if date_start < today:
            return None

        state_raw = state_div.get_text(strip=True) if state_div else None
        state = normalize_state(state_raw)

        # Parse event-info div for location, sanction, event type, and director
        city: str | None = None
        url: str | None = None
        sanction: str | None = None
        # USAPL's "Type of Event" is the competitive tier (Local/State/National/
        # Regional), not the competition format, so it maps to event_level.
        event_level: str | None = None
        director_name: str | None = None
        director_email: str | None = None

        info_div = panel.find("div", class_="event-info")
        if info_div:
            info_text = info_div.get_text(" ", strip=True)
            loc_match = re.search(r"Location:\s*(.+?)\s*(?:Director:|$)", info_text)
            if loc_match:
                loc = loc_match.group(1).strip()
                parts = [s.strip() for s in loc.rsplit(",", 1)]
                if len(parts) == 2:
                    city = parts[0] or None
                    state = normalize_state(parts[1]) or state

            type_match = re.search(r"Type of Event:\s*(.+?)\s*(?:Sanction:|$)", info_text)
            if type_match:
                event_level = normalize_event_level(type_match.group(1).strip())

            sanction_match = re.search(r"Sanction:\s*([A-Za-z0-9-]+)", info_text)
            if sanction_match:
                sanction = sanction_match.group(1).strip() or None

            # The director's name is the mailto link's text; the email is its href.
            mailto = info_div.find("a", href=re.compile(r"^mailto:", re.I))
            if mailto:
                director_name = mailto.get_text(strip=True) or None
                director_email = (
                    mailto["href"].split(":", 1)[1].split("?")[0].strip() or None
                )
            else:
                dir_match = re.search(r"Director:\s*(.+?)\s*$", info_text)
                if dir_match:
                    director_name = dir_match.group(1).strip() or None

        # The "More Info" button is the meet's info page; "Registration" is the
        # sign-up link. Keep them in separate fields.
        registration_url: str | None = None
        button_div = panel.find("div", class_="event-button")
        if button_div:
            for a in button_div.find_all("a", href=True):
                link_text = a.get_text(strip=True).lower()
                if "registration" in link_text or "register" in link_text:
                    registration_url = registration_url or a["href"]
                elif "more info" in link_text or "info" in link_text:
                    url = url or a["href"]

        return Meet(
            name=name,
            federation="USAPL",
            date_start=date_start,
            date_end=date_end,
            state=state,
            city=city,
            url=url,
            registration_url=registration_url,
            status="active",
            sanction=sanction,
            event_level=event_level,
            director_name=director_name,
            director_email=director_email,
        )

    def _parse_date_range(self, text: str) -> tuple[date | None, date | None]:
        """Parse date strings like 'Mar 14, 2026' or 'Mar 14-15, 2026'."""
        # Range within same month: "Mar 14-15, 2026"
        m = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2})\s*-\s*(\d{1,2}),?\s*(\d{4})", text)
        if m:
            month_str, day1, day2, year = m.groups()
            start = self._make_date(month_str, day1, year)
            end = self._make_date(month_str, day2, year)
            return start, end if end != start else None

        # Cross-month range: "Mar 30 - Apr 1, 2026" or "Mar 30, 2026 - Apr 1, 2026"
        m = re.match(
            r"([A-Z][a-z]{2})\s+(\d{1,2}),?\s*\d{0,4}\s*-\s*"
            r"([A-Z][a-z]{2})\s+(\d{1,2}),?\s*(\d{4})",
            text,
        )
        if m:
            m1, d1, m2, d2, year = m.groups()
            start = self._make_date(m1, d1, year)
            end = self._make_date(m2, d2, year)
            return start, end

        # Single date: "Mar 14, 2026"
        m = re.match(r"([A-Z][a-z]{2})\s+(\d{1,2}),?\s*(\d{4})", text)
        if m:
            month_str, day, year = m.groups()
            d = self._make_date(month_str, day, year)
            return d, None

        return None, None

    def _make_date(self, month_str: str, day: str, year: str) -> date | None:
        try:
            return datetime.strptime(f"{month_str} {day} {year}", "%b %d %Y").date()
        except ValueError:
            return None
