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

# Country names we recognize as a trailing token in a location string, mapped to
# a canonical display name. Several federations (notably APF/WPC) list meets
# worldwide as "City CountryName" with no state, so we split the country off to
# keep the city clean and flag the meet as non-US. Lowercase keys; longest-first
# matching means multi-word names ("South Africa") win over a substring.
COUNTRY_ALIASES: dict[str, str] = {
    "united states": "United States", "usa": "United States",
    "united states of america": "United States",
    "canada": "Canada", "mexico": "Mexico",
    "south africa": "South Africa", "australia": "Australia",
    "new zealand": "New Zealand", "switzerland": "Switzerland",
    "united kingdom": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom",
    "wales": "United Kingdom", "northern ireland": "United Kingdom",
    "ireland": "Ireland", "germany": "Germany", "france": "France",
    "spain": "Spain", "portugal": "Portugal", "italy": "Italy",
    "netherlands": "Netherlands", "belgium": "Belgium", "austria": "Austria",
    "sweden": "Sweden", "norway": "Norway", "finland": "Finland",
    "denmark": "Denmark", "iceland": "Iceland", "poland": "Poland",
    "czech republic": "Czech Republic", "hungary": "Hungary",
    "romania": "Romania", "ukraine": "Ukraine", "russia": "Russia",
    "japan": "Japan", "china": "China", "india": "India",
    "south korea": "South Korea", "philippines": "Philippines",
    "indonesia": "Indonesia", "malaysia": "Malaysia", "singapore": "Singapore",
    "thailand": "Thailand", "brazil": "Brazil", "argentina": "Argentina",
    "chile": "Chile", "colombia": "Colombia", "peru": "Peru",
    "egypt": "Egypt", "nigeria": "Nigeria", "kenya": "Kenya",
    "united arab emirates": "United Arab Emirates", "uae": "United Arab Emirates",
    "israel": "Israel", "turkey": "Turkey", "greece": "Greece",
}

# Country names longest-first so multi-word names win over a trailing substring.
_COUNTRY_NAMES_BY_LEN: list[str] = sorted(COUNTRY_ALIASES, key=len, reverse=True)


def normalize_country(raw: str | None) -> str | None:
    """Normalize a country name to its canonical form, or None if unrecognized."""
    if not raw:
        return None
    return COUNTRY_ALIASES.get(raw.strip().lower())


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


def parse_trailing_country(text: str) -> tuple[str, str] | None:
    """Parse a trailing "City CountryName" segment into (city, country).

    Mirrors parse_trailing_location but matches a known country name (possibly
    multi-word, e.g. "Port Elizabeth South Africa"). Returns None when there is
    no recognizable trailing country so callers can leave the text untouched.
    """
    s = text.strip()
    low = s.lower()
    for name in _COUNTRY_NAMES_BY_LEN:
        if not low.endswith(name):
            continue
        start = len(s) - len(name)
        if start == 0:
            break  # bare country name, no city
        if s[start - 1].isspace() or s[start - 1] == ",":
            city = s[:start].rstrip().rstrip(",").rstrip()
            if city:
                return city, COUNTRY_ALIASES[name]
        break
    return None


# A standalone postal-code segment: US ZIP ("72206", "72206-1234") or a
# Canadian/UK-style code ("S7N 1Y3"). Used to drop postal noise from the tail of
# a full street address before reading the state/province.
_POSTAL_RE = re.compile(
    r"^(?:\d{5}(?:-\d{4})?|[A-Za-z]\d[A-Za-z]\s*\d[A-Za-z]\d)$"
)


def parse_full_address(
    text: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Parse a full street address into (city, state, region, country).

    Handles the comma-separated "Venue, Street, City, State/Province[, ZIP],
    Country" shape that JSON-LD and iCal feeds use, where the state may be a full
    name ("Arkansas") or a code, and the country/ZIP trail the state. `state` is
    a US two-letter code (US only); non-US sub-national regions go in `region`.
    Returns (None, None, None, None) when nothing is recognizable.
    """
    if not text or not text.strip():
        return None, None, None, None
    segs = [s.strip() for s in text.split(",") if s.strip()]
    if not segs:
        return None, None, None, None

    country: str | None = None
    if len(segs) > 1:
        c = normalize_country(segs[-1])
        if c:
            country = c
            segs.pop()

    # Drop trailing standalone postal-code segments.
    while len(segs) > 1 and _POSTAL_RE.match(segs[-1]):
        segs.pop()

    state: str | None = None
    region: str | None = None
    if len(segs) > 1:
        cand = segs[-1]
        token0 = cand.split()[0] if cand.split() else cand
        us = normalize_state(cand) or normalize_state(token0)
        if us:
            state = us
            country = "United States"
            segs.pop()
        elif token0.upper() in CANADIAN_PROVINCES:
            region = token0.upper()
            segs.pop()

    city = segs[-1] if segs else None
    # Guard against returning a street/venue line as the city when we found no
    # state/region/country signal at all.
    if state is None and region is None and country is None:
        return None, None, None, None
    return city or None, state, region, country


def resolve_location(
    text: str | None,
) -> tuple[str | None, str | None, str | None]:
    """Best-effort (city, state, country) from a free-text location string.

    `state` is a US two-letter code when the text resolves to a US location,
    otherwise None. `country` is a canonical name when determinable. Returns
    (None, None, None) when nothing recognizable is found, so callers can leave
    existing values untouched. Handles comma forms ("Venue, City, ST" /
    "City, ST" / "City, Country") and space-separated trailing forms
    ("Royal Oak MI", "Port Elizabeth South Africa").
    """
    if not text or not text.strip():
        return None, None, None
    s = text.strip()

    # Comma form: trust the last segment as state-or-country, prior as city.
    if "," in s:
        parts = [p.strip() for p in s.split(",") if p.strip()]
        if len(parts) >= 2:
            tail = parts[-1]
            state = normalize_state(tail)
            if state:
                return parts[-2] or None, state, "United States"
            country = normalize_country(tail)
            if country:
                return parts[-2] or None, None, country

    # Space-separated trailing US state ("Royal Oak MI", "Dayton Ohio").
    loc = parse_trailing_location(s)
    if loc and loc[1]:
        return loc[0], loc[1], "United States"

    # Space-separated trailing country ("Port Elizabeth South Africa").
    country_loc = parse_trailing_country(s)
    if country_loc:
        return country_loc[0], None, country_loc[1]

    # Whole field is a bare state (code or name) or country, with no city.
    # APF sometimes lists just "IL" or "Australia" in the location cell.
    state = normalize_state(s)
    if state:
        return None, state, "United States"
    country = normalize_country(s)
    if country:
        return None, None, country

    return None, None, None
