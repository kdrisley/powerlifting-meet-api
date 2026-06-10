from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from powerlifting_meets.models import Meet
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

# Norges Styrkeløftforbund (IPF's Norwegian affiliate). One server-rendered PHP
# table for the whole year, sectioned by month-name rows; the year comes from
# the page heading ("Terminliste - 2026").
CALENDAR_URL = "https://styrkeloft.no/terminliste/"

# Meet types to publish. Dropped on purpose: "Klubbstevne" (in-house club
# nights, ~70% of rows, no outside registration), "Internasjonalt stevne" (IPF
# internationals — already on our IPF feed), and "Kurs" (courses).
_KEEP_TYPES = frozenset({"Åpent stevne", "Regionsmesterskap", "Mesterskapsstevne"})

_MONTHS = {
    "januar": 1, "februar": 2, "mars": 3, "april": 4, "mai": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11,
    "desember": 12,
}

# "03." single day or "17.-19." multi-day span within one month.
_DATO_RE = re.compile(r"^(?P<d1>\d{1,2})\.(?:-(?P<d2>\d{1,2})\.)?$")


class NSFScraper(BaseScraper):
    federation = "NSF"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching NSF terminliste")
        resp = self.client.get(CALENDAR_URL)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        year = self._page_year(soup)
        if year is None:
            raise ValueError("NSF terminliste: no year found in page heading")

        table = self._schedule_table(soup)
        if table is None:
            raise ValueError("NSF terminliste: schedule table not found")

        today = date.today()
        month: int | None = None
        meets: list[Meet] = []
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            texts = [c.get_text(" ", strip=True) for c in cells]
            if len(cells) == 1:
                month = _MONTHS.get(texts[0].lower(), month)
                continue
            if len(cells) < 5 or texts[0] == "Dato" or month is None:
                continue
            meet = self._parse_row(row, texts, year, month)
            if meet is not None and meet.date_start >= today:
                meets.append(meet)

        logger.info("Scraped %d NSF meets", len(meets))
        return meets

    @staticmethod
    def _page_year(soup: BeautifulSoup) -> int | None:
        h1 = soup.find("h1")
        if h1 is None:
            return None
        m = re.search(r"(20\d{2})", h1.get_text())
        return int(m.group(1)) if m else None

    @staticmethod
    def _schedule_table(soup: BeautifulSoup):
        """The schedule is the table containing month-section rows; the page's
        first table is the year/club/type filter form."""
        for table in soup.find_all("table"):
            header = table.find(string=re.compile(r"^\s*Stevne\s*$"))
            if header is not None:
                return table
        return None

    def _parse_row(
        self, row, texts: list[str], year: int, month: int
    ) -> Meet | None:
        dato, name, meet_type = texts[0], texts[1], texts[2]
        if not name or meet_type not in _KEEP_TYPES:
            return None
        # Some clubs list their club nights under "Åpent stevne" but name them
        # just "Klubbstevne"; a meet with no identity of its own isn't feed-worthy.
        if name.lower() == "klubbstevne":
            return None

        m = _DATO_RE.match(dato.replace(" ", ""))
        if m is None:
            return None
        try:
            date_start = date(year, month, int(m.group("d1")))
            date_end = date(year, month, int(m.group("d2"))) if m.group("d2") else None
        except ValueError:
            return None
        if date_end is not None and date_end <= date_start:
            date_end = None

        venue = texts[4].strip() or None

        url = None
        entry_link = row.find("a", href=re.compile(r"pameldingsliste"))
        if entry_link is not None:
            url = urljoin(CALENDAR_URL, entry_link["href"])

        return Meet(
            name=name,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            # Single-country federation; Sted is a venue string, not a clean
            # city, so it goes in `venue` and the country stamp keeps these
            # meets out of the geo-inference tier.
            country="Norway",
            venue=venue,
            url=url,
            status="active",
        )
