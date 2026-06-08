from __future__ import annotations

from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper


class ADFPFScraper(TribeEventsScraper):
    # American Drug-Free Powerlifting Federation. Lives at adfpf.net (the .org /
    # .com domains have lapsed); WordPress + The Events Calendar (Tribe) plugin.
    federation = "ADFPF"
    base_url = "https://adfpf.net"
