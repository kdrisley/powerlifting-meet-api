from powerlifting_meets.normalize import (
    normalize_country,
    normalize_state,
    parse_address_location,
    parse_trailing_country,
    parse_trailing_location,
    resolve_location,
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


class TestNormalizeCountry:
    def test_canonical_and_aliases(self):
        assert normalize_country("South Africa") == "South Africa"
        assert normalize_country("usa") == "United States"
        assert normalize_country("England") == "United Kingdom"
        assert normalize_country(" canada ") == "Canada"

    def test_unknown_and_empty(self):
        assert normalize_country(None) is None
        assert normalize_country("") is None
        assert normalize_country("Atlantis") is None


class TestParseTrailingCountry:
    def test_multi_word_country(self):
        assert parse_trailing_country("Port Elizabeth South Africa") == (
            "Port Elizabeth",
            "South Africa",
        )

    def test_single_word_country(self):
        assert parse_trailing_country("Sierre Switzerland") == (
            "Sierre",
            "Switzerland",
        )

    def test_alias_canonicalized(self):
        assert parse_trailing_country("London England") == ("London", "United Kingdom")

    def test_bare_country_has_no_city(self):
        assert parse_trailing_country("Australia") is None

    def test_no_country(self):
        assert parse_trailing_country("Lombard IL") is None


class TestResolveLocation:
    def test_space_separated_us_state(self):
        assert resolve_location("Royal Oak MI") == ("Royal Oak", "MI", "United States")

    def test_comma_us_state(self):
        assert resolve_location("Houston, TX") == ("Houston", "TX", "United States")

    def test_venue_city_state(self):
        assert resolve_location("Big Dog Barbell, Atlanta, GA") == (
            "Atlanta",
            "GA",
            "United States",
        )

    def test_international(self):
        assert resolve_location("Port Elizabeth South Africa") == (
            "Port Elizabeth",
            None,
            "South Africa",
        )

    def test_comma_country(self):
        assert resolve_location("Toronto, Canada") == ("Toronto", None, "Canada")

    def test_unresolvable_and_empty(self):
        assert resolve_location("Drogheda") == (None, None, None)
        assert resolve_location(None) == (None, None, None)
        assert resolve_location("") == (None, None, None)

    def test_bare_state_code(self):
        assert resolve_location("IL") == (None, "IL", "United States")

    def test_bare_country(self):
        assert resolve_location("Australia") == (None, None, "Australia")
