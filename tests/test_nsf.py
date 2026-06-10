"""NSF parses the year-long terminliste table, keeping open/championship meets
and dropping club nights, IPF internationals (already on our IPF feed), and
courses."""
from datetime import date
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.nsf import NSFScraper


@pytest.fixture
def nsf_fixture(fixtures_dir: Path) -> str:
    return (fixtures_dir / "nsf_terminliste.html").read_text()


def test_keeps_open_and_championship_meets_only(nsf_fixture, scraper_runner):
    meets = scraper_runner(NSFScraper, nsf_fixture, today=date(2026, 1, 1))
    # 45 Åpent stevne + 14 Regionsmesterskap + 7 Mesterskapsstevne in the 2026
    # capture; Klubbstevne (77), Internasjonalt stevne (20) and Kurs (1) drop
    # by type, and 5 club nights mislabeled "Åpent stevne" but named just
    # "Klubbstevne" drop by name.
    assert len(meets) == 61
    assert all(m.federation == "NSF" for m in meets)
    assert all(m.country == "Norway" for m in meets)
    assert all(m.state is None for m in meets)
    names = " ".join(m.name for m in meets)
    assert all(m.name.lower() != "klubbstevne" for m in meets)
    # The IPF international listed in the table (SBD Sheffield) is dropped.
    assert "Sheffield" not in names


def test_row_parsing(nsf_fixture, scraper_runner):
    meets = scraper_runner(NSFScraper, nsf_fixture, today=date(2026, 1, 1))
    first = meets[0]  # Bjørgvin Open, 03. Januar
    assert first.name == "Bjørgvin Open"
    assert first.date_start == date(2026, 1, 3)
    assert first.venue == "Bjørgvin Treningssenter"

    # Month sections advance the implied month.
    rm = next(m for m in meets if m.name == "Regionmesterskap Nordland")
    assert rm.date_start == date(2026, 1, 17)

    # Multi-day "NN.-NN." spans parse into start/end.
    multi = [m for m in meets if m.date_end is not None]
    assert multi, "expected at least one multi-day meet in the capture"
    assert all(m.date_end > m.date_start for m in multi)


def test_entry_list_link_becomes_url(nsf_fixture, scraper_runner):
    meets = scraper_runner(NSFScraper, nsf_fixture, today=date(2026, 1, 1))
    linked = [m for m in meets if m.url is not None]
    assert linked
    assert all("pameldingsliste" in str(m.url) for m in linked)
    assert all(str(m.url).startswith("https://styrkeloft.no/") for m in linked)


def test_past_meets_filtered(nsf_fixture, scraper_runner):
    meets = scraper_runner(NSFScraper, nsf_fixture, today=date(2026, 9, 1))
    assert all(m.date_start >= date(2026, 9, 1) for m in meets)
