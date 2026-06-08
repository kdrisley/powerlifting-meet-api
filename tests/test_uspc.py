import json
from datetime import date
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.uspc import USPCScraper


@pytest.fixture
def uspc_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "uspc_tockify.json").read_text())


def test_parses_tockify_events(uspc_fixture, scraper_runner):
    meets = scraper_runner(USPCScraper, uspc_fixture)
    assert len(meets) == 4
    assert all(m.federation == "USPC" for m in meets)

    m = meets[0]
    # The ", City, ST" tail is stripped from the summary to get a clean name.
    assert m.name == "USPC Iron City Open"
    assert m.date_start == date(2026, 6, 13)
    # The full street address is preferred over the summary's branding city.
    assert m.city == "Washington"
    assert m.state == "PA"
    assert m.region is None
    assert m.country == "United States"
    assert m.status == "active"
    assert str(m.url) == "https://tockify.com/uspcdates/detail/324/1781323200000"


def test_filters_past_meets(uspc_fixture, scraper_runner):
    meets = scraper_runner(USPCScraper, uspc_fixture, today=date(2026, 7, 1))
    # Only the 2026-07-11 meet remains.
    assert all(m.date_start >= date(2026, 7, 1) for m in meets)
    assert len(meets) == 1
