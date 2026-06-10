from __future__ import annotations

import html
import json
import logging
from datetime import date

from bs4 import BeautifulSoup

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import parse_full_address
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# American Powerlifting Organization (multi-ply/equipped scene). WordPress with
# Modern Events Calendar, which server-renders one JSON-LD Event block per
# upcoming meet on the events page. The plugin's REST route
# (wp-json/mec/v1/events) exists but returns [], so JSON-LD is the data source.
EVENTS_URL = "https://apopowerlifting.com/events/"


class APOScraper(BaseScraper):
    federation = "APO"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching APO events page")
        resp = self.client.get(EVENTS_URL)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        today = date.today()
        meets: list[Meet] = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except ValueError:
                continue
            for item in data if isinstance(data, list) else [data]:
                if not isinstance(item, dict) or item.get("@type") != "Event":
                    continue
                meet = self._parse_event(item)
                if meet is not None and meet.date_start >= today:
                    meets.append(meet)

        logger.info("Scraped %d APO meets", len(meets))
        return meets

    def _parse_event(self, item: dict) -> Meet | None:
        name = html.unescape(item.get("name") or "").strip()
        date_start = self._parse_date(item.get("startDate"))
        if not name or date_start is None:
            return None
        date_end = self._parse_date(item.get("endDate"))
        if date_end is not None and date_end <= date_start:
            date_end = None

        location = item.get("location") or {}
        venue = html.unescape(location.get("name") or "").strip() or None
        city, state, _, _ = parse_full_address(location.get("address"))

        organizer = item.get("organizer") or {}
        director_name = (organizer.get("name") or "").strip() or None

        cancelled = "EventCancelled" in (item.get("eventStatus") or "")

        return Meet(
            name=name,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            state=state,
            city=city,
            # APO is US-only; stamping the country keeps address-less meets
            # (some venues publish only a name) out of the geo-inference tier.
            country="United States",
            url=(item.get("url") or "").strip() or None,
            venue=venue,
            status="cancelled" if cancelled else "active",
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
            director_name=director_name,
        )

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        if not raw:
            return None
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            return None
