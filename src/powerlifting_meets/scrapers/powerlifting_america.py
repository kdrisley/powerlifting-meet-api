from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class PowerliftingAmericaScraper(TribeEventsScraper):
    federation = "PA"
    base_url = "https://www.powerlifting-america.com"
