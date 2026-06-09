"""Tests for the trivial Tribe Events subclass scrapers (US + international).

These share TribeEventsScraper's parsing, so the focus is: each subclass is
wired to the right federation, and the international region/country split works
(state stays US-only; non-US sub-national regions land in `region`).
"""
import json
from pathlib import Path

import pytest

from powerlifting_meets.scrapers.adfpf import ADFPFScraper
from powerlifting_meets.scrapers.apl import APLScraper
from powerlifting_meets.scrapers.npl import NPLScraper
from powerlifting_meets.scrapers.nzpu import NZPUScraper
from powerlifting_meets.scrapers.powerlifting_australia import PowerliftingAustraliaScraper
from powerlifting_meets.scrapers.powerlifting_united import PowerliftingUnitedScraper

CASES = [
    (PowerliftingUnitedScraper, "powerlifting_united_tribe.json", "PLU"),
    (ADFPFScraper, "adfpf_tribe.json", "ADFPF"),
    (PowerliftingAustraliaScraper, "powerlifting_australia_tribe.json", "PA-AUS"),
    (APLScraper, "apl_tribe.json", "APL"),
    (NZPUScraper, "nzpu_tribe.json", "NZPU"),
    (NPLScraper, "npl_tribe.json", "NPL"),
]


def _load(fixtures_dir: Path, name: str) -> dict:
    return json.loads((fixtures_dir / name).read_text())


@pytest.mark.parametrize("scraper_cls,fixture,fed", CASES)
def test_subclass_wiring_and_parsing(scraper_cls, fixture, fed, fixtures_dir, scraper_runner):
    data = _load(fixtures_dir, fixture)
    meets = scraper_runner(scraper_cls, data)
    assert len(meets) == len(data["events"])
    assert all(m.federation == fed for m in meets)
    # Federation invariant: no meet has both a US state and a non-US region.
    assert all(not (m.state and m.region) for m in meets)


def test_us_meet_has_state_no_region(fixtures_dir, scraper_runner):
    meets = scraper_runner(
        PowerliftingUnitedScraper, _load(fixtures_dir, "powerlifting_united_tribe.json")
    )
    m = meets[0]  # Alabama State Games Championships 3
    assert m.city == "Gardendale"
    assert m.state == "AL"
    assert m.region is None
    assert m.country == "United States"


def test_australian_meets_use_region_not_state(fixtures_dir, scraper_runner):
    meets = scraper_runner(
        PowerliftingAustraliaScraper,
        _load(fixtures_dir, "powerlifting_australia_tribe.json"),
    )
    qld = meets[0]  # Aus Powerlifting Championships - North (Brendale, QLD)
    assert qld.state is None
    assert qld.region == "QLD"
    assert qld.city == "Brendale"
    assert qld.country == "Australia"

    # A non-US, non-Australian venue still resolves country + region.
    china = meets[2]  # China Strength Summit (Jinqiao, Pudong)
    assert china.state is None
    assert china.region == "Pudong"
    assert china.country == "China"


def test_apl_full_region_name_lands_in_region(fixtures_dir, scraper_runner):
    meets = scraper_runner(APLScraper, _load(fixtures_dir, "apl_tribe.json"))
    m = meets[0]  # Battle of Brisbane (Windsor, Queensland)
    assert m.state is None
    assert m.region == "Queensland"
    assert m.country == "Australia"


def test_npl_state_resolved_and_stateless_meet_keeps_country(fixtures_dir, scraper_runner):
    meets = scraper_runner(NPLScraper, _load(fixtures_dir, "npl_tribe.json"))
    m = meets[0]  # NPL Pennsylvania State Championship (New Tripoli, PA)
    assert m.city == "New Tripoli"
    assert m.state == "PA"
    assert m.country == "United States"
    # Shikellamy Showdown has no state in the venue; country still comes through.
    shik = next(m for m in meets if "Shikellamy" in m.name)
    assert shik.state is None
    assert shik.country == "United States"


def test_nzpu_country_set_region_optional(fixtures_dir, scraper_runner):
    meets = scraper_runner(NZPUScraper, _load(fixtures_dir, "nzpu_tribe.json"))
    # All NZ meets get the country; region only when the source provides one.
    assert all(m.country == "New Zealand" and m.state is None for m in meets)
    sub_zero = meets[2]  # Sub ZeroW II (Sydenham, Christchurch)
    assert sub_zero.region == "Christchurch"
