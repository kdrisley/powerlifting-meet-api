"""Pure-transform classification of meets from name + federation.

Mirrors `normalize.py`: no I/O, no network — just deterministic functions over
fields the scrapers already produce. Used by the post-dedup enrichment pass in
`runner.py` to fill `event_type`, `event_level`, and `testing_status`.

The guiding rule throughout: return ``None`` rather than guess. A null field is
honest ("we don't know"); a wrong default is a filter that lies to the lifter.
"""

from __future__ import annotations

import re

# Canonical event-type (competition format) values.
EVENT_TYPES = frozenset(
    {"full_power", "push_pull", "bench_only", "deadlift_only", "squat_only"}
)

# Canonical event-level (competitive tier) values, ascending.
EVENT_LEVELS = frozenset({"LOCAL", "STATE", "REGIONAL", "NATIONAL", "INTERNATIONAL"})

# Canonical testing-status values.
TESTING_STATUSES = frozenset({"tested", "untested"})


# --- event type -------------------------------------------------------------

# Ordered (pattern, type) pairs. Order is load-bearing: a name like
# "Bench & Deadlift" must hit push_pull before the bare "bench"/"deadlift" rules,
# and the generic full_power fallback must come last so it never shadows a more
# specific single-lift meet ("Bench Press Championship" is bench_only, not full
# power). Patterns are matched against the lowercased name as substrings/regex.
_EVENT_TYPE_RULES: list[tuple[re.Pattern[str], str]] = [
    # push/pull and bench+deadlift combos — must precede the single-lift rules.
    (re.compile(r"push[\s/&-]*pull|push\s*&\s*pull"), "push_pull"),
    (re.compile(r"bench\s*(?:&|and|/|\+)\s*dead"), "push_pull"),
    # single-lift formats
    (re.compile(r"bench(?:\s*press)?\s*(?:only|champ|press)|\bbench\s*only\b"), "bench_only"),
    (re.compile(r"\bbench\s*press\b"), "bench_only"),
    (re.compile(r"deadlift\s*only|\bdeadlift\s*champ|\bdead\s*only\b"), "deadlift_only"),
    (re.compile(r"\bdeadlift\b"), "deadlift_only"),
    (re.compile(r"squat\s*only"), "squat_only"),
    # generic full-power fallback — keep last.
    (re.compile(r"full\s*power|\bpowerlifting\b|\bpower\s*lifting\b"), "full_power"),
]


def classify_event_type(name: str | None) -> str | None:
    """Infer the competition format from the meet name, or None if unstated.

    Returns one of EVENT_TYPES. The bench/deadlift/squat single-lift rules are
    checked before the generic full_power fallback so a "Bench Press
    Championship" doesn't classify as full power.
    """
    if not name:
        return None
    low = name.lower()
    for pattern, event_type in _EVENT_TYPE_RULES:
        if pattern.search(low):
            return event_type
    return None


# --- event level ------------------------------------------------------------

# Ordered (pattern, level) pairs, highest tier first so "World" wins over a
# stray "national" and "National" wins over "regional", etc.
_EVENT_LEVEL_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bworld|\binternational\b|\bglobal\b|\bcontinental\b"), "INTERNATIONAL"),
    (re.compile(r"\bnational"), "NATIONAL"),
    (re.compile(r"\bregional"), "REGIONAL"),
    (re.compile(r"\bstate\b|\bstates\b"), "STATE"),
]

# Maps the raw level strings scrapers capture (USAPL "Type of Event", etc.) onto
# the canonical set. Unknown/non-level values (e.g. "COACHING") map to None so
# clinic listings don't pollute the level filter.
_RAW_LEVEL_MAP: dict[str, str] = {
    "local": "LOCAL",
    "state": "STATE",
    "state championship": "STATE",
    "regional": "REGIONAL",
    "regionals": "REGIONAL",
    "national": "NATIONAL",
    "nationals": "NATIONAL",
    "international": "INTERNATIONAL",
    "world": "INTERNATIONAL",
    "worlds": "INTERNATIONAL",
}


def normalize_event_level(raw: str | None) -> str | None:
    """Map a scraper-captured level string onto the canonical EVENT_LEVELS set.

    Returns None for empty input or values that aren't a recognized tier (e.g.
    a USAPL "Coaching" clinic), so non-meet rows don't carry a bogus level.
    """
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _RAW_LEVEL_MAP:
        return _RAW_LEVEL_MAP[key]
    return raw.strip().upper() if raw.strip().upper() in EVENT_LEVELS else None


def classify_event_level(name: str | None) -> str | None:
    """Infer the competitive tier from the meet name, or None if unstated.

    Returns one of EVENT_LEVELS. Deliberately does NOT default to LOCAL: most
    meet names carry no tier keyword, and stamping every one LOCAL would make
    the level filter meaningless. A scraped level (see normalize_event_level)
    should take precedence over this when available.
    """
    if not name:
        return None
    low = name.lower()
    for pattern, level in _EVENT_LEVEL_RULES:
        if pattern.search(low):
            return level
    return None


# --- testing status ---------------------------------------------------------

# Per-federation default testing posture. Only federations with a clear,
# well-known stance are listed; everything else (federations that run both
# tested and untested meets, or whose posture we're unsure of) is omitted and
# resolves to None unless the meet name says otherwise. Keys are the
# `federation` identifiers set on each scraper.
_FEDERATION_TESTING_DEFAULT: dict[str, str] = {
    # IPF and its affiliates are drug-tested by default.
    "USAPL": "tested",
    "IPF": "tested",
    "EPF": "tested",
    "PA": "tested",       # Powerlifting America (IPF US affiliate)
    "PA-AUS": "tested",   # Powerlifting Australia (IPF affiliate)
    "NZPU": "tested",     # New Zealand Powerlifting Union (IPF affiliate)
    "CPU": "tested",      # Canadian Powerlifting Union (IPF affiliate)
    "IrishPF": "tested",  # Irish Powerlifting Federation (IPF affiliate)
    # Explicitly drug-free / natural federations.
    "ADFPF": "tested",    # American Drug Free Powerlifting Federation
    "WNPF": "tested",     # World Natural Powerlifting Federation
    "NASA": "tested",     # Natural Athlete Strength Association
    "100RAW": "tested",   # 100% RAW (drug-free)
    # Predominantly untested federations.
    "APF": "untested",    # American Powerlifting Federation / WPC
    "RPS": "untested",
    "SPF": "untested",
    # Deliberately omitted (run both / uncertain → name signal only):
    # USPA, IPA, APL, WABDL, USPC, PLU.
}

_TESTED_NAME_RE = re.compile(r"\bdrug[\s-]*tested\b|\btested\b|\bnatural\b|\bdrug[\s-]*free\b")
_UNTESTED_NAME_RE = re.compile(r"\buntested\b|\bnon[\s-]*tested\b")


def classify_testing_status(federation: str | None, name: str | None) -> str | None:
    """Infer drug-testing status from the federation default and meet name.

    A name keyword ("Tested" / "Untested" / "Drug Free") always overrides the
    federation default. For federations that run both postures (no default
    listed), the name is the only signal; absent it, returns None rather than
    guessing.
    """
    low = (name or "").lower()
    # An explicit name keyword wins over the federation default.
    if _UNTESTED_NAME_RE.search(low):
        return "untested"
    if _TESTED_NAME_RE.search(low):
        return "tested"
    if federation:
        return _FEDERATION_TESTING_DEFAULT.get(federation)
    return None
