from datetime import date
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.nzpu import NZPUScraper


@pytest.fixture
def nzpu_ics(fixtures_dir: Path) -> str:
    return (fixtures_dir / "nzpu.ics").read_text()


def test_parses_ical_feed(nzpu_ics, scraper_runner):
    meets = scraper_runner(NZPUScraper, nzpu_ics, today=date(2026, 10, 9))
    assert [m.name for m in meets] == ["NZPU Nationals 2026", "Iron Hearts"]
    assert all(m.federation == "NZPU" and m.country == "New Zealand" and m.state is None for m in meets)

    nationals = meets[0]
    assert nationals.date_start == date(2026, 12, 4)
    assert nationals.date_end == date(2026, 12, 5)  # DTEND is exclusive
    assert nationals.venue == "ZeroW Chirstchurch"
    assert nationals.city == "Christchurch"
    assert nationals.region == "Canterbury"
    assert str(nationals.url) == "https://nzpu.org/competitions/nzpu-nationals-2026"

    iron = meets[1]
    assert iron.date_end is None  # single-day
    assert iron.city == "Auckland"


def test_filters_past_meets(nzpu_ics, scraper_runner):
    meets = scraper_runner(NZPUScraper, nzpu_ics, today=date(2027, 1, 1))
    assert [m.name for m in meets] == ["Iron Hearts"]
