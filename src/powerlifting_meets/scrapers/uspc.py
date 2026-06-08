from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import parse_address_location, resolve_location
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# United States Powerlifting Coalition publishes its calendar through Tockify,
# whose public JSON API returns every event for the calendar in one call.
CALNAME = "uspcdates"
API_URL = "https://tockify.com/api/ngevent"
DETAIL_URL = "https://tockify.com/{cal}/detail/{uid}/{tid}"

# A trailing ", City, ST" (US state code) appended to the event summary, e.g.
# "USPC Iron City Open, Pittsburgh, PA" -> name "USPC Iron City Open".
_SUMMARY_LOC_RE = re.compile(r"^(?P<name>.+?),\s*[^,]+,\s*[A-Za-z]{2}\.?$")


class USPCScraper(BaseScraper):
    federation = "USPC"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching USPC events from Tockify")
        resp = self.client.get(API_URL, params={"calname": CALNAME, "max": 500})
        resp.raise_for_status()
        events = resp.json().get("events", [])

        today = date.today()
        meets: list[Meet] = []
        for event in events:
            meet = self._parse_event(event)
            if meet is not None and meet.date_start >= today:
                meets.append(meet)

        logger.info("Scraped %d USPC meets", len(meets))
        return meets

    def _parse_event(self, event: dict) -> Meet | None:
        when = event.get("when") or {}
        start = (when.get("start") or {}).get("millis")
        date_start = self._millis_to_date(start)
        if date_start is None:
            return None

        all_day = bool(when.get("allDay"))
        date_end = self._millis_to_date((when.get("end") or {}).get("millis"))
        if date_end is not None and all_day:
            # Tockify all-day end is exclusive (next midnight).
            from datetime import timedelta

            date_end = date_end - timedelta(days=1)
        if date_end is not None and date_end <= date_start:
            date_end = None

        content = event.get("content") or {}
        summary = ((content.get("summary") or {}).get("text") or "").strip()
        if not summary:
            return None

        m = _SUMMARY_LOC_RE.match(summary)
        name = (m.group("name").strip() if m else summary)

        # The full street address is the most reliable location source; fall back
        # to the city/state baked into the summary tail.
        address = (content.get("address") or "").strip()
        city = state = None
        loc = parse_address_location(address)
        if loc:
            city, state = loc
        if state is None:
            city2, state2, _ = resolve_location(summary)
            city = city or city2
            state = state or state2
        country = "United States" if state else None

        eid = event.get("eid") or {}
        url = None
        if eid.get("uid") is not None and eid.get("tid") is not None:
            url = DETAIL_URL.format(cal=CALNAME, uid=eid["uid"], tid=eid["tid"])

        cancelled = (event.get("status") or {}).get("name") == "cancelled"

        return Meet(
            name=name,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            state=state,
            city=city,
            country=country,
            url=url,
            status="cancelled" if cancelled else "active",
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
        )

    @staticmethod
    def _millis_to_date(millis: int | None) -> date | None:
        if not millis:
            return None
        try:
            return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).date()
        except (ValueError, TypeError, OverflowError):
            return None
