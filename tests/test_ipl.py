"""IPL scrapes the league's public Google Calendar ICS feed, keeping upcoming
internationals and dropping meets owned by other feeds (US events live on the
USPA calendar, UK events on UKIPL's)."""
from datetime import date
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.ipl import IPLScraper, _registration_url


@pytest.fixture
def ipl_fixture(fixtures_dir: Path) -> str:
    return (fixtures_dir / "ipl_calendar.ics").read_text()


def test_keeps_upcoming_non_us_non_uk_meets(ipl_fixture, scraper_runner):
    meets = scraper_runner(IPLScraper, ipl_fixture, today=date(2026, 6, 9))
    # Fixture has 8 VEVENTs: 1 past (2017) and 2 Las Vegas events are dropped.
    assert len(meets) == 5
    assert all(m.federation == "IPL" for m in meets)
    assert all(m.state is None for m in meets)
    assert all(m.date_start >= date(2026, 6, 9) for m in meets)
    names = " ".join(m.name for m in meets)
    assert "Las Vegas" not in names

    by_date = {m.date_start: m for m in meets}
    czech = by_date[date(2026, 6, 13)]
    assert czech.country == "Czech Republic"
    chile = by_date[date(2026, 10, 1)]
    assert chile.country == "Chile"


def test_serbia_resolves_from_title_when_address_does_not(ipl_fixture, scraper_runner):
    # "Zdravka Čelara 14, Beograd 11060, Serbia" — the venue address doesn't
    # parse, but the title "..., Belgrade, Serbia" does.
    meets = scraper_runner(IPLScraper, ipl_fixture, today=date(2026, 6, 9))
    serbia = next(m for m in meets if m.date_start == date(2026, 9, 5))
    assert serbia.country == "Serbia"


def test_registration_url_from_description(ipl_fixture, scraper_runner):
    meets = scraper_runner(IPLScraper, ipl_fixture, today=date(2026, 6, 9))
    chile = next(m for m in meets if m.date_start == date(2026, 10, 1))
    # The entry link leads the description; the shared classification-standards
    # boilerplate link must never win.
    assert chile.registration_url is not None
    assert "docs.google.com/forms" in str(chile.registration_url)
    assert all(
        "classification-standards" not in str(m.registration_url)
        for m in meets
        if m.registration_url
    )


def test_uk_meets_are_dropped(scraper_runner):
    # No UK event is in the live feed today; prove the ownership rule (UKIPL
    # carries domestic UK meets) against a minimal VEVENT.
    ics = (
        "BEGIN:VCALENDAR\r\n"
        "BEGIN:VEVENT\r\n"
        "DTSTART;VALUE=DATE:20261205\r\n"
        "SUMMARY:IPL British Open\\, Manchester\\, United Kingdom\r\n"
        "LOCATION:Manchester Central\\, Manchester\\, United Kingdom\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    meets = scraper_runner(IPLScraper, ics, today=date(2026, 6, 9))
    assert meets == []


def test_registration_url_helper_skips_boilerplate():
    desc = (
        'Enter here: <a href="https://www.powerlifting-ipl.com/classification-standards/">'
        "standards</a> then https://example.com/register."
    )
    assert _registration_url(desc) == "https://example.com/register"
    assert _registration_url(None) is None
    assert (
        _registration_url("only https://www.powerlifting-ipl.com/classification-standards/")
        is None
    )
