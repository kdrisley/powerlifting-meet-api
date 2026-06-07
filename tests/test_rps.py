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

        assert len(meets) == 6
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

        # No comma between city and state — must still split location off the name
        m = meets[5]
        assert m.name == "Power Palooza 29"
        assert m.city == "Lancaster"
        assert m.state == "PA"
        assert m.status == "active"

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

        # No comma between city and state
        name, city, state = scraper._parse_title("Merry Gainzmas – Pflugerville TX")
        assert name == "Merry Gainzmas"
        assert city == "Pflugerville"
        assert state == "TX"

        # Multi-word city, no comma
        name, city, state = scraper._parse_title("Power Palooza 29 – Lancaster PA")
        assert name == "Power Palooza 29"
        assert city == "Lancaster"
        assert state == "PA"

        # Subtitle ending in two capitals must NOT be treated as a location
        name, city, state = scraper._parse_title("Crowned in Iron II – Women's Full Power")
        assert name == "Crowned in Iron II – Women's Full Power"
        assert city is None
        assert state is None

        # Two separators: only the trailing location is split off
        name, city, state = scraper._parse_title(
            "Crowned in Iron II – Women's Full Power – Fort Mill, SC"
        )
        assert name == "Crowned in Iron II – Women's Full Power"
        assert city == "Fort Mill"
        assert state == "SC"

        # Full state name spelled out, after a dash with no leading space.
        name, city, state = scraper._parse_title(
            "2026 RPS Tri- State Challenge at Mpower Gym- Dayton Ohio"
        )
        assert name == "2026 RPS Tri- State Challenge at Mpower Gym"
        assert city == "Dayton"
        assert state == "OH"

        # Hyphenated city name must stay intact (not split on its hyphen).
        name, city, state = scraper._parse_title("Bench Bash – Wilkes-Barre, PA")
        assert name == "Bench Bash"
        assert city == "Wilkes-Barre"
        assert state == "PA"
