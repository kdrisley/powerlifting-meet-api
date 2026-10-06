"""Venue street addresses and coordinates carried through to the feed.

The /gyms/ directory on powerliftingrecords.com locates host gyms from these
fields, so each scraper that receives an address should keep it.
"""
from datetime import date
from pathlib import Path


from powerlifting_meets.normalize import clean_street_address, split_venue_address
from powerlifting_meets.scrapers.metal_militia import MetalMilitiaScraper
from powerlifting_meets.scrapers.tribe_events import TribeEventsScraper
from powerlifting_meets.scrapers.wabdl import WABDLScraper


class TestCleanStreetAddress:
    def test_keeps_full_address_and_drops_trailing_country(self):
        assert (
            clean_street_address("700 W Wheeler Ave, Aransas Pass, TX 78336, USA")
            == "700 W Wheeler Ave, Aransas Pass, TX 78336"
        )

    def test_rejects_city_state_only(self):
        assert clean_street_address("Aransas Pass, TX") is None
        assert clean_street_address("Arsenal Fitness") is None
        assert clean_street_address("") is None
        assert clean_street_address(None) is None

    def test_collapses_whitespace_and_newlines(self):
        assert clean_street_address("12 Main St\nSpringfield ,  IL") == "12 Main St, Springfield, IL"


class TestSplitVenueAddress:
    def test_leading_venue_name(self):
        assert split_venue_address(
            "All American Gym, 1245 George Jenkins Blvd, Lakeland, Florida, United States"
        ) == ("All American Gym", "1245 George Jenkins Blvd, Lakeland, Florida")

    def test_no_venue_name(self):
        assert split_venue_address("16179 Pecan Grove, Trumann, Arkansas") == (
            None,
            "16179 Pecan Grove, Trumann, Arkansas",
        )

    def test_not_an_address(self):
        assert split_venue_address("Trumann, Arkansas") == (None, None)


class TestTribeVenueAddress:
    def test_joins_parts_and_reads_coordinates(self):
        address, lat, lng = TribeEventsScraper._venue_address(
            {
                "address": "2315 Bob Wallace Ave SW Suite 114",
                "zip": "35805",
                "geo_lat": 34.7,
                "geo_lng": "-86.6",
            },
            "Huntsville",
            "AL",
        )
        assert address == "2315 Bob Wallace Ave SW Suite 114, Huntsville, AL 35805"
        assert (lat, lng) == (34.7, -86.6)

    def test_missing_street_and_zero_coordinates(self):
        assert TribeEventsScraper._venue_address(
            {"address": "", "geo_lat": 0, "geo_lng": 0}, "Huntsville", "AL"
        ) == (None, None, None)


def test_metal_militia_keeps_address_and_coordinates(fixtures_dir: Path, scraper_runner):
    html = (fixtures_dir / "metal_militia_meets.html").read_text()
    meets = scraper_runner(MetalMilitiaScraper, html, today=date(2026, 6, 9))
    with_address = [m for m in meets if m.venue_address]
    assert with_address, "expected at least one Wix event with a street address"
    m = with_address[0]
    assert m.venue_address[0].isdigit()
    assert not m.venue_address.endswith("USA")
    assert m.venue_lat is not None and m.venue_lng is not None


def test_wabdl_splits_venue_from_location(fixtures_dir: Path, scraper_runner):
    ics = (fixtures_dir / "wabdl.ics").read_text()
    meets = scraper_runner(WABDLScraper, ics, today=date(2020, 1, 1))
    lakeland = [m for m in meets if m.venue == "All American Gym"]
    assert lakeland
    assert lakeland[0].venue_address.startswith("1245 George Jenkins Blvd")


def test_tribe_event_with_venue_list_parses():
    # USPA started returning `venue` as a list for multi-venue events
    # (2026-09), which crashed the whole USPA scrape.
    scraper = TribeEventsScraper.__new__(TribeEventsScraper)
    scraper.federation = "USPA"
    meet = scraper._parse_event(
        {
            "title": "Tested Iron Classic",
            "start_date": "2026-11-07 08:00:00",
            "end_date": "2026-11-07 17:00:00",
            "url": "https://uspa.net/events/x/",
            "venue": [
                {
                    "venue": "Operation Iron Gym",
                    "address": "810 Crossland Avenue",
                    "city": "Clarksville",
                    "stateprovince": "TN",
                    "zip": "37040",
                    "country": "United States",
                }
            ],
        }
    )
    assert meet is not None
    assert meet.state == "TN"
    assert meet.venue == "Operation Iron Gym"
    assert meet.venue_address == "810 Crossland Avenue, Clarksville, TN 37040"
