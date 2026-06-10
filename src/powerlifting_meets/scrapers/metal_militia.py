from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import (
    normalize_country,
    normalize_state,
    parse_full_address,
)
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# Metal Militia (bench/deadlift-focused federation, Northeast/Midwest/TX
# chapters). Wix site, but the meets page server-renders the Wix Events app's
# warmup data: a JSON blob with one fully structured record per meet (title,
# ISO schedule, geocoded address, external registration link, slug).
MEETS_URL = "https://www.metalmilitiapowerlifting.com/meets"
EVENT_URL = "https://www.metalmilitiapowerlifting.com/event-details/{slug}"

_WARMUP_RE = re.compile(
    r'<script[^>]*id="wix-warmup-data"[^>]*>(.*?)</script>', re.S
)


def _find_event_lists(obj) -> list[list[dict]]:
    """Recursively collect Wix Events lists from the warmup-data tree.

    The path to the list nests the site-specific widget instance id
    (appsWarmupData.<app-guid>.widgetcomp-XXXX.events.events), so walk the tree
    for any "events" list of dicts that look like event records instead of
    hardcoding ids.
    """
    found: list[list[dict]] = []
    if isinstance(obj, dict):
        events = obj.get("events")
        if (
            isinstance(events, list)
            and events
            and all(isinstance(e, dict) and "scheduling" in e and "title" in e for e in events)
        ):
            found.append(events)
        for value in obj.values():
            found.extend(_find_event_lists(value))
    elif isinstance(obj, list):
        for value in obj:
            found.extend(_find_event_lists(value))
    return found


class MetalMilitiaScraper(BaseScraper):
    federation = "MetalMilitia"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching Metal Militia meets page")
        resp = self.client.get(MEETS_URL)
        resp.raise_for_status()

        m = _WARMUP_RE.search(resp.text)
        if m is None:
            raise ValueError("Metal Militia: wix-warmup-data script not found")
        warmup = json.loads(m.group(1))

        today = date.today()
        meets: list[Meet] = []
        seen: set[str] = set()
        for events in _find_event_lists(warmup):
            for event in events:
                meet = self._parse_event(event)
                if meet is None or meet.date_start < today:
                    continue
                key = str(meet.url or meet.name)
                if key in seen:
                    continue
                seen.add(key)
                meets.append(meet)

        logger.info("Scraped %d MetalMilitia meets", len(meets))
        return meets

    def _parse_event(self, event: dict) -> Meet | None:
        name = (event.get("title") or "").strip()
        scheduling = event.get("scheduling") or {}
        # The formatted date is in the venue's own timezone; the ISO config
        # dates are UTC and can roll an evening meet onto the next day.
        date_start = self._parse_date(
            scheduling.get("startDateFormatted"),
            (scheduling.get("config") or {}).get("startDate"),
        )
        if not name or date_start is None:
            return None
        date_end = self._parse_date(
            scheduling.get("endDateFormatted"),
            (scheduling.get("config") or {}).get("endDate"),
        )
        if date_end is not None and date_end <= date_start:
            date_end = None

        city, state, region, country = self._parse_location(event.get("location") or {})

        slug = (event.get("slug") or "").strip()
        url = EVENT_URL.format(slug=slug) if slug else None

        registration = event.get("registration") or {}
        external = (registration.get("external") or {}).get("registration") or ""
        registration_url = external.strip() or None

        return Meet(
            name=name,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            state=state,
            region=region,
            city=city,
            country=country,
            url=url,
            registration_url=registration_url,
            venue=(event.get("location") or {}).get("name") or None,
            status="active",
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
        )

    @staticmethod
    def _parse_location(location: dict) -> tuple[str | None, str | None, str | None, str | None]:
        """(city, state, region, country) from the Wix location record.

        The street address is the truth for the city — the geocoded
        fullAddress can name the metro instead of the actual town (Aransas
        Pass geocodes to Corpus Christi). fullAddress is the fallback.
        """
        city, state, region, country = parse_full_address(location.get("address"))
        full = location.get("fullAddress") or {}
        if state is None and region is None:
            state = normalize_state(full.get("subdivision"))
        if city and any(ch.isdigit() for ch in city):
            # Address had no street/city comma split; the "city" is really the
            # street line ("715 S. Sugar Street Celina").
            city = None
        if city is None:
            city = (full.get("city") or "").strip() or None
        if country is None:
            country = normalize_country(full.get("countryFullname")) or (
                "United States" if state else None
            )
        if state is not None:
            region = None
        return city, state, region, country

    @staticmethod
    def _parse_date(formatted: str | None, iso: str | None) -> date | None:
        if formatted:
            try:
                return datetime.strptime(formatted.strip(), "%B %d, %Y").date()
            except ValueError:
                pass
        if iso:
            try:
                return date.fromisoformat(iso[:10])
            except ValueError:
                pass
        return None
