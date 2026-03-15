from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from powerlifting_meets.scrapers.apf import APFScraper


@pytest.fixture
def apf_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "apf_calendar.html").read_text()


class TestAPFScraper:
    def test_scrape_from_fixture(self, apf_html: str):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=apf_html)

        transport = httpx.MockTransport(mock_handler)
        client = httpx.Client(transport=transport)

        with patch.object(APFScraper, "__init__", lambda self, **kw: None):
            scraper = APFScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.apf.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        # 4 rows in 2026 section + 1 row in 2027 = 5, all dates >= today
        assert len(meets) == 5
        assert all(m.federation == "APF" for m in meets)

        m = meets[0]
        assert m.name == "APF 10th Annual Women's Powerlifting Championships"
        assert m.date_start == date(2026, 3, 14)
        assert m.city == "Westbrooke"
        assert m.state == "ME"
        assert str(m.url) == "https://form.jotform.com/DynaMaxx/9th-annual-womens-apf-meet-entry"

        # International meet has no US state
        m_intl = meets[2]
        assert m_intl.name == "Arise"
        assert m_intl.state is None

        # Illinois meet
        m_il = meets[3]
        assert m_il.state == "IL"
        assert m_il.city == "Lombard"

        # 2027 meet
        m_2027 = meets[4]
        assert m_2027.date_start == date(2027, 5, 1)
        assert m_2027.state == "GA"
        assert m_2027.city == "Atlanta"

    def test_skips_past_events(self, apf_html: str):
        def mock_handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=apf_html)

        transport = httpx.MockTransport(mock_handler)
        client = httpx.Client(transport=transport)

        with patch.object(APFScraper, "__init__", lambda self, **kw: None):
            scraper = APFScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.apf.date") as mock_date:
                # Set today to after all 2026 March meets
                mock_date.today.return_value = date(2026, 4, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        # Only the 2027 meet should survive
        assert len(meets) == 1
        assert meets[0].date_start.year == 2027
