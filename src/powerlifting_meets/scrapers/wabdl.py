from __future__ import annotations

import logging
from datetime import date

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import parse_full_address
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.ical import parse_ical
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# WABDL (World Association of Benchers and Deadlifters). The site runs the
# Events Manager WordPress plugin, which exposes a full iCal feed. The feed is
# the entire history (events back to 2015), so we filter to upcoming meets.
ICAL_URL = "https://wabdl.org/events/?ical=1"


class WABDLScraper(BaseScraper):
    federation = "WABDL"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching WABDL iCal feed")
        resp = self.client.get(ICAL_URL)
        resp.raise_for_status()

        today = date.today()
        meets: list[Meet] = []
        for ev in parse_ical(resp.text):
            if ev.date_start < today:
                continue
            meet = self._to_meet(ev)
            if meet is not None:
                meets.append(meet)

        logger.info("Scraped %d WABDL meets", len(meets))
        return meets

    def _to_meet(self, ev) -> Meet | None:
        name = (ev.summary or "").strip()
        # Some titles carry an organizer "MEEET:"/"MEET:" prefix; strip it.
        for prefix in ("MEEET:", "MEET:"):
            if name.upper().startswith(prefix):
                name = name[len(prefix):].strip()
        if not name:
            return None

        city, state, region, country = parse_full_address(ev.location)

        return Meet(
            name=name,
            federation=self.federation,
            date_start=ev.date_start,
            date_end=ev.date_end,
            state=state,
            region=region,
            city=city,
            country=country,
            url=ev.url or None,
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
            status="active",
        )
