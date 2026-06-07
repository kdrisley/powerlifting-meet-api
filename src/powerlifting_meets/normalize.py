from __future__ import annotations

import re

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


# Full US state names, longest first so multi-word names ("West Virginia",
# "North Carolina") win over a substring ("Virginia", "Carolina") when matching
# the tail of a string.
_STATE_NAMES_BY_LEN: list[str] = sorted(US_STATES, key=len, reverse=True)

# A trailing "City, ST" / "City ST" where the code is a known US state or
# Canadian province (validated against LOCATION_CODES by the caller).
_TRAILING_CODE_RE = re.compile(r"^(?P<city>.+?),?\s+(?P<code>[A-Za-z]{2})$")

# A "City, ST" run embedded in a longer comma-separated address, e.g.
# "..., Little Rock, AR 72206, USA". City is letters/spaces/punctuation but no
# digits or commas, so it can't bleed across address fields.
_ADDRESS_LOCATION_RE = re.compile(
    r"(?P<city>[A-Za-z][A-Za-z .'\-]*?),\s*(?P<code>[A-Z]{2})\b"
)


def parse_trailing_location(text: str) -> tuple[str, str | None] | None:
    """Parse a trailing-location segment into (city, state_code).

    Accepts "City, ST", "City ST", and "City StateName" (full state name,
    possibly multi-word). The two-letter form also accepts Canadian provinces
    (state comes back None, but the city is still split off). Returns None when
    the segment has no recognizable trailing state, so callers can leave the
    text untouched rather than mistaking a meet subtitle for a location.
    """
    s = text.strip()

    m = _TRAILING_CODE_RE.match(s)
    if m and m.group("code").upper() in LOCATION_CODES:
        city = m.group("city").strip()
        if city:
            return city, normalize_state(m.group("code"))

    low = s.lower()
    for name in _STATE_NAMES_BY_LEN:
        if not low.endswith(name):
            continue
        start = len(s) - len(name)
        if start == 0:
            continue  # bare state name, no city
        if s[start - 1].isspace() or s[start - 1] == ",":
            city = s[:start].rstrip().rstrip(",").rstrip()
            if city:
                return city, US_STATES[name]
        break

    return None


def parse_address_location(text: str) -> tuple[str, str] | None:
    """Extract (city, state_code) from a free-text address string.

    Scans for "City, ST" runs (optionally followed by a ZIP) and returns the
    last one, since the city/state sits near the end of a full address ahead of
    the ZIP and country. Returns None when no valid US state code is found.
    """
    match = None
    for m in _ADDRESS_LOCATION_RE.finditer(text):
        if m.group("code").upper() in _VALID_ABBREVS:
            match = m
    if match is None:
        return None
    return match.group("city").strip(), match.group("code").upper()
