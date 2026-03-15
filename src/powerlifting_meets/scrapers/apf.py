from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import normalize_state
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://worldpowerliftingcongress.com/meet-calendar/"


class APFScraper(BaseScraper):
    federation = "APF"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching APF/WPC calendar")
        resp = self.client.get(CALENDAR_URL)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        meets: list[Meet] = []
        today = date.today()
        current_year: int | None = None

        for element in self._iter_headings_and_tables(soup):
            if isinstance(element, int):
                current_year = element
                continue

            if current_year is None:
                continue

            # element is a <table> Tag
            for row in element.find_all("tr"):
                cells = row.find_all("td")
                if len(cells) < 4:
                    continue

                meet = self._parse_row(cells, current_year, today)
                if meet is not None:
                    meets.append(meet)

        logger.info("Scraped %d APF meets", len(meets))
        return meets

    def _iter_headings_and_tables(self, soup: BeautifulSoup):
        """Yield year ints from headings and table Tags in document order."""
        for tag in soup.find_all(re.compile(r"^(h[1-6]|table)$")):
            if tag.name.startswith("h"):
                year = self._extract_year(tag.get_text())
                if year is not None:
                    yield year
            else:
                yield tag

    def _extract_year(self, text: str) -> int | None:
        m = re.search(r"(20\d{2})", text)
        return int(m.group(1)) if m else None

    def _parse_row(
        self, cells: list[Tag], year: int, today: date
    ) -> Meet | None:
        month_text = cells[0].get_text(strip=True)
        day_text = cells[1].get_text(strip=True)
        name = cells[2].get_text(strip=True)
        location = cells[3].get_text(strip=True)

        if not name:
            return None

        date_start = self._build_date(month_text, day_text, year)
        if date_start is None:
            return None

        if date_start < today:
            return None

        city, state = self._parse_location(location)

        # Entry form link is in last column
        url: str | None = None
        link = cells[-1].find("a", href=True)
        if link:
            url = link["href"]

        return Meet(
            name=name,
            federation="APF",
            date_start=date_start,
            state=state,
            city=city,
            url=url,
            status="active",
        )

    def _build_date(
        self, month_text: str, day_text: str, year: int
    ) -> date | None:
        if not month_text:
            return None
        # Some rows have no day (e.g. "May" with empty day for TBD meets)
        if not day_text:
            day_text = "1"
        try:
            return datetime.strptime(
                f"{month_text} {day_text} {year}", "%B %d %Y"
            ).date()
        except ValueError:
            return None

    def _parse_location(self, location: str) -> tuple[str | None, str | None]:
        """Parse 'City, ST' or 'Venue, City, ST' into (city, state)."""
        if not location:
            return None, None

        # Split on comma, take last part as potential state
        parts = [p.strip() for p in location.split(",")]
        if len(parts) >= 2:
            state = normalize_state(parts[-1])
            # City is the second-to-last part
            city = parts[-2] or None
            return city, state

        return location, None
