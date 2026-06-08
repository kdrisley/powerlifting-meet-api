from datetime import date
from pathlib import Path

import httpx

from powerlifting_meets.scrapers.irish import IrishScraper


def _handler(fixtures_dir: Path):
    body = (fixtures_dir / "irish_calendar.html").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        if "calendar-2026" in str(request.url):
            return httpx.Response(200, text=body)
        return httpx.Response(404, text="not found")

    return handler


def test_parses_calendar_table(fixtures_dir, scraper_runner):
    meets = scraper_runner(IrishScraper, _handler(fixtures_dir), today=date(2026, 1, 1))
    assert len(meets) >= 6
    assert all(m.federation == "IrishPF" for m in meets)
    assert all(m.country == "Ireland" and m.state is None for m in meets)

    m = meets[0]
    assert m.name == "February Open"
    assert m.date_start == date(2026, 2, 7)
    assert m.date_end == date(2026, 2, 8)
    assert m.venue == "Phenom"
    assert m.city == "Cork"


def test_single_day_has_no_end(fixtures_dir, scraper_runner):
    meets = scraper_runner(IrishScraper, _handler(fixtures_dir), today=date(2026, 1, 1))
    bench = next(m for m in meets if m.name == "Bench Nationals")
    assert bench.date_start == date(2026, 3, 7)
    assert bench.date_end is None
