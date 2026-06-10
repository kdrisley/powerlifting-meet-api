"""UKIPL keeps domestic UK meets and drops the IPL internationals its calendar
re-lists (US events are already on the USPA calendar; other internationals will
come from a dedicated IPL feed)."""
import copy
import json
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.ukipl import UKIPLScraper


@pytest.fixture
def ukipl_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "ukipl_tribe.json").read_text())


def test_keeps_only_uk_meets(ukipl_fixture, scraper_runner):
    meets = scraper_runner(UKIPLScraper, ukipl_fixture)
    # 8 events in the fixture: 2 in Las Vegas (venue country) and 1 in Italy
    # (no venue, country only in the title) are dropped.
    assert len(meets) == 5
    assert all(m.federation == "UKIPL" for m in meets)
    assert all(m.country == "United Kingdom" for m in meets)
    assert all(m.state is None for m in meets)
    names = " ".join(m.name for m in meets)
    assert "Las Vegas" not in names
    assert "ITALY" not in names


def test_titles_are_html_unescaped(ukipl_fixture, scraper_runner):
    meets = scraper_runner(UKIPLScraper, ukipl_fixture)
    northern = next(m for m in meets if m.name.startswith("Northern Strength"))
    # Source title is "Northern Strength &#8211; September 5th &#8211; ...".
    assert "&#8211;" not in northern.name
    assert "–" in northern.name


def test_uk_meet_without_venue_is_stamped_uk(ukipl_fixture, scraper_runner):
    # A domestic meet with no venue at all (and no country in its title) must
    # be kept and stamped United Kingdom rather than dropped or left for geo
    # inference.
    data = copy.deepcopy(ukipl_fixture)
    event = next(
        e for e in data["events"] if e["title"].startswith("Northern Strength")
    )
    event["venue"] = []
    meets = scraper_runner(UKIPLScraper, data)
    northern = next(m for m in meets if m.name.startswith("Northern Strength"))
    assert northern.country == "United Kingdom"
    assert northern.city is None
