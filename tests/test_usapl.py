from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from powerlifting_meets.scrapers.usapl import USAPLScraper


@pytest.fixture
def usapl_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "usapl_calendar.html").read_text()


class TestUSAPLScraper:
    def test_scrape_from_fixture(self, usapl_html: str):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=usapl_html)

        transport = httpx.MockTransport(mock_handler)
        client = httpx.Client(transport=transport)

        with patch.object(USAPLScraper, "__init__", lambda self, **kw: None):
            scraper = USAPLScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.usapl.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        assert len(meets) == 3
        assert all(m.federation == "USAPL" for m in meets)

        m = meets[0]
        assert m.name == "2026 USA Powerlifting Surge Legacy Series"
        assert m.date_start == date(2026, 3, 14)
        assert m.city == "Carol Stream"
        assert m.state == "IL"
        assert str(m.url) == "https://liftingcast.com/meets/m0247b0mongl/registration"

    def test_date_range_parsing(self):
        scraper = USAPLScraper.__new__(USAPLScraper)

        # Single date
        start, end = scraper._parse_date_range("Mar 14, 2026")
        assert start == date(2026, 3, 14)
        assert end is None

        # Same-month range
        start, end = scraper._parse_date_range("Mar 14-15, 2026")
        assert start == date(2026, 3, 14)
        assert end == date(2026, 3, 15)

        # Cross-month range
        start, end = scraper._parse_date_range("Mar 30 - Apr 1, 2026")
        assert start == date(2026, 3, 30)
        assert end == date(2026, 4, 1)
