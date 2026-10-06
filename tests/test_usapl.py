from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from powerlifting_meets.scrapers.usapl import USAPLScraper


@pytest.fixture
def usapl_events_html(fixtures_dir: Path) -> str:
    # Page 4 of https://www.usapowerlifting.com/events as returned through Jina
    # Reader (X-Return-Format: html), captured 2026-10-06.
    return (fixtures_dir / "usapl_events_page.html").read_text()


class TestUSAPLEventsCalendar:
    def test_parses_events_page_and_stops_on_empty_page(self, usapl_events_html: str):
        pages: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            page = request.url.params.get("page")
            pages.append(page)
            return httpx.Response(200, text=usapl_events_html if page == "1" else "<html></html>")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(USAPLScraper, "__init__", lambda self, **kw: None):
            scraper = USAPLScraper()
        scraper.client = client
        scraper._owns_client = False
        with patch("powerlifting_meets.scrapers.usapl.date") as mock_date:
            mock_date.today.return_value = date(2026, 10, 6)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            meets = scraper._scrape_live()

        assert pages[:2] == ["1", "2"]
        assert len(meets) == 9
        freak = meets[0]
        assert freak.name == "2026 USA Powerlifting Freak Fest"
        assert freak.date_start == date(2026, 10, 31)
        assert (freak.city, freak.state) == ("Marshall", "WI")
        assert freak.sanction == "WI-2026-10"
        assert freak.event_level == "LOCAL"
        assert freak.director_name == "Maxwell Soucy"
        assert str(freak.registration_url) == "https://liftingcast.com/meets/mctz2ojn7y6e/registration"
        assert any(m.venue_address for m in meets)

    def test_total_pages_from_results_count(self, usapl_events_html: str):
        from bs4 import BeautifulSoup

        assert USAPLScraper._total_pages(BeautifulSoup(usapl_events_html, "lxml")) == 26


class TestUSAPLSnapshotFallback:
    """USAPL's calendar returns 403 to non-browser clients; the committed
    browser-captured snapshot keeps USAPL meets in the feed."""

    def _scraper(self, handler):
        client = httpx.Client(transport=httpx.MockTransport(handler))
        with patch.object(USAPLScraper, "__init__", lambda self, **kw: None):
            scraper = USAPLScraper()
        scraper.client = client
        scraper._owns_client = False
        return scraper

    def _run(self, scraper, today: date):
        with patch("powerlifting_meets.scrapers.usapl.date") as mock_date:
            mock_date.today.return_value = today
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            return scraper.scrape()

    def test_403_falls_back_to_snapshot(self):
        scraper = self._scraper(lambda req: httpx.Response(403, text="blocked"))
        meets = self._run(scraper, date(2026, 10, 6))
        assert len(meets) > 200
        assert all(m.federation == "USAPL" for m in meets)
        ma = {m.name for m in meets if m.state == "MA"}
        assert "2026 USA Powerlifting Western MASSacre" in ma
        assert "2026 USA Powerlifting Massachusetts State Championships" in ma

    def test_snapshot_fields_and_past_filter(self):
        scraper = self._scraper(lambda req: httpx.Response(403))
        meets = self._run(scraper, date(2026, 11, 14))
        assert all(m.date_start >= date(2026, 11, 14) for m in meets)
        ma = next(m for m in meets if m.name == "2026 USA Powerlifting Massachusetts State Championships")
        assert (ma.date_start, ma.date_end) == (date(2026, 11, 14), date(2026, 11, 15))
        assert ma.city == "Natick"
        assert ma.sanction == "MA-2026-12"
        assert ma.event_level == "STATE"
        assert str(ma.registration_url) == "https://form.jotform.com/260687759978182"
        boston = next(m for m in meets if m.name == "2027 USA Powerlifting Boston Open")
        assert boston.venue_address == "78 Avenue Louis Pasteur, Boston, MA 02115"

    def test_empty_live_parse_falls_back_to_snapshot(self):
        scraper = self._scraper(lambda req: httpx.Response(200, text="<html></html>"))
        assert len(self._run(scraper, date(2026, 10, 6))) > 200

    def test_long_date_range_parsing(self):
        parse = USAPLScraper._parse_long_date_range
        assert parse("October 10, 2026") == (date(2026, 10, 10), None)
        assert parse("October 16, 2026 - October 18, 2026") == (date(2026, 10, 16), date(2026, 10, 18))
        assert parse("garbage") == (None, None)
