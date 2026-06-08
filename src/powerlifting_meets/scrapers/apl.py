from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class APLScraper(TribeEventsScraper):
    # Australian Powerlifting League. WordPress + Tribe Events.
    federation = "APL"
    base_url = "https://aplpowerlifting.com"
