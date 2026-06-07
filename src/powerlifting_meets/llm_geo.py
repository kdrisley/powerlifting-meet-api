"""LLM fallback for inferring a meet's location from unstructured clues.

Deterministic parsing (see normalize.resolve_location) resolves almost every
meet. The handful it can't — a location buried mid-title, a bare foreign city,
a US territory — are sent here, where Gemini infers the city/state/country from
the meet name, venue, and URL. The whole tier is a no-op without a GEMINI_API_KEY,
so local runs and tests need no key or network.
"""
from __future__ import annotations

import hashlib
import logging
import os

from pydantic import BaseModel, Field

from powerlifting_meets.models import Meet

logger = logging.getLogger(__name__)

# Cheap, fast model — this is simple "given these clues, what city/state"
# extraction, not a reasoning task. gemini-3.1-flash-lite is the Gemini 3
# family's flash-lite GA model (there is no plain "gemini-3-flash-lite").
GEMINI_MODEL = "gemini-3.1-flash-lite"

# Bump to force a global re-assessment (e.g. after changing the prompt/model);
# cached entries with an older version are ignored.
SCHEMA_VERSION = 1

# Only adopt a guess at or above this confidence. Below it the meet stays
# flagged as unresolved rather than risk publishing a bad value.
CONFIDENCE_THRESHOLD = 0.6


class GeoGuess(BaseModel):
    """Structured result the model is constrained to return."""

    city: str | None = Field(default=None, description="City name, or null if unknown")
    state: str | None = Field(
        default=None,
        description="Two-letter US state code (e.g. TX). Null if the meet is not in the US.",
    )
    country: str | None = Field(default=None, description="Country name, or null if unknown")
    confidence: float = Field(description="0.0-1.0 confidence in the inferred location")
    reasoning: str = Field(description="One sentence explaining the inference")


_PROMPT = """You are locating a powerlifting meet from limited clues.

Infer the meet's city, US state, and country. Rules:
- `state` is the two-letter US postal code (e.g. TX, CA) ONLY when the meet is in the United States; otherwise null.
- For US territories (Guam, Puerto Rico, etc.) set `country` to "United States" and leave `state` null.
- When the meet is clearly outside the US, set `country` (e.g. "Ireland") and leave `state` null.
- Use only what the clues support. If you cannot tell, return low confidence with nulls — do not guess wildly.

Clues:
- Meet name: {name}
- Federation: {federation}
- Venue: {venue}
- Partial location text: {city}
- URL: {url}
"""


def _get_client():
    """Return a configured genai client, or None when no API key is set.

    Imports the SDK lazily so the module loads even where google-genai isn't
    installed (e.g. minimal test envs)."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai

        return genai.Client(api_key=api_key)
    except Exception as exc:
        logger.warning("Gemini client unavailable: %s", exc)
        return None


def infer_location(meet: Meet) -> GeoGuess | None:
    """Ask Gemini to infer the location of one meet.

    Returns None when there's no API key or the call/parse fails, so the caller
    skips caching and can retry on a later run."""
    client = _get_client()
    if client is None:
        return None

    from google.genai import types

    prompt = _PROMPT.format(
        name=meet.name or "",
        federation=meet.federation or "",
        venue=meet.venue or "",
        city=meet.city or "",
        url=str(meet.url or meet.registration_url or ""),
    )
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=GeoGuess,
            ),
        )
    except Exception as exc:
        logger.warning("Gemini geo inference failed for %r: %s", meet.name, exc)
        return None

    # Prefer the SDK's parsed object; fall back to parsing the raw JSON so this
    # works across SDK versions that don't populate `.parsed`.
    guess = getattr(resp, "parsed", None)
    if isinstance(guess, GeoGuess):
        return guess
    try:
        return GeoGuess.model_validate_json(resp.text)
    except Exception as exc:
        logger.warning("Could not parse Gemini response for %r: %s", meet.name, exc)
        return None


def signals_hash(meet: Meet) -> str:
    """Stable hash of the inputs fed to the model.

    If a meet's source data later changes (e.g. a scraper starts providing a
    venue), the hash changes and the meet is re-assessed once."""
    raw = "|".join(
        [
            meet.name or "",
            meet.venue or "",
            meet.city or "",
            str(meet.url or meet.registration_url or ""),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def cache_key(meet: Meet) -> str:
    """Identity of a meet within the geo cache."""
    return f"{meet.federation}|{meet.name}|{meet.date_start.isoformat()}"
