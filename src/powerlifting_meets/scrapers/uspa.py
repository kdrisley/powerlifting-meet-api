from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class USPAScraper(TribeEventsScraper):
    federation = "USPA"
    base_url = "https://uspa.net"
