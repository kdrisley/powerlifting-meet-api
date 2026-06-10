from __future__ import annotations

import logging
from collections import Counter

from powerlifting_meets.models import Meet
from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper

logger = logging.getLogger(__name__)

# powerlifting.com runs a Tribe Events calendar aggregating ~500 upcoming
# events across many federations (plus strongman/weightlifting), with the
# sanctioning federation as the event's organizer and the lister's external
# link (registration form or fed meet page) in `website`.
#
# Only organizers in ORGANIZER_TO_FED are emitted — federations we have no
# direct scraper for. Everything else is dropped: feds we already scrape
# (keeping them would duplicate meets under a second source, and runner dedup
# only collapses exact (name, federation, date) matches), non-powerlifting
# organizers, and unknown/unattributed organizers. Unknowns are logged so the
# allowlist grows by review, never by guessing.
ORGANIZER_TO_FED: dict[str, str] = {
    "World Raw Powerlifting Federation": "WRPF",
    "World Raw Powerlifting Federation Canada": "WRPF",
    "365 Strong World Powerlifting Federation": "365Strong",
    "American Powerlifting Union": "APU",
    "Irish Powerlifting Organisation": "IPO",
    "CAPO Powerlifting": "CAPO",
    "World United Amateur Powerlifting": "WUAP",
    # organizer-name variant seen in the live feed
    "WUAP EUROPEAN CHAMPIONSHIPS": "WUAP",
    "British Drug Free Powerlifting Association": "BDFPA",
    "British Powerlifting Union": "BPU",
}

# Organizers dropped silently: federations our other scrapers already cover,
# and non-powerlifting sports the calendar mixes in. Anything not here and not
# in the allowlist is logged as unmatched.
KNOWN_DROPPED: frozenset[str] = frozenset({
    # covered by direct scrapers
    "USA Powerlifting",
    "United States Powerlifting Association",
    "Powerlifting America",
    "United States Powerlifting Coalition",
    "Revolution Powerlifting Syndicate",
    "Powerlifting United",
    "Australian Powerlifting League",
    "National Powerlifting League",
    "Southern Powerlifting Federation",
    "100% RAW Powerlifting Federation",
    "Canada Powerlifting",
    "American Powerlifting Organization",
    "American Powerlifting Federation",
    "British Powerlifting",
    "International Powerlifting Federation",
    "European Powerlifting Federation",  # EPF meets ride the IPF scraper
    "International Powerlifting League",
    "United Kingdom Powerlifting League",
    "Natural Athlete Strength Association",
    "World Natural Powerlifting Federation",
    "Irish Powerlifting Federation",
    "Powerlifting Australia",
    "New Zealand Powerlifting United",
    "Metal Militia Powerlifting",
    # not powerlifting
    "United States Strongman",
    "Strongman Corporation",
    "Ultimate Strongman",
    "USA Weightlifting",
    "USA Masters Weightlifting",
    "International Masters Weightlifting Association",
})


class PowerliftingComScraper(TribeEventsScraper):
    # Meta.json / fallback key for the source; each Meet carries its real
    # federation code from ORGANIZER_TO_FED.
    federation = "PLCOM"
    fallback_federations = frozenset(ORGANIZER_TO_FED.values())
    base_url = "https://powerlifting.com"

    def scrape(self) -> list[Meet]:
        self._unmatched: Counter[str] = Counter()
        meets = super().scrape()
        if self._unmatched:
            logger.info(
                "powerlifting.com: unmatched organizers (review for allowlist): %s",
                ", ".join(f"{name} x{n}" for name, n in self._unmatched.most_common(15)),
            )
        return meets

    def _parse_event(self, event: dict) -> Meet | None:
        organizer = event.get("organizer")
        if isinstance(organizer, list):
            organizer = organizer[0] if organizer else None
        name = (organizer or {}).get("organizer", "").strip() if isinstance(organizer, dict) else ""

        fed = ORGANIZER_TO_FED.get(name)
        if fed is None:
            if name and name not in KNOWN_DROPPED:
                self._unmatched[name] += 1
            return None

        meet = super()._parse_event(event)
        if meet is None:
            return None
        meet.federation = fed
        # The base class maps the Tribe organizer to director fields, but here
        # the organizer is the federation, not a meet director.
        meet.director_name = None
        meet.director_email = None
        # `website` is the lister's external link — a registration form
        # (JotForm/Google Forms/LiftingCast) or the fed's own meet page; the
        # powerlifting.com event page stays in `url`.
        website = (event.get("website") or "").strip()
        if website and website != str(meet.url):
            meet.registration_url = website
        return meet
