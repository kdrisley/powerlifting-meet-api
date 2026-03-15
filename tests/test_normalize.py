from powerlifting_meets.normalize import normalize_state


class TestNormalizeState:
    def test_abbreviation(self):
        assert normalize_state("TX") == "TX"
        assert normalize_state("tx") == "TX"
        assert normalize_state(" CA ") == "CA"

    def test_full_name(self):
        assert normalize_state("Texas") == "TX"
        assert normalize_state("california") == "CA"
        assert normalize_state("New York") == "NY"

    def test_none_and_empty(self):
        assert normalize_state(None) is None
        assert normalize_state("") is None
        assert normalize_state("  ") is None

    def test_unknown(self):
        assert normalize_state("ON") is None  # Canadian province
        assert normalize_state("XY") is None
