from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class PowerliftingUnitedScraper(TribeEventsScraper):
    federation = "PLU"
    base_url = "https://powerliftingunited.com"
