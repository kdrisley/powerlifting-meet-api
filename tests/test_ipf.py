from collections import Counter
from datetime import date
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.ipf import IPFScraper


@pytest.fixture
def ipf_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "ipf_calendar.html").read_text()


def test_parses_ipf_and_epf_rows(ipf_html, scraper_runner):
    meets = scraper_runner(IPFScraper, ipf_html, today=date(2026, 1, 1))
    feds = Counter(m.federation for m in meets)
    # The calendar carries both global IPF and European EPF championships.
    assert feds["IPF"] > 0 and feds["EPF"] > 0
    # Only those two confederations are kept (no APF/NAPF/etc. collisions).
    assert set(feds) <= {"IPF", "EPF"}

    sheffield = next(m for m in meets if "Sheffield" in m.name)
    assert sheffield.federation == "IPF"
    assert sheffield.date_start == date(2026, 1, 31)
    assert sheffield.date_end is None
    assert sheffield.city == "Sheffield"
    assert sheffield.country == "United Kingdom"
    assert sheffield.state is None
    assert sheffield.event_type == "International"


def test_excludes_education_courses(ipf_html, scraper_runner):
    meets = scraper_runner(IPFScraper, ipf_html, today=date(2026, 1, 1))
    assert not any(
        "education" in m.name.lower() or "trainer" in m.name.lower() for m in meets
    )


def test_parses_multiday_range(ipf_html, scraper_runner):
    meets = scraper_runner(IPFScraper, ipf_html, today=date(2026, 1, 1))
    multi = next(m for m in meets if m.date_end is not None)
    assert multi.date_end > multi.date_start
