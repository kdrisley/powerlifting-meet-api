from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from powerlifting_meets.scrapers.rps import RPSScraper


@pytest.fixture
def rps_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "rps_meets.html").read_text()


class TestRPSScraper:
    def test_scrape_from_fixture(self, rps_html: str):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=rps_html)

        transport = httpx.MockTransport(mock_handler)
        client = httpx.Client(transport=transport)

        with patch.object(RPSScraper, "__init__", lambda self, **kw: None):
            scraper = RPSScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.rps.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        assert len(meets) == 5
        assert all(m.federation == "RPS" for m in meets)

        # First meet - Sold Out
        m = meets[0]
        assert m.name == "Dominion"
        assert m.date_start == date(2026, 3, 14)
        assert m.city == "Farmingdale"
        assert m.state == "NY"
        assert m.status == "sold_out"

        # Second meet - active, no status badge
        m = meets[1]
        assert m.name == "17th Bristol Big Bench"
        assert m.city == "Fairless Hills"
        assert m.state == "PA"
        assert m.status == "active"

        # Canadian meet - state should be None
        m = meets[2]
        assert m.name == "Iron Annihilation 9"
        assert m.city == "Ottawa"
        assert m.state is None  # ON is not a US state

    def test_title_parsing(self):
        scraper = RPSScraper.__new__(RPSScraper)

        name, city, state = scraper._parse_title("Big Meet – Houston, TX")
        assert name == "Big Meet"
        assert city == "Houston"
        assert state == "TX"

        name, city, state = scraper._parse_title("Meet Name")
        assert name == "Meet Name"
        assert city is None
        assert state is None
