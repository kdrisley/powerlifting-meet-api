import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from powerlifting_meets.scrapers.spf import SPFScraper


@pytest.fixture
def spf_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "spf_events_page1.json").read_text())


class TestSPFScraper:
    def test_scrape_from_fixture(self, spf_fixture: dict):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=spf_fixture)

        transport = httpx.MockTransport(mock_handler)
        client = httpx.Client(transport=transport)

        with patch.object(SPFScraper, "__init__", lambda self, **kw: None):
            scraper = SPFScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.tribe_events.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        assert len(meets) == 3
        assert all(m.federation == "SPF" for m in meets)

        m = meets[0]
        assert m.name == "The Searcy Showdown"
        assert m.date_start == date(2026, 3, 14)
        assert m.city == "Covington"
        assert m.state == "GA"
