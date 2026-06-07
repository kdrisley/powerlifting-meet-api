from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import resolve_location
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

        city, state, country = self._parse_location(location)

        # The last column holds a mix of links: an info page ("Meet Info",
        # poster, website, FB event) and registration material (an "Online
        # Registration" portal, a liftingcast link, or an entry-form PDF/Word).
        url, registration_url = self._classify_links(cells[-1])

        # Director name (col 4) and email (col 5, usually a mailto link).
        director_name: str | None = None
        director_email: str | None = None
        if len(cells) > 4:
            director_name = cells[4].get_text(strip=True) or None
        if len(cells) > 5:
            mailto = cells[5].find("a", href=re.compile(r"^mailto:", re.I))
            if mailto:
                director_email = mailto["href"].split(":", 1)[1].split("?")[0].strip()
            else:
                director_email = cells[5].get_text(strip=True)
            director_email = director_email or None

        return Meet(
            name=name,
            federation="APF",
            date_start=date_start,
            state=state,
            city=city,
            country=country,
            url=url,
            registration_url=registration_url,
            status="active",
            director_name=director_name,
            director_email=director_email,
        )

    @staticmethod
    def _classify_links(cell: Tag) -> tuple[str | None, str | None]:
        """Split a link cell into (info_url, registration_url)."""
        info_url: str | None = None
        registration_url: str | None = None
        entry_form: str | None = None
        for a in cell.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(" ", strip=True).lower()
            if "registration" in text or "register" in text or "liftingcast.com" in href:
                registration_url = registration_url or href
            elif text in ("pdf", "word") or "entry" in text:
                # Entry-form documents are how APF meets are entered.
                entry_form = entry_form or href
            elif any(k in text for k in ("info", "poster", "website", "event")):
                info_url = info_url or href
        return info_url, registration_url or entry_form

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

    def _parse_location(
        self, location: str
    ) -> tuple[str | None, str | None, str | None]:
        """Parse a location cell into (city, state, country).

        APF/WPC lists meets worldwide in several shapes: "City, ST",
        "Venue, City, ST", space-separated "City ST", and international
        "City CountryName". resolve_location handles all of them; if nothing
        is recognizable we keep the raw text as the city.
        """
        if not location:
            return None, None, None

        city, state, country = resolve_location(location)
        if state or country:
            return city, state, country

        return location, None, None
