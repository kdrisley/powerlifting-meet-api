from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class SPFScraper(TribeEventsScraper):
    federation = "SPF"
    base_url = "https://www.southernpowerlifting.com"
