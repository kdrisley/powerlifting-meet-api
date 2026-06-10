"""powerlifting.com aggregator: emit only organizer-allowlisted federations we
have no direct scraper for; drop covered feds, non-powerlifting sports, and
unknown organizers (logging the unknowns for allowlist review)."""
import json
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.powerlifting_com import (
    ORGANIZER_TO_FED,
    PowerliftingComScraper,
)


@pytest.fixture
def plcom_fixture(fixtures_dir: Path) -> dict:
    return json.loads((fixtures_dir / "powerlifting_com_tribe.json").read_text())


def test_emits_only_allowlisted_federations(plcom_fixture, scraper_runner):
    meets = scraper_runner(PowerliftingComScraper, plcom_fixture)
    # 11 fixture events: 6 allowlisted; USA Powerlifting (covered), two
    # strongman events, "* Powerlifting" (unknown), and an organizer-less
    # event are dropped.
    assert len(meets) == 6
    assert sorted(m.federation for m in meets) == [
        "365Strong", "APU", "IPO", "WRPF", "WRPF", "WUAP",
    ]
    # No meet leaks the aggregator's own meta key.
    assert all(m.federation != "PLCOM" for m in meets)
    titles = " ".join(m.name for m in meets)
    assert "Strongman" not in titles
    assert "Holloman" not in titles


def test_wrpf_uk_event_fields(plcom_fixture, scraper_runner):
    meets = scraper_runner(PowerliftingComScraper, plcom_fixture)
    wy = next(m for m in meets if m.name == "West Yorkshire Qualifier II")
    assert wy.federation == "WRPF"
    assert wy.city == "Ossett"
    assert wy.region == "West Yorkshire"
    assert wy.state is None
    assert wy.country == "United Kingdom"
    assert "powerlifting.com/event/" in str(wy.url)
    assert "jotform.com" in str(wy.registration_url)
    # The Tribe organizer is the federation, not a meet director.
    assert wy.director_name is None
    assert wy.director_email is None


def test_us_event_resolves_state(plcom_fixture, scraper_runner):
    meets = scraper_runner(PowerliftingComScraper, plcom_fixture)
    tn = next(m for m in meets if m.federation == "APU")
    assert tn.state == "TN"
    assert tn.region is None
    assert tn.country == "United States"
    assert "americanpowerliftingunion.com" in str(tn.registration_url)


def test_both_wrpf_organizers_map_to_one_code(plcom_fixture, scraper_runner):
    meets = scraper_runner(PowerliftingComScraper, plcom_fixture)
    wrpf = [m for m in meets if m.federation == "WRPF"]
    # One from "World Raw Powerlifting Federation" (UK), one from
    # "... Federation Canada" — a single fed code for consumers.
    assert {m.country for m in wrpf} == {"United Kingdom", "Canada"}


def test_unknown_organizers_are_tracked_not_emitted(plcom_fixture, scraper_runner):
    import httpx
    from unittest.mock import patch

    def handler(request):
        return httpx.Response(200, json=plcom_fixture)

    with patch.object(PowerliftingComScraper, "__init__", lambda self, **kw: None):
        scraper = PowerliftingComScraper()
        scraper.client = httpx.Client(transport=httpx.MockTransport(handler))
        scraper._owns_client = False
        scraper.scrape()
    assert scraper._unmatched["Man Beast Strongman"] == 1
    assert scraper._unmatched["* Powerlifting"] == 1
    # Covered feds and known non-powerlifting organizers drop silently.
    assert "USA Powerlifting" not in scraper._unmatched
    assert "United States Strongman" not in scraper._unmatched


def test_fallback_federations_cover_emitted_codes():
    assert PowerliftingComScraper.fallback_federations == frozenset(
        ORGANIZER_TO_FED.values()
    )
