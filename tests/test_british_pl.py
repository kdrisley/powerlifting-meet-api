"""British Powerlifting parses the server-rendered cards on its two upcoming-
meet listing pages (championships + major events)."""
from datetime import date
from pathlib import Path

import httpx
import pytest

from powerlifting_meets.scrapers.british_pl import BritishPLScraper


@pytest.fixture
def bp_handler(fixtures_dir: Path):
    champs = (fixtures_dir / "britishpl_championships.html").read_text()
    events = (fixtures_dir / "britishpl_events.html").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        page = champs if "championships" in str(request.url) else events
        return httpx.Response(200, text=page)

    return handler


def test_parses_both_listing_pages(bp_handler, scraper_runner):
    meets = scraper_runner(BritishPLScraper, bp_handler, today=date(2026, 6, 9))
    # 13 divisional cards + 1 major event (SBD British Open) on capture day.
    assert len(meets) == 14
    assert all(m.federation == "BritishPL" for m in meets)
    # Single-country fed: every meet stamped, none left for geo inference.
    assert all(m.country == "United Kingdom" for m in meets)
    assert all(m.state is None for m in meets)
    assert all(m.url is not None for m in meets)


def test_date_range_and_level_parsing(bp_handler, scraper_runner):
    meets = scraper_runner(BritishPLScraper, bp_handler, today=date(2026, 6, 9))
    by_name = {m.name: m for m in meets}

    slam = by_name["Summer Slam 2026"]
    assert slam.date_start == date(2026, 6, 13)
    assert slam.date_end == date(2026, 6, 14)
    # "Divisional" is a tier word, not a region.
    assert slam.event_level == "REGIONAL"
    assert slam.region is None

    # A division named by region: deterministic region signal, no tier.
    west_mids = by_name["West Midlands Summer Cup 2026"]
    assert west_mids.date_start == date(2026, 7, 5)
    assert west_mids.date_end is None
    assert west_mids.region == "West Midlands"
    assert west_mids.event_level is None

    open_champs = by_name["SBD British Open Championships"]
    assert open_champs.date_start == date(2026, 12, 4)
    assert open_champs.date_end == date(2026, 12, 6)
    assert "/event/" in str(open_champs.url)


def test_past_meets_filtered(bp_handler, scraper_runner):
    meets = scraper_runner(BritishPLScraper, bp_handler, today=date(2026, 12, 1))
    assert all(m.date_start >= date(2026, 12, 1) for m in meets)


def test_new_year_range_rolls_end_forward():
    parsed = BritishPLScraper._parse_dates("30 Dec - 2 Jan, 2026")
    assert parsed == (date(2026, 12, 30), date(2027, 1, 2))
