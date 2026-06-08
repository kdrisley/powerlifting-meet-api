from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import normalize_country
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# International Powerlifting Federation master calendar (TYPO3, server-rendered).
# The page groups events under per-year <h2> headings, each followed by a table
# of [date, name, confederation, city, country]. The calendar also lists the
# continental confederations' championships; we keep the global IPF rows and the
# European (EPF) rows, which gives broad international coverage from one source
# without duplicating our other federations or colliding on the "APF" code
# (which means Asian Powerlifting Federation here, not the WPC/APF we scrape).
CALENDAR_URL = "https://www.powerlifting.sport/championships/calendar"
CONFEDERATIONS = {"IPF": "IPF", "EPF": "EPF"}

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
_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\b", re.I)
_DAY_RE = re.compile(r"(\d{1,2})\.")


class IPFScraper(BaseScraper):
    federation = "IPF"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching IPF calendar")
        resp = self.client.get(CALENDAR_URL)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        today = date.today()
        meets: list[Meet] = []

        for heading in soup.find_all("h2"):
            year_text = heading.get_text(strip=True)
            if not re.fullmatch(r"20\d{2}", year_text):
                continue
            year = int(year_text)
            table = heading.find_next("table")
            if table is None:
                continue
            for row in table.find_all("tr"):
                meet = self._parse_row(row, year, today)
                if meet is not None:
                    meets.append(meet)

        logger.info("Scraped %d IPF/EPF meets", len(meets))
        return meets

    def _parse_row(self, row, year: int, today: date) -> Meet | None:
        cells = [c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 5:
            return None
        date_text, name, conf, city_raw, country_raw = cells[:5]

        federation = CONFEDERATIONS.get(conf.upper())
        if federation is None:
            return None
        if not name or self._is_non_meet(name):
            return None

        date_start, date_end = self._parse_date(date_text, year)
        if date_start is None or date_start < today:
            return None

        city = self._clean_place(city_raw)
        country = self._clean_country(country_raw)

        return Meet(
            name=name,
            federation=federation,
            date_start=date_start,
            date_end=date_end,
            city=city,
            country=country,
            url=CALENDAR_URL,
            status="active",
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
            event_type="International",
        )

    @staticmethod
    def _is_non_meet(name: str) -> bool:
        low = name.lower()
        return "education course" in low or "trainer" in low or "referee" in low

    @staticmethod
    def _clean_place(value: str) -> str | None:
        v = value.strip()
        if not v or "tbd" in v.lower() or "bid" in v.lower():
            return None
        # TYPO3 sometimes prefixes the city with "Place ".
        v = re.sub(r"^Place\s+", "", v)
        return v or None

    @staticmethod
    def _clean_country(value: str) -> str | None:
        v = value.strip()
        if not v or "tbd" in v.lower():
            return None
        if "bid" in v.lower():
            # "Bid - Malta" -> "Malta"; multiple bids are ambiguous -> drop.
            if v.lower().count("bid") > 1:
                return None
            v = re.sub(r"(?i)bid\s*-\s*", "", v).strip()
        return normalize_country(v) or v or None

    @staticmethod
    def _parse_date(text: str, year: int) -> tuple[date | None, date | None]:
        months = [m.group(1).lower() for m in _MONTH_RE.finditer(text)]
        days = [int(m.group(1)) for m in _DAY_RE.finditer(text)]
        if not months or not days:
            return None, None

        start_month = _MONTHS[months[0]]
        end_month = _MONTHS[months[1]] if len(months) > 1 else start_month
        start_day = days[0]
        end_day = days[1] if len(days) > 1 else None

        start = _safe_date(year, start_month, start_day)
        if start is None:
            return None, None
        if end_day is None:
            return start, None
        end_year = year + 1 if end_month < start_month else year
        end = _safe_date(end_year, end_month, end_day)
        if end is None or end == start:
            return start, None
        return start, end


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return datetime(year, month, day).date()
    except ValueError:
        return None
