from __future__ import annotations

import logging
import re
from datetime import date

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import (
    parse_full_address,
    parse_trailing_country,
    resolve_location,
)
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.ical import ICalEvent, parse_ical
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# International Powerlifting League. powerlifting-ipl.com/ipl-events/ embeds a
# public Google Calendar; its ICS feed carries the full history plus upcoming
# championships with venue addresses in LOCATION and entry links in DESCRIPTION.
ICAL_URL = (
    "https://calendar.google.com/calendar/ical/"
    "of0ufu6t86cngkn3278f8bqi0c%40group.calendar.google.com/public/basic.ics"
)

# IPL meets in these countries belong to other feeds: US events are on the USPA
# calendar (USPA is the IPL's US affiliate) and UK events on UKIPL's, so keeping
# them here would duplicate meets under a second federation code.
_COVERED_ELSEWHERE = frozenset({"United States", "United Kingdom"})

_URL_RE = re.compile(r"https?://[^\s\\\"'<>]+")

# Every event description ends with the same classification-standards link;
# it's boilerplate, not a registration link.
_BOILERPLATE = "powerlifting-ipl.com/classification-standards"


def _registration_url(description: str | None) -> str | None:
    """First non-boilerplate link in the event description.

    IPL descriptions consistently lead with the entry link (a Google Form or
    the organizing affiliate's registration page) and end with the shared
    classification-standards link.
    """
    if not description:
        return None
    for raw in _URL_RE.findall(description):
        url = raw.rstrip(".,;)")
        if _BOILERPLATE not in url:
            return url
    return None


class IPLScraper(BaseScraper):
    federation = "IPL"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching IPL Google Calendar feed")
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

        logger.info("Scraped %d IPL meets", len(meets))
        return meets

    def _to_meet(self, ev: ICalEvent) -> Meet | None:
        name = (ev.summary or "").strip()
        if not name:
            return None

        city, state, region, country = parse_full_address(ev.location)
        if not country and not state and ev.location:
            # The address's last segment may bundle region+zip+country
            # ("Región Metropolitana de Santiago 8370159 Chile").
            tail = parse_trailing_country(ev.location.rsplit(",", 1)[-1].strip())
            if tail:
                country = tail[1]
        if not country and not state:
            # Last resort before honest-null: internationals usually carry the
            # country in the title ("IPL Bench Press World Cup, Belgrade, Serbia").
            _, _, country = resolve_location(name)

        if state or country in _COVERED_ELSEWHERE:
            return None

        return Meet(
            name=name,
            federation=self.federation,
            date_start=ev.date_start,
            date_end=ev.date_end,
            state=None,
            region=region,
            city=city,
            country=country,
            url=ev.url or None,
            registration_url=_registration_url(ev.description),
            status="active",
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
        )
