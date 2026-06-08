import pytest

from powerlifting_meets.classify import (
    classify_event_level,
    classify_event_type,
    classify_testing_status,
    normalize_event_level,
)


class TestClassifyEventType:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("2026 Spring Full Power Classic", "full_power"),
            ("State Powerlifting Championship", "full_power"),
            ("Iron City Push Pull", "push_pull"),
            ("Push/Pull Showdown", "push_pull"),
            ("Bench & Deadlift Bash", "push_pull"),
            ("Bench and Deadlift Open", "push_pull"),
            ("Spring Bench Only Meet", "bench_only"),
            ("Annual Bench Press Championship", "bench_only"),
            ("Deadlift Only Mayhem", "deadlift_only"),
            ("Winter Deadlift Open", "deadlift_only"),
            ("Squat Only Spectacular", "squat_only"),
        ],
    )
    def test_classifies(self, name, expected):
        assert classify_event_type(name) == expected

    def test_single_lift_beats_full_power_fallback(self):
        # "Powerlifting" is present but it's really a bench-only meet.
        assert classify_event_type("Bench Press Powerlifting Championship") == "bench_only"

    def test_none_when_unstated(self):
        assert classify_event_type("The Iron Gauntlet") is None
        assert classify_event_type(None) is None
        assert classify_event_type("") is None


class TestNormalizeEventLevel:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("Local", "LOCAL"),
            ("State Championship", "STATE"),
            ("Regionals", "REGIONAL"),
            ("National", "NATIONAL"),
            ("International", "INTERNATIONAL"),
            ("INTERNATIONAL", "INTERNATIONAL"),
        ],
    )
    def test_normalizes(self, raw, expected):
        assert normalize_event_level(raw) == expected

    def test_unknown_level_is_none(self):
        # USAPL lists coaching clinics under "Type of Event"; not a real tier.
        assert normalize_event_level("Coaching") is None
        assert normalize_event_level(None) is None
        assert normalize_event_level("") is None


class TestClassifyEventLevel:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("2026 World Bench Press Championships", "INTERNATIONAL"),
            ("IPF International Cup", "INTERNATIONAL"),
            ("USA National Championships", "NATIONAL"),
            ("Southeast Regional Open", "REGIONAL"),
            ("Texas State Championship", "STATE"),
        ],
    )
    def test_classifies(self, name, expected):
        assert classify_event_level(name) == expected

    def test_highest_tier_wins(self):
        assert classify_event_level("World & National Open") == "INTERNATIONAL"

    def test_no_default_to_local(self):
        # Deliberately None, not LOCAL, when no tier keyword is present.
        assert classify_event_level("Spring Iron Classic") is None
        assert classify_event_level(None) is None


class TestClassifyTestingStatus:
    def test_federation_default_tested(self):
        assert classify_testing_status("USAPL", "Some Meet") == "tested"
        assert classify_testing_status("IPF", "Some Meet") == "tested"

    def test_federation_default_untested(self):
        assert classify_testing_status("APF", "Some Meet") == "untested"
        assert classify_testing_status("SPF", "Some Meet") == "untested"

    def test_name_keyword_overrides_default(self):
        # An untested-federation meet explicitly billed as tested.
        assert classify_testing_status("APF", "WPC Drug Tested Open") == "tested"
        # A tested-federation meet explicitly billed as untested.
        assert classify_testing_status("USAPL", "Untested Showdown") == "untested"

    def test_both_posture_federation_uses_name_only(self):
        # USPA runs both; no default, so name is the only signal.
        assert classify_testing_status("USPA", "Tested Classic") == "tested"
        assert classify_testing_status("USPA", "Spring Open") is None

    def test_open_is_not_untested(self):
        # "Open" is an age division, not a testing signal.
        assert classify_testing_status("USPA", "Summer Open") is None
