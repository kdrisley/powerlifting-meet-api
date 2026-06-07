from datetime import date

from powerlifting_meets import llm_geo
from powerlifting_meets.llm_geo import GeoGuess
from powerlifting_meets.models import Meet
from powerlifting_meets.runner import infer_missing_locations


def make_meet(**kw) -> Meet:
    base = dict(name="York PA July Meet", federation="RPS", date_start=date(2026, 7, 12))
    base.update(kw)
    return Meet(**base)


class TestInferLocationNoKey:
    def test_returns_none_without_api_key(self, monkeypatch):
        # No key -> no client -> no network call, just None.
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert llm_geo.infer_location(make_meet()) is None


class TestCacheKeying:
    def test_cache_key_is_identity(self):
        assert llm_geo.cache_key(make_meet()) == "RPS|York PA July Meet|2026-07-12"

    def test_signals_hash_changes_with_inputs(self):
        h1 = llm_geo.signals_hash(make_meet())
        h2 = llm_geo.signals_hash(make_meet(venue="Some Gym"))
        assert h1 != h2
        # Stable for identical inputs.
        assert llm_geo.signals_hash(make_meet()) == h1


class TestInferMissingLocations:
    def test_cache_hit_applies_without_calling_model(self, monkeypatch):
        # If the model were called, this would blow up the test.
        monkeypatch.setattr(
            llm_geo, "infer_location", lambda m: (_ for _ in ()).throw(AssertionError("called"))
        )
        meet = make_meet()
        cache = {
            llm_geo.cache_key(meet): {
                "schema_version": llm_geo.SCHEMA_VERSION,
                "signals_hash": llm_geo.signals_hash(meet),
                "city": "York",
                "state": "PA",
                "country": "United States",
                "confidence": 0.9,
                "reasoning": "York, PA is in the name.",
            }
        }
        applied = infer_missing_locations([meet], cache)
        assert applied == 1
        assert (meet.city, meet.state, meet.country) == ("York", "PA", "United States")
        assert meet.geo_inferred is True

    def test_miss_calls_model_and_caches(self, monkeypatch):
        monkeypatch.setattr(
            llm_geo,
            "infer_location",
            lambda m: GeoGuess(
                city="Drogheda", state=None, country="Ireland", confidence=0.85, reasoning="x"
            ),
        )
        meet = make_meet(name="Battle of the Boyne", city="Drogheda")
        cache: dict = {}
        applied = infer_missing_locations([meet], cache)
        assert applied == 1
        assert meet.country == "Ireland"
        assert meet.state is None
        assert meet.geo_inferred is True
        # Result is cached for next time, keyed by identity + signals.
        entry = cache[llm_geo.cache_key(meet)]
        assert entry["country"] == "Ireland"
        assert entry["signals_hash"] == llm_geo.signals_hash(meet)

    def test_low_confidence_is_cached_but_not_applied(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            llm_geo,
            "infer_location",
            lambda m: calls.append(1)
            or GeoGuess(city=None, state=None, country=None, confidence=0.2, reasoning="unsure"),
        )
        meet = make_meet()
        cache: dict = {}
        assert infer_missing_locations([meet], cache) == 0
        assert meet.state is None and meet.country is None
        assert meet.geo_inferred is False
        # Negative result is cached, so a second pass makes no new call.
        infer_missing_locations([meet], cache)
        assert len(calls) == 1

    def test_skips_meets_that_already_have_location(self, monkeypatch):
        monkeypatch.setattr(
            llm_geo, "infer_location", lambda m: (_ for _ in ()).throw(AssertionError("called"))
        )
        with_state = make_meet(state="TX")
        with_country = make_meet(country="Ireland")
        assert infer_missing_locations([with_state, with_country], {}) == 0

    def test_stale_signals_hash_triggers_recheck(self, monkeypatch):
        monkeypatch.setattr(
            llm_geo,
            "infer_location",
            lambda m: GeoGuess(
                city="York", state="PA", country="United States", confidence=0.9, reasoning="x"
            ),
        )
        meet = make_meet()
        expected_hash = llm_geo.signals_hash(meet)  # from scraped inputs, pre-apply
        cache = {
            llm_geo.cache_key(meet): {
                "schema_version": llm_geo.SCHEMA_VERSION,
                "signals_hash": "stale-hash",
                "city": None,
                "state": None,
                "country": None,
                "confidence": 0.1,
                "reasoning": "old",
            }
        }
        applied = infer_missing_locations([meet], cache)
        assert applied == 1
        assert meet.state == "PA"
        # Cache was refreshed with the current input signals.
        assert cache[llm_geo.cache_key(meet)]["signals_hash"] == expected_hash
