import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from powerlifting_meets.models import FederationMeta, Meet, MeetsResponse
from powerlifting_meets.runner import (
    fetch_previous_data,
    get_previous_meets_for_federation,
    run,
)


class TestFetchPreviousData:
    def test_returns_none_when_no_url(self):
        assert fetch_previous_data(None) is None

    def test_returns_none_on_error(self):
        assert fetch_previous_data("https://nonexistent.invalid/meets.json") is None

    def test_round_trips_region_from_published_feed(self):
        """A non-US meet's region survives the published-feed round-trip."""
        import httpx

        feed = {
            "generated_at": "2026-03-13T00:00:00+00:00",
            "total_meets": 1,
            "events": [
                {
                    "parsed_date": "2026-07-12",
                    "evt_name": "Battle of Brisbane",
                    "fed": "APL",
                    "state": "",
                    "region": "QLD",
                    "city": "Windsor",
                    "country": "Australia",
                }
            ],
            "meta": {},
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=feed)

        with patch("powerlifting_meets.runner.httpx.get") as mock_get:
            mock_get.return_value = httpx.Client(
                transport=httpx.MockTransport(handler)
            ).get("https://example.invalid/events")
            result = fetch_previous_data("https://example.invalid/events")

        assert result is not None
        meet = result.meets[0]
        assert meet.region == "QLD"
        assert meet.state is None
        assert meet.country == "Australia"


class TestGetPreviousMeetsForFederation:
    def test_filters_by_federation_and_date(self):
        previous = MeetsResponse(
            generated_at=datetime(2026, 3, 13, tzinfo=timezone.utc),
            total_meets=3,
            meets=[
                Meet(name="Past", federation="USPA", date_start=date(2026, 3, 10)),
                Meet(name="Future USPA", federation="USPA", date_start=date(2026, 4, 1)),
                Meet(name="Future RPS", federation="RPS", date_start=date(2026, 4, 1)),
            ],
        )
        result = get_previous_meets_for_federation(previous, "USPA", date(2026, 3, 14))
        assert len(result) == 1
        assert result[0].name == "Future USPA"

    def test_returns_empty_when_no_previous(self):
        result = get_previous_meets_for_federation(None, "USPA", date(2026, 3, 14))
        assert result == []

    def test_accepts_federation_set_for_aggregators(self):
        previous = MeetsResponse(
            generated_at=datetime(2026, 3, 13, tzinfo=timezone.utc),
            total_meets=3,
            meets=[
                Meet(name="WRPF Meet", federation="WRPF", date_start=date(2026, 4, 1)),
                Meet(name="APU Meet", federation="APU", date_start=date(2026, 4, 1)),
                Meet(name="USPA Meet", federation="USPA", date_start=date(2026, 4, 1)),
            ],
        )
        result = get_previous_meets_for_federation(
            previous, frozenset({"WRPF", "APU"}), date(2026, 3, 14)
        )
        assert sorted(m.federation for m in result) == ["APU", "WRPF"]


class TestRun:
    def test_run_with_mocked_scrapers(self, tmp_path: Path):
        """Test runner produces valid JSON output."""
        mock_meets = [
            Meet(name="Test Meet A", federation="USPA", date_start=date(2026, 4, 1), state="TX"),
            Meet(name="Test Meet B", federation="PA", date_start=date(2026, 5, 1), state="CA"),
        ]

        class FakeScraper:
            federation = "FAKE"
            def __init__(self): pass
            def scrape(self):
                return [mock_meets.pop(0)]
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass

        class FakeScraperA(FakeScraper):
            federation = "USPA"

        class FakeScraperB(FakeScraper):
            federation = "PA"

        with (
            patch("powerlifting_meets.runner.ALL_SCRAPERS", [FakeScraperA, FakeScraperB]),
            patch("powerlifting_meets.runner.OUTPUT_DIR", tmp_path),
            patch("powerlifting_meets.runner.PREVIOUS_DATA_URL", None),
            # Keep run() offline: no geo-cache fetch, no LLM tier (tested
            # separately in test_llm_geo).
            patch("powerlifting_meets.runner.GEO_CACHE_URL", None),
            patch("powerlifting_meets.runner.EXTRACT_CACHE_URL", None),
            patch("powerlifting_meets.runner.infer_missing_locations", return_value=0),
        ):
            run()

        meets_json = json.loads((tmp_path / "events").read_text())
        assert meets_json["total_meets"] == 2
        assert meets_json["events"][0]["evt_name"] == "Test Meet A"
        assert meets_json["events"][0]["fed"] == "USPA"
        assert meets_json["events"][0]["state"] == "TX"
        # US meets carry an empty region; the key is always present.
        assert meets_json["events"][0]["region"] == ""
        assert meets_json["events"][0]["parsed_date"] == "2026-04-01"
        assert meets_json["meta"]["USPA"]["status"] == "ok"

        # The extraction cache is written alongside the events output.
        assert (tmp_path / "extract_cache.json").exists()

        meta_json = json.loads((tmp_path / "meta.json").read_text())
        assert meta_json["total_meets"] == 2

    def test_run_with_scraper_failure_and_fallback(self, tmp_path: Path):
        """Test that runner uses previous data when a scraper fails."""
        previous_response = MeetsResponse(
            generated_at=datetime(2026, 3, 13, tzinfo=timezone.utc),
            total_meets=1,
            meets=[
                Meet(name="Fallback Meet", federation="USPA", date_start=date(2026, 5, 1)),
            ],
            meta={
                "USPA": FederationMeta(
                    status="ok",
                    last_successful_scrape=date(2026, 3, 13),
                    meet_count=1,
                ),
            },
        )

        class FailingScraper:
            federation = "USPA"
            def __init__(self): pass
            def scrape(self):
                raise RuntimeError("Site down")
            def close(self): pass
            def __enter__(self): return self
            def __exit__(self, *a): pass

        with (
            patch("powerlifting_meets.runner.ALL_SCRAPERS", [FailingScraper]),
            patch("powerlifting_meets.runner.OUTPUT_DIR", tmp_path),
            patch("powerlifting_meets.runner.fetch_previous_data", return_value=previous_response),
            # Keep run() offline: no geo-cache fetch, no LLM tier.
            patch("powerlifting_meets.runner.GEO_CACHE_URL", None),
            patch("powerlifting_meets.runner.EXTRACT_CACHE_URL", None),
            patch("powerlifting_meets.runner.infer_missing_locations", return_value=0),
            # Pin "today" so the fallback meet (dated 2026-05-01) stays in the
            # future and isn't filtered out as past.
            patch("powerlifting_meets.runner.date") as mock_date,
        ):
            mock_date.today.return_value = date(2026, 3, 14)
            mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
            run()

        meets_json = json.loads((tmp_path / "events").read_text())
        assert meets_json["total_meets"] == 1
        assert meets_json["events"][0]["evt_name"] == "Fallback Meet"
        assert meets_json["meta"]["USPA"]["status"] == "stale"
