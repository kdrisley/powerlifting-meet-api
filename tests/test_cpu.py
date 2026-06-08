from datetime import date
from pathlib import Path

import httpx

from powerlifting_meets.scrapers.cpu import CPUScraper


def _make_handler(fixtures_dir: Path):
    sitemap = (fixtures_dir / "cpu_sitemap.xml").read_text()
    bridge = (fixtures_dir / "cpu_event_2026-bridge-city-classic.html").read_text()

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("event-pages-sitemap.xml"):
            return httpx.Response(200, text=sitemap)
        if url.endswith("2026-bridge-city-classic"):
            return httpx.Response(200, text=bridge)
        # Any other event page: no JSON-LD, so it's skipped.
        return httpx.Response(200, text="<html><head></head><body></body></html>")

    return handler


def test_parses_sitemap_and_jsonld(fixtures_dir, scraper_runner):
    meets = scraper_runner(CPUScraper, _make_handler(fixtures_dir))
    # Only the bridge-city page yields a parseable Event; the 2023 slug is
    # filtered out before fetching, and the no-jsonld page yields nothing.
    assert len(meets) == 1

    m = meets[0]
    assert m.federation == "CPU"
    assert m.name == "2026 Bridge City Classic"
    assert m.date_start == date(2026, 8, 7)
    assert m.date_end == date(2026, 8, 8)
    assert m.venue == "Sutherland Curling Rink"
    assert m.city == "Saskatoon"
    # Canadian province lands in `region`, not the US-only `state` field.
    assert m.state is None
    assert m.region == "SK"
    assert m.country == "Canada"
