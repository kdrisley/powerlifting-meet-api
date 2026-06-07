import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from powerlifting_meets.scrapers.spf import MEET_PAGE_BASE, SPFScraper


@pytest.fixture
def spf_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "spf_meets_sanity.json").read_text())


def _scraper_with_fixture(fixture: dict) -> SPFScraper:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=fixture)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with patch.object(SPFScraper, "__init__", lambda self, **kw: None):
        scraper = SPFScraper()
        scraper.client = client
        scraper._owns_client = False
    return scraper


class TestSPFScraper:
    def test_scrape_from_fixture(self, spf_fixture: dict):
        scraper = _scraper_with_fixture(spf_fixture)
        meets = scraper.scrape()

        assert len(meets) == 4
        assert all(m.federation == "SPF" for m in meets)

    def test_multiday_uppercase_city_with_registration_url(self, spf_fixture: dict):
        scraper = _scraper_with_fixture(spf_fixture)
        m = scraper.scrape()[0]

        assert m.name == "SPF ARKANSAS STRENGTH EXPO & TESTED/UNTESTED NATIONALS"
        assert m.date_start == date(2026, 6, 27)
        assert m.date_end == date(2026, 6, 28)
        # SHOUTING city is normalized to title case.
        assert m.city == "Little Rock"
        assert m.state == "AR"
        assert m.venue == "ARKANSAS STATE FAIRGROUNDS, 2600 Howard Street"
        # url is the SPF meet page; the external sign-up link is registration_url.
        assert str(m.url) == (
            MEET_PAGE_BASE + "spf-arkansas-strength-expo-and-tested-untested-nationals"
        )
        assert str(m.registration_url) == "https://www.invictuspowerlifting.net/schedule"
        assert m.status == "active"
        # First meet director, preferring the public email over the private one.
        assert m.director_name == "David Shirley"
        assert m.director_email == "dshirley.spf@gmail.com"

    def test_director_falls_back_to_contacts(self, spf_fixture: dict):
        scraper = _scraper_with_fixture(spf_fixture)
        m = next(s for s in scraper.scrape() if s.name == "SPF Women's Raw Showdown")
        # No meetDirectors, so the first contact is used.
        assert m.director_name == "Jordan Reed"
        assert m.director_email == "jordan.reed@example.com"

    def test_meet_page_url_with_no_registration_link(self, spf_fixture: dict):
        scraper = _scraper_with_fixture(spf_fixture)
        m = next(s for s in scraper.scrape() if s.name == "SPF Women's Raw Showdown")

        # url is always the meet page; registration_url is None when absent.
        assert str(m.url) == MEET_PAGE_BASE + "spf-womens-raw-showdown"
        assert m.registration_url is None
        assert m.city == "Covington"
        assert m.state == "GA"
        # Equipment/restrictions are inferred from the title, as before.
        assert m.equipment == "Raw"
        assert m.restrictions == "Women Only"

    def test_single_day_has_no_end_date(self, spf_fixture: dict):
        scraper = _scraper_with_fixture(spf_fixture)
        m = next(s for s in scraper.scrape() if s.name == "SPF Women's Raw Showdown")
        assert m.date_end is None

    def test_cancelled_status_preserved(self, spf_fixture: dict):
        scraper = _scraper_with_fixture(spf_fixture)
        m = next(s for s in scraper.scrape() if s.name == "SPF Cancelled Classic")
        assert m.status == "cancelled"
