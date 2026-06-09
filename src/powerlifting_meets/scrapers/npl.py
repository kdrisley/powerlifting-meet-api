from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class NPLScraper(TribeEventsScraper):
    federation = "NPL"
    base_url = "https://npleague.net"
