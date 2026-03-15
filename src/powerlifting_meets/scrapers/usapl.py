from __future__ import annotations

import logging
import re
from datetime import date, datetime

from bs4 import BeautifulSoup, Tag

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import normalize_state
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://usapowerlifting.com/calendar/"


class USAPLScraper(BaseScraper):
    federation = "USAPL"

    def scrape(self) -> list[Meet]:
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

        # Parse event-info div for location and links
        city: str | None = None
        url: str | None = None

        info_div = panel.find("div", class_="event-info")
        if info_div:
            info_text = info_div.get_text()
            loc_match = re.search(r"Location:\s*(.+?)(?:\n|$)", info_text)
            if loc_match:
                loc = loc_match.group(1).strip()
                parts = [s.strip() for s in loc.rsplit(",", 1)]
                if len(parts) == 2:
                    city = parts[0] or None
                    state = normalize_state(parts[1]) or state

        # Registration or More Info links
        button_div = panel.find("div", class_="event-button")
        if button_div:
            for a in button_div.find_all("a", href=True):
                link_text = a.get_text(strip=True).lower()
                if "registration" in link_text:
                    url = a["href"]
                    break
                elif "more info" in link_text and url is None:
                    url = a["href"]

        return Meet(
            name=name,
            federation="USAPL",
            date_start=date_start,
            date_end=date_end,
            state=state,
            city=city,
            url=url,
            status="active",
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
