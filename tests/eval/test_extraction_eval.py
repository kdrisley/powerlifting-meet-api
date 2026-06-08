"""Real-Gemini validation of the LLM extraction prompts.

These tests make actual API calls and are EXCLUDED from the default/CI run (see
`addopts = -m 'not eval'` in pyproject). Run them explicitly before shipping a
prompt or SCHEMA_VERSION change:

    uv run pytest -m eval

They run the real extraction against pinned source snapshots in
tests/fixtures/eval/ and assert the hand-verified meets come back correctly
(strict on dates/state, fuzzy on names), plus structural invariants. The
fixtures are frozen, so when a source's live page changes, recapture the fixture
and re-verify the anchors below.
"""
import os
from datetime import date
from pathlib import Path

import pytest

# Load GEMINI_API_KEY from the project .env for local eval runs.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass

from powerlifting_meets import llm_extract  # noqa: E402

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(
        not os.environ.get("GEMINI_API_KEY"), reason="needs a real GEMINI_API_KEY"
    ),
]

EVAL_DIR = Path(__file__).parent.parent / "fixtures" / "eval"

# Hand-verified anchors: meets that must come back, matched by a name substring
# plus an exact start date, with the expected US state.
# Fixtures are the page text (visible_text output) — the HTML->text step is
# unit-tested separately; here we validate the extraction prompt itself.
# Anchors are (name_substring, start_date, state[, expected_city]); city is
# asserted when given (used to prove multi-word cities aren't truncated).
CASES = {
    "nasa_schedule.txt": {
        "min_count": 18,
        "anchors": [
            ("Illinois Tri-State Summer", date(2026, 7, 25), "IL"),
            ("Ohio Regional", date(2026, 10, 3), "OH"),
            ("Merry Liftmas Texas Nationals", date(2026, 12, 5), "TX"),
        ],
    },
    "ipa_events.txt": {
        "min_count": 5,
        "anchors": [
            ("Strength of Heroes", date(2026, 9, 12), "NY"),
            ("Power Plant Showdown", date(2026, 10, 10), "WV"),
        ],
    },
    "wnpf_2026.txt": {
        "min_count": 8,
        "anchors": [
            ("Larry B Pan", date(2026, 6, 20), "FL"),
            ("Sarge McCray", date(2026, 12, 6), "NJ"),
        ],
    },
    "raw100_2026.txt": {
        "min_count": 12,
        "anchors": [
            # Multi-word cities must survive intact (the reason for the switch).
            ("Shenandoah Open", date(2026, 8, 22), "VA", "Woodstock"),
            ("California Open II", date(2026, 7, 26), "CA", "Santa Clara"),
            ("Mr. America Pro", date(2026, 10, 11), "NJ", "Atlantic City"),
        ],
    },
}


def _extract(fixture: str):
    text = (EVAL_DIR / fixture).read_text(encoding="utf-8")
    result = llm_extract.extract_meets_from_text(text)
    assert result is not None, "extraction returned None (API/parse failure)"
    return result.meets


def _parse(d: str) -> date | None:
    try:
        return date.fromisoformat(d[:10])
    except (ValueError, TypeError):
        return None


@pytest.mark.parametrize("fixture", list(CASES))
def test_extraction_quality(fixture):
    spec = CASES[fixture]
    meets = _extract(fixture)

    # Structural invariants.
    assert len(meets) >= spec["min_count"], f"{fixture}: only {len(meets)} meets"
    for m in meets:
        assert m.name and m.name.strip(), "blank meet name"
        d = _parse(m.date_start)
        assert d is not None, f"unparseable date_start {m.date_start!r}"
        assert date(2025, 1, 1) <= d <= date(2030, 1, 1), f"date out of range: {d}"
        assert not (m.state and m.region), "meet has both US state and non-US region"

    # Hand-verified anchors come back with the right date + state (+ city).
    for anchor in spec["anchors"]:
        name_sub, exp_date, exp_state = anchor[:3]
        exp_city = anchor[3] if len(anchor) > 3 else None
        match = [
            m
            for m in meets
            if name_sub.lower() in m.name.lower() and _parse(m.date_start) == exp_date
        ]
        assert match, f"{fixture}: missing anchor {name_sub!r} on {exp_date}"
        assert (
            match[0].state == exp_state
        ), f"{fixture}: {name_sub!r} state {match[0].state!r} != {exp_state!r}"
        if exp_city is not None:
            assert (
                match[0].city == exp_city
            ), f"{fixture}: {name_sub!r} city {match[0].city!r} != {exp_city!r}"
