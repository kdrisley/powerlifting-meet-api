from __future__ import annotations

import logging
from datetime import date

from powerlifting_meets.models import Meet
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.ical import parse_ical
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# NZPU (New Zealand Powerlifting United). The site moved off WordPress/Tribe
# Events in Sep 2026 (the old /wp-json/tribe endpoint 404s); its competition
# calendar now publishes an iCal feed. LOCATION reads "Venue, City, Region".
ICAL_URL = "https://nzpu.org/api/v1/competitions/calendar.ics"


class NZPUScraper(BaseScraper):
    federation = "NZPU"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching NZPU iCal feed")
        resp = self.client.get(ICAL_URL)
        resp.raise_for_status()

        today = date.today()
        meets = [
            self._to_meet(ev)
            for ev in parse_ical(resp.text)
            if ev.date_start >= today and (ev.summary or "").strip()
        ]
        logger.info("Scraped %d NZPU meets", len(meets))
        return meets

    def _to_meet(self, ev) -> Meet:
        name = ev.summary.strip()
        parts = [p.strip() for p in (ev.location or "").split(",") if p.strip()]
        venue = city = region = None
        if len(parts) >= 3:
            venue, city, region = ", ".join(parts[:-2]), parts[-2], parts[-1]
        elif len(parts) == 2:
            venue, city = parts
        elif parts:
            city = parts[0]
        return Meet(
            name=name,
            federation=self.federation,
            date_start=ev.date_start,
            date_end=ev.date_end,
            region=region,
            city=city,
            country="New Zealand",
            url=ev.url or None,
            venue=venue,
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
            status="active",
        )
