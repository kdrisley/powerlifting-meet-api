from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class NZPUScraper(TribeEventsScraper):
    # New Zealand Powerlifting United. WordPress + Tribe Events.
    federation = "NZPU"
    base_url = "https://nzpu.org"
