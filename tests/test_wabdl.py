from datetime import date
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.wabdl import WABDLScraper


@pytest.fixture
def wabdl_ics(fixtures_dir: Path) -> str:
    return (fixtures_dir / "wabdl.ics").read_text()


def test_parses_ical_feed(wabdl_ics, scraper_runner):
    meets = scraper_runner(WABDLScraper, wabdl_ics)
    assert len(meets) == 4
    assert all(m.federation == "WABDL" for m in meets)

    m = meets[0]
    assert m.name == "WABDL Southern Nationals"
    assert m.date_start == date(2026, 3, 7)
    # Full state name in the address resolves to a US code.
    assert m.city == "Trumann"
    assert m.state == "AR"
    assert m.country == "United States"
    assert str(m.url) == "https://wabdl.org/events/wabdl-southern-nationals-3/"


def test_filters_past_meets(wabdl_ics, scraper_runner):
    meets = scraper_runner(WABDLScraper, wabdl_ics, today=date(2026, 3, 15))
    # Only the 2026-03-22 meet remains.
    assert all(m.date_start >= date(2026, 3, 15) for m in meets)
    assert len(meets) == 1
