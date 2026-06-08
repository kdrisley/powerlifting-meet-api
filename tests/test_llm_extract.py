from datetime import date

import pytest

from powerlifting_meets import llm_extract
from powerlifting_meets.llm_extract import ExtractedMeet, ExtractionResult, extract_cached
from powerlifting_meets.scrapers.llm_extract_base import (
    ExtractionUnavailable,
    LLMExtractionScraper,
)


class TestContentHash:
    def test_stable_and_sensitive(self):
        a = llm_extract.content_hash(b"hello world")
        assert a == llm_extract.content_hash(b"hello world")
        assert a != llm_extract.content_hash(b"hello world!")


class TestExtractCached:
    def _meet(self, **kw):
        base = dict(name="X Open", date_start="2026-07-04")
        base.update(kw)
        return ExtractedMeet(**base)

    def test_fresh_cache_hit_makes_no_api_call(self, monkeypatch):
        # Any call to the model would fail the test.
        monkeypatch.setattr(
            llm_extract,
            "extract_meets_from_text",
            lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("called")),
        )
        blob = b"some page text"
        cache = {
            "WNPF": {
                "schema_version": llm_extract.SCHEMA_VERSION,
                "content_hash": llm_extract.content_hash(blob),
                "meets": [self._meet().model_dump()],
            }
        }
        out = extract_cached("WNPF", blob, cache, kind="text")
        assert len(out) == 1
        assert out[0].name == "X Open"

    def test_miss_calls_model_and_caches(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            llm_extract,
            "extract_meets_from_text",
            lambda text: calls.append(text)
            or ExtractionResult(meets=[self._meet(city="Tampa", state="FL")]),
        )
        cache: dict = {}
        out = extract_cached("WNPF", b"new text", cache, kind="text")
        assert len(out) == 1 and len(calls) == 1
        entry = cache["WNPF"]
        assert entry["content_hash"] == llm_extract.content_hash(b"new text")
        assert entry["meets"][0]["state"] == "FL"
        # A second call with the same content is now a cache hit (no new call).
        extract_cached("WNPF", b"new text", cache, kind="text")
        assert len(calls) == 1

    def test_stale_hash_triggers_reextraction(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            llm_extract,
            "extract_meets_from_text",
            lambda text: calls.append(text) or ExtractionResult(meets=[self._meet()]),
        )
        cache = {
            "WNPF": {
                "schema_version": llm_extract.SCHEMA_VERSION,
                "content_hash": "stale",
                "meets": [],
            }
        }
        extract_cached("WNPF", b"changed", cache, kind="text")
        assert len(calls) == 1
        assert cache["WNPF"]["content_hash"] == llm_extract.content_hash(b"changed")

    def test_no_key_returns_empty_without_caching(self, monkeypatch):
        # extract_meets_from_text returns None when there's no client/key.
        monkeypatch.setattr(llm_extract, "extract_meets_from_text", lambda text: None)
        cache: dict = {}
        assert extract_cached("WNPF", b"x", cache, kind="text") == []
        assert cache == {}

    def test_image_kind_calls_image_extractor(self, monkeypatch):
        monkeypatch.setattr(
            llm_extract,
            "extract_meets_from_image",
            lambda blob, mime: ExtractionResult(meets=[self._meet()]),
        )
        out = extract_cached("NASA", b"\x89PNG...", {}, kind="image", mime_type="image/png")
        assert len(out) == 1


class _FakeScraper(LLMExtractionScraper):
    federation = "FAKE"
    source_id = "FAKE"
    kind = "text"

    def fetch_blob(self):
        return b"blob", "text/plain"


class TestLLMExtractionScraper:
    def test_to_meet_us_vs_international(self):
        sc = _FakeScraper(extract_cache={})
        us = sc._to_meet(
            ExtractedMeet(name="US Meet", date_start="2026-07-04", city="Tampa", state="fl")
        )
        assert us.state == "FL" and us.region is None and us.country == "United States"

        intl = sc._to_meet(
            ExtractedMeet(
                name="Aus Meet",
                date_start="2026-07-04",
                city="Brisbane",
                region="QLD",
                country="Australia",
            )
        )
        assert intl.state is None and intl.region == "QLD" and intl.country == "Australia"

    def test_to_meet_drops_unparseable_date(self):
        sc = _FakeScraper(extract_cache={})
        assert sc._to_meet(ExtractedMeet(name="X", date_start="TBD")) is None

    def test_scrape_uses_cache(self, monkeypatch):
        monkeypatch.setattr(
            llm_extract,
            "extract_cached",
            lambda *a, **k: [ExtractedMeet(name="Cached", date_start="2026-08-01")],
        )
        sc = _FakeScraper(extract_cache={})
        meets = sc.scrape()
        assert len(meets) == 1 and meets[0].name == "Cached"
        assert meets[0].date_start == date(2026, 8, 1)

    def test_scrape_raises_when_no_key_and_no_cache(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setattr(llm_extract, "extract_cached", lambda *a, **k: [])
        sc = _FakeScraper(extract_cache={})
        with pytest.raises(ExtractionUnavailable):
            sc.scrape()
