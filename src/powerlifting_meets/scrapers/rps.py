from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import parse_trailing_location
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

MEETS_URL = "https://meets.revolutionpowerlifting.com/"


class RPSScraper(BaseScraper):
    federation = "RPS"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching RPS meets")
        resp = self.client.get(MEETS_URL)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        meets: list[Meet] = []
        today = date.today()

        for li in soup.find_all("li", class_="postEvent"):
            meet = self._parse_meet_li(li, today)
            if meet is not None:
                meets.append(meet)

        logger.info("Scraped %d RPS meets", len(meets))
        return meets

    def _parse_meet_li(self, li: Tag, today: date) -> Meet | None:
        a = li.find("a", href=True)
        if a is None:
            return None

        href = a["href"]

        # Extract date from URL: /YYYY/MM/DD/slug/
        parsed = urlparse(href)
        path = parsed.path.strip("/")
        parts = path.split("/")
        if len(parts) < 4:
            return None

        try:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            meet_date = date(year, month, day)
        except (ValueError, IndexError):
            return None

        if meet_date < today:
            return None

        # Extract meet name and location from p.theTitle
        title_p = li.find("p", class_="theTitle")
        if title_p is None:
            return None

        # Get text content, skipping the time span
        # Structure: <span>Sat @ 9:30 am</span><br/><span style="color:red;">Sold Out</span> Meet Name – City, ST
        status = "active"
        name_parts: list[str] = []

        for child in title_p.children:
            if isinstance(child, Tag):
                if child.name == "span" and "color" in (child.get("style") or ""):
                    # Status badge
                    badge = child.get_text(strip=True).lower()
                    if "sold out" in badge:
                        status = "sold_out"
                    elif "cancelled" in badge or "canceled" in badge:
                        status = "cancelled"
                elif child.name == "br":
                    continue
                elif child.name == "span":
                    # Time span (e.g., "Sat @ 9:30 am") — skip
                    continue
                else:
                    name_parts.append(child.get_text(strip=True))
            elif isinstance(child, str):
                text = child.strip()
                if text:
                    name_parts.append(text)

        raw_title = " ".join(name_parts).strip()
        if not raw_title:
            return None

        name, city, state = self._parse_title(raw_title)
        if not name:
            return None

        return Meet(
            name=name,
            federation="RPS",
            date_start=meet_date,
            state=state,
            city=city,
            url=href,
            status=status,
        )

    # A dash (-, –, —) followed by whitespace. A leading space is optional so
    # listings like "...Mpower Gym- Dayton Ohio" split as well as the usual
    # spaced " – ". Requiring trailing whitespace keeps hyphenated names intact
    # ("Wilkes-Barre", "Push-Pull").
    _SEPARATOR_RE = re.compile(r"[–—-]\s+")

    def _parse_title(self, text: str) -> tuple[str | None, str | None, str | None]:
        """Parse 'Meet Name – City, ST' / 'Meet Name – City ST' / 'Meet Name - City StateName'."""
        # Try each separator from right to left; the first whose trailing
        # segment parses as a real location wins. Validating the segment is a
        # known location keeps meet subtitles (e.g. "– Women's Full Power") from
        # being mistaken for a city/state split.
        for m in reversed(list(self._SEPARATOR_RE.finditer(text))):
            loc = parse_trailing_location(text[m.end():])
            if loc:
                name = text[: m.start()].rstrip()
                city, state = loc
                return name or None, city or None, state

        return text.strip() or None, None, None
