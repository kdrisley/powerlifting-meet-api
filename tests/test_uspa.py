import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from powerlifting_meets.scrapers.uspa import USPAScraper


@pytest.fixture
def uspa_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "uspa_events_page1.json").read_text())


class TestUSPAScraper:
    def test_scrape_from_fixture(self, uspa_fixture: dict):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=uspa_fixture)

        transport = httpx.MockTransport(mock_handler)
        client = httpx.Client(transport=transport)

        with patch.object(USPAScraper, "__init__", lambda self, **kw: None):
            scraper = USPAScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.tribe_events.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        assert len(meets) == 3
        assert all(m.federation == "USPA" for m in meets)

        # First meet
        m = meets[0]
        assert m.name == "USPA Tested and Open Luck of the Lift, Huntsville, Alabama"
        assert m.date_start == date(2026, 3, 14)
        assert m.city == "Huntsville"
        assert m.state == "AL"
        assert m.venue == "Arsenal Fitness"

    def test_scrape_sets_federation(self, uspa_fixture: dict):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=uspa_fixture)

        transport = httpx.MockTransport(mock_handler)
        client = httpx.Client(transport=transport)

        with patch.object(USPAScraper, "__init__", lambda self, **kw: None):
            scraper = USPAScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.tribe_events.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        for m in meets:
            assert m.federation == "USPA"
