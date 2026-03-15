import json
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

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
        ):
            run()

        meets_json = json.loads((tmp_path / "events").read_text())
        assert meets_json["total_meets"] == 2
        assert meets_json["meets"][0]["name"] == "Test Meet A"
        assert meets_json["meta"]["USPA"]["status"] == "ok"

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
        ):
            run()

        meets_json = json.loads((tmp_path / "events").read_text())
        assert meets_json["total_meets"] == 1
        assert meets_json["meets"][0]["name"] == "Fallback Meet"
        assert meets_json["meta"]["USPA"]["status"] == "stale"
