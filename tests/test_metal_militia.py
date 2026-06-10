"""Metal Militia parses the Wix Events warmup-data JSON the meets page
server-renders (the fixture is the real captured script block; the rest of the
1.3MB Wix page is irrelevant to the scraper)."""
from datetime import date
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.metal_militia import MetalMilitiaScraper


@pytest.fixture
def mm_fixture(fixtures_dir: Path) -> str:
    return (fixtures_dir / "metal_militia_meets.html").read_text()


def test_parses_warmup_data_events(mm_fixture, scraper_runner):
    meets = scraper_runner(MetalMilitiaScraper, mm_fixture, today=date(2026, 6, 9))
    assert len(meets) == 7
    assert all(m.federation == "MetalMilitia" for m in meets)
    assert all(m.country == "United States" for m in meets)
    assert all(m.url is not None for m in meets)

    by_date = {m.date_start: m for m in meets}
    texas = by_date[date(2026, 6, 13)]
    assert texas.name == "Texas Strength Wars 2026"
    # Street address wins over the geocoded metro (Corpus Christi).
    assert texas.city == "Aransas Pass"
    assert texas.state == "TX"
    assert str(texas.url) == (
        "https://www.metalmilitiapowerlifting.com/event-details/texas-strength-wars-2026"
    )
    assert "jotform.com" in str(texas.registration_url)


def test_events_without_external_registration_have_none(mm_fixture, scraper_runner):
    meets = scraper_runner(MetalMilitiaScraper, mm_fixture, today=date(2026, 6, 9))
    fall_brawl = next(m for m in meets if m.name.startswith("Fall Brawl"))
    assert fall_brawl.registration_url is None
    assert fall_brawl.state == "OH"
    # 5 of the 7 captured meets carry JotForm registration links.
    assert sum(1 for m in meets if m.registration_url) == 5


def test_past_meets_filtered(mm_fixture, scraper_runner):
    meets = scraper_runner(MetalMilitiaScraper, mm_fixture, today=date(2026, 10, 1))
    assert all(m.date_start >= date(2026, 10, 1) for m in meets)
    assert len(meets) == 3
