from powerlifting_meets.normalize import (
    normalize_state,
    parse_address_location,
    parse_trailing_location,
)


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


class TestParseTrailingLocation:
    def test_city_comma_code(self):
        assert parse_trailing_location("Houston, TX") == ("Houston", "TX")

    def test_city_code_no_comma(self):
        assert parse_trailing_location("Lancaster PA") == ("Lancaster", "PA")
        assert parse_trailing_location("Pflugerville TX") == ("Pflugerville", "TX")

    def test_full_state_name(self):
        assert parse_trailing_location("Dayton Ohio") == ("Dayton", "OH")
        assert parse_trailing_location("Some Town, Ohio") == ("Some Town", "OH")

    def test_multi_word_state_name(self):
        assert parse_trailing_location("Charlotte North Carolina") == (
            "Charlotte",
            "NC",
        )
        # Multi-word name wins over the trailing single-word substring.
        assert parse_trailing_location("Morgantown West Virginia") == (
            "Morgantown",
            "WV",
        )

    def test_canadian_province_keeps_city_drops_state(self):
        assert parse_trailing_location("Ottawa, ON") == ("Ottawa", None)

    def test_no_location(self):
        assert parse_trailing_location("Women's Full Power") is None
        assert parse_trailing_location("Round IV") is None
        # A bare state name with no city is not a location.
        assert parse_trailing_location("Indiana") is None


class TestParseAddressLocation:
    def test_full_address(self):
        assert parse_address_location(
            "Arkansas State Fair, 2600 Howard St, Little Rock, AR 72206, USA"
        ) == ("Little Rock", "AR")

    def test_simple_city_state(self):
        assert parse_address_location("80 Piper Rd, Covington, GA 30014") == (
            "Covington",
            "GA",
        )

    def test_no_state(self):
        assert parse_address_location("Arkansas State Fair,") is None
        assert parse_address_location("Crossfit Unyielding") is None
