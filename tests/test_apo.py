"""APO parses the JSON-LD Event blocks Modern Events Calendar server-renders
on the events page (the plugin's REST route exists but returns no data)."""
from datetime import date
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.apo import APOScraper


@pytest.fixture
def apo_fixture(fixtures_dir: Path) -> str:
    return (fixtures_dir / "apo_events.html").read_text()


def test_parses_jsonld_events(apo_fixture, scraper_runner):
    meets = scraper_runner(APOScraper, apo_fixture, today=date(2026, 6, 9))
    assert len(meets) == 7
    assert all(m.federation == "APO" for m in meets)
    # US-only federation: every meet is stamped, so none need geo inference.
    assert all(m.country == "United States" for m in meets)

    by_date = {m.date_start: m for m in meets}
    west_coast = by_date[date(2026, 6, 13)]
    assert west_coast.name == "2026 APO West Coast War"
    assert west_coast.venue == "Relentless Barbell"
    assert west_coast.city == "Oroville"
    assert west_coast.state == "CA"
    assert str(west_coast.url).startswith("https://apopowerlifting.com/events/")

    # Multi-day: Nationals run July 10-12.
    nationals = by_date[date(2026, 7, 10)]
    assert nationals.date_end == date(2026, 7, 12)

    # Full state name in the address still resolves to a code.
    iron_independence = by_date[date(2026, 7, 18)]
    assert iron_independence.state == "CT"
    assert iron_independence.director_name == "Eric Sirois"


def test_addressless_event_keeps_country_only(apo_fixture, scraper_runner):
    meets = scraper_runner(APOScraper, apo_fixture, today=date(2026, 6, 9))
    shootout = next(m for m in meets if "Southern Shootout" in m.name)
    # Its JSON-LD location block is empty strings; no city/state, but the
    # country stamp keeps it out of the LLM geo tier.
    assert shootout.venue is None
    assert shootout.state is None
    assert shootout.country == "United States"


def test_past_events_filtered(apo_fixture, scraper_runner):
    meets = scraper_runner(APOScraper, apo_fixture, today=date(2026, 8, 15))
    assert all(m.date_start >= date(2026, 8, 15) for m in meets)
    assert len(meets) == 2
