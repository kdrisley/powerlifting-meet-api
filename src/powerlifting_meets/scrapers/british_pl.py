from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from powerlifting_meets.models import Meet
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# British Powerlifting (IPF's UK affiliate). Server-rendered WordPress; the two
# listing pages render one card per upcoming meet. The WP REST routes for these
# CPTs exist but expose no dates, and /calendar redirects to a news post, so
# the listing HTML is the data source. National/divisional meets here do NOT
# appear on powerlifting.sport (that calendar is internationals only).
LISTING_URLS = (
    "https://www.britishpowerlifting.org/upcoming-championships/",
    "https://www.britishpowerlifting.org/upcoming-events-competitions/",
)

# "13 Jun - 14 Jun, 2026" or "5 Jul, 2026" (the year applies to both ends).
_DATES_RE = re.compile(
    r"^(?P<d1>\d{1,2})\s+(?P<m1>[A-Za-z]+)"
    r"(?:\s*[-–]\s*(?P<d2>\d{1,2})\s+(?P<m2>[A-Za-z]+))?"
    r",\s*(?P<year>\d{4})$"
)

# Card metadata carries either p.event-level (a tier word) or p.divisions (the
# hosting division's region name, e.g. "West Midlands") — a deterministic
# region signal on otherwise location-less cards.
_LEVELS = {
    "divisional": "REGIONAL",
    "national": "NATIONAL",
    "international": "INTERNATIONAL",
}


class BritishPLScraper(BaseScraper):
    federation = "BritishPL"

    def scrape(self) -> list[Meet]:
        today = date.today()
        meets: list[Meet] = []
        seen: set[str] = set()
        for url in LISTING_URLS:
            logger.info("Fetching %s", url)
            resp = self.client.get(url)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "lxml")
            for card in soup.select("a.content_row_card"):
                href = card.get("href") or ""
                if not href or href in seen:
                    continue
                seen.add(href)
                meet = self._parse_card(card, href)
                if meet is not None and meet.date_start >= today:
                    meets.append(meet)

        logger.info("Scraped %d BritishPL meets", len(meets))
        return meets

    def _parse_card(self, card, href: str) -> Meet | None:
        title_el = card.select_one(".title_excerpt h5") or card.find("h5")
        name = title_el.get_text(" ", strip=True) if title_el else ""
        dates_el = card.select_one("p.dates")
        if not name or dates_el is None:
            return None

        parsed = self._parse_dates(dates_el.get_text(" ", strip=True))
        if parsed is None:
            return None
        date_start, date_end = parsed

        event_level: str | None = None
        level_el = card.select_one("p.event-level")
        if level_el is not None:
            event_level = _LEVELS.get(level_el.get_text(" ", strip=True).lower())

        region: str | None = None
        division_el = card.select_one("p.divisions")
        if division_el is not None:
            region = division_el.get_text(" ", strip=True) or None

        return Meet(
            name=name,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            region=region,
            # Single-country federation: stamping the country keeps these cards
            # (which carry no venue/city) out of the geo-inference tier.
            country="United Kingdom",
            url=href,
            status="active",
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
            event_level=event_level,
        )

    @staticmethod
    def _parse_dates(text: str) -> tuple[date, date | None] | None:
        m = _DATES_RE.match(text)
        if m is None:
            return None
        year = int(m.group("year"))

        def build(day: str, month: str, yr: int) -> date | None:
            try:
                return datetime.strptime(f"{day} {month[:3]} {yr}", "%d %b %Y").date()
            except ValueError:
                return None

        start = build(m.group("d1"), m.group("m1"), year)
        if start is None:
            return None
        end = None
        if m.group("d2"):
            end = build(m.group("d2"), m.group("m2"), year)
            if end is not None and end < start:
                # Range crossing New Year ("30 Dec - 2 Jan, 2026").
                end = build(m.group("d2"), m.group("m2"), year + 1)
            if end == start:
                end = None
        return start, end
