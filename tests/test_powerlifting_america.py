import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from powerlifting_meets.scrapers.powerlifting_america import PowerliftingAmericaScraper


@pytest.fixture
def pa_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "pa_events_page1.json").read_text())


class TestPAScraper:
    def test_scrape_from_fixture(self, pa_fixture: dict):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=pa_fixture)

        transport = httpx.MockTransport(mock_handler)
        client = httpx.Client(transport=transport)

        with patch.object(PowerliftingAmericaScraper, "__init__", lambda self, **kw: None):
            scraper = PowerliftingAmericaScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.tribe_events.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        assert len(meets) == 3
        assert all(m.federation == "PA" for m in meets)

        m = meets[0]
        assert m.name == "Powerlifting America Dana Rosenzweig"
        assert m.date_start == date(2026, 3, 14)
        assert m.city == "Belleville"
        assert m.state == "IL"
