from __future__ import annotations

US_STATES: dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA", "west virginia": "WV",
    "wisconsin": "WI", "wyoming": "WY", "district of columbia": "DC",
}

_VALID_ABBREVS = set(US_STATES.values())

# Canadian provinces/territories. Not US states, so normalize_state() leaves
# them as None, but they're valid trailing-location codes in meet titles
# (e.g. RPS lists meets in Ontario), so we still want to split them off.
CANADIAN_PROVINCES: set[str] = {
    "AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
}

# Two-letter codes that signal a trailing "City ST" location in a meet title.
LOCATION_CODES: frozenset[str] = frozenset(_VALID_ABBREVS | CANADIAN_PROVINCES)


def normalize_state(raw: str | None) -> str | None:
    """Normalize a state name or abbreviation to a two-letter code."""
    if not raw:
        return None
    cleaned = raw.strip()
    upper = cleaned.upper()
    if upper in _VALID_ABBREVS:
        return upper
    lookup = US_STATES.get(cleaned.lower())
    return lookup
