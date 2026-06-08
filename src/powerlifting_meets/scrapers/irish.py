from __future__ import annotations

import logging
import re
from datetime import date

from bs4 import BeautifulSoup

from powerlifting_meets.models import Meet
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# Irish Powerlifting Federation. WordPress; per-year calendar page is a static
# table: [Month, Date, Event, Sanction, Venue, ...]. All meets are in Ireland.
CALENDAR_URL = "https://irishpowerliftingfederation.com/calendar-{year}/"

_MONTHS = {
    m.lower(): i
    for i, m in enumerate(
        [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ],
        start=1,
    )
}
# Ordinal day(s): "7th", "7th-8th", "16th–17th" (en dash too).
_DAY_RE = re.compile(r"(\d{1,2})(?:st|nd|rd|th)")


class IrishScraper(BaseScraper):
    federation = "IrishPF"

    def scrape(self) -> list[Meet]:
        today = date.today()
        meets: list[Meet] = []
        for year in (today.year, today.year + 1):
            url = CALENDAR_URL.format(year=year)
            try:
                resp = self.client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.info("IrishPF: no calendar page for %d (%s)", year, exc)
                continue
            meets.extend(self._parse_table(resp.text, year, today))

        logger.info("Scraped %d IrishPF meets", len(meets))
        return meets

    def _parse_table(self, html_text: str, year: int, today: date) -> list[Meet]:
        soup = BeautifulSoup(html_text, "lxml")
        table = soup.find("table")
        if table is None:
            return []
        meets: list[Meet] = []
        for row in table.find_all("tr"):
            cells = [c.get_text(" ", strip=True) for c in row.find_all("td")]
            if len(cells) < 3:
                continue
            meet = self._parse_row(cells, year, today)
            if meet is not None:
                meets.append(meet)
        return meets

    def _parse_row(self, cells: list[str], year: int, today: date) -> Meet | None:
        month_text, day_text, name = cells[0], cells[1], cells[2]
        month = _MONTHS.get(month_text.strip().lower())
        if month is None or not name:
            return None

        days = [int(d) for d in _DAY_RE.findall(day_text)]
        if not days:
            return None
        date_start = _safe_date(year, month, days[0])
        if date_start is None or date_start < today:
            return None
        date_end = _safe_date(year, month, days[1]) if len(days) > 1 else None
        if date_end == date_start:
            date_end = None

        venue = city = None
        if len(cells) >= 5 and cells[4]:
            venue_cell = cells[4]
            if "," in venue_cell:
                venue, city = (p.strip() for p in venue_cell.rsplit(",", 1))
            else:
                venue = venue_cell.strip()
            venue = venue or None
            city = city or None

        sanction = cells[3].strip() if len(cells) > 3 and cells[3].strip() else None

        return Meet(
            name=name,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            city=city,
            country="Ireland",
            venue=venue,
            status="active",
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
            sanction=sanction,
        )


def _safe_date(year: int, month: int, day: int) -> date | None:
    from datetime import datetime

    try:
        return datetime(year, month, day).date()
    except ValueError:
        return None
