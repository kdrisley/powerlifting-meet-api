"""LLM meet-EXTRACTION tier for brittle sources.

Some federations publish their schedule in a form deterministic parsing can't
reliably handle: free-text on a Wix page (WNPF), heading-blocks with prose dates
(IPA), or only as an image (NASA). For those, we hand the raw source blob to
Gemini and ask it to return structured meets.

This is distinct from llm_geo (which locates one already-parsed meet). Here the
unit of work is a whole source blob -> many meets.

Cost discipline: extraction results are cached by a hash of the source content,
and the cache is published to GitHub Pages and reloaded each run (see runner).
So a given blob is sent to Gemini at most once, ever — re-extraction happens only
when the source content actually changes (or SCHEMA_VERSION is bumped).
"""
from __future__ import annotations

import hashlib
import logging

from pydantic import BaseModel, Field

from powerlifting_meets.gemini_client import get_client

logger = logging.getLogger(__name__)

# Same cheap, fast, vision-capable model the geo tier uses.
GEMINI_MODEL = "gemini-3.1-flash-lite"

# Bump to force re-extraction of every source (e.g. after changing a prompt).
# v2: added director_name/director_email to ExtractedMeet.
SCHEMA_VERSION = 2


class ExtractedMeet(BaseModel):
    """One meet the model pulled out of a source blob. Dates are ISO strings —
    Gemini emits those more reliably than typed dates; the scraper parses them."""

    name: str = Field(description="Full meet name, transcribed as written")
    date_start: str = Field(description="Start date as YYYY-MM-DD")
    date_end: str | None = Field(
        default=None, description="End date YYYY-MM-DD for multi-day events, else null"
    )
    city: str | None = Field(default=None, description="City, or null if not stated")
    state: str | None = Field(
        default=None, description="Two-letter US state code if in the USA, else null"
    )
    region: str | None = Field(
        default=None,
        description="Non-US sub-national region (province/state/territory), else null",
    )
    country: str | None = Field(default=None, description="Country name, or null")
    director_name: str | None = Field(
        default=None, description="Meet director / organizer name if stated, else null"
    )
    director_email: str | None = Field(
        default=None, description="Meet director contact email if stated, else null"
    )


class ExtractionResult(BaseModel):
    meets: list[ExtractedMeet] = Field(default_factory=list)


_RULES = """For each meet provide: the full name (transcribed exactly); the start
date as YYYY-MM-DD; the end date as YYYY-MM-DD only for multi-day events,
otherwise null; and the location split into city, state (two-letter US code, only
if in the USA), region (a non-US state/province/territory, only if outside the
USA), and country. Also include the meet director's name and contact email when
the source states them (director_name, director_email), else null. Never set both
state and region. Today is {today}. If a year is
not written next to a date, infer it from the surrounding context and the ordering
of the dates (a schedule usually runs forward in time, rolling into the next year
when the month numbers wrap); if it's still ambiguous, choose the next future
occurrence on or after today. Do NOT invent meets, dates, or locations — use null
for anything not stated. Skip anything that is not an actual competition
(memberships, registration deadlines, livestream notices, ads, past results)."""

_TEXT_PROMPT = (
    "You are extracting the list of powerlifting meets from the text of a "
    "federation's events page.\n\n" + _RULES + "\n\n--- PAGE TEXT ---\n{text}"
)

_IMAGE_PROMPT = (
    "The attached image is a powerlifting federation's meet schedule. Read every "
    "meet shown in the image.\n\n" + _RULES + "\n\nDates in the image may look "
    "like 'March 14, 2026' or '3/14/26'; normalize them to YYYY-MM-DD."
)


def content_hash(blob: bytes) -> str:
    """Stable short hash of the raw source content."""
    return hashlib.sha256(blob).hexdigest()[:16]


def _today_iso() -> str:
    from datetime import date

    return date.today().isoformat()


def _parse_response(resp) -> ExtractionResult | None:
    guess = getattr(resp, "parsed", None)
    if isinstance(guess, ExtractionResult):
        return guess
    try:
        return ExtractionResult.model_validate_json(resp.text)
    except Exception as exc:
        logger.warning("Could not parse Gemini extraction response: %s", exc)
        return None


def extract_meets_from_text(text: str) -> ExtractionResult | None:
    """Extract meets from page text. None without an API key or on failure."""
    client = get_client()
    if client is None:
        return None
    from google.genai import types

    prompt = _TEXT_PROMPT.format(today=_today_iso(), text=text)
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExtractionResult,
            ),
        )
    except Exception as exc:
        logger.warning("Gemini text extraction failed: %s", exc)
        return None
    return _parse_response(resp)


def extract_meets_from_image(
    image_bytes: bytes, mime_type: str = "image/png"
) -> ExtractionResult | None:
    """Extract meets from a schedule image. None without a key or on failure."""
    client = get_client()
    if client is None:
        return None
    from google.genai import types

    prompt = _IMAGE_PROMPT.format(today=_today_iso())
    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=ExtractionResult,
            ),
        )
    except Exception as exc:
        logger.warning("Gemini image extraction failed: %s", exc)
        return None
    return _parse_response(resp)


def extract_cached(
    source_id: str,
    blob: bytes,
    cache: dict,
    *,
    kind: str = "text",
    mime_type: str = "image/png",
) -> list[ExtractedMeet]:
    """Cache-aware extraction.

    Returns the cached meets with ZERO API calls when the source content is
    unchanged (same content_hash + schema_version). On a miss, calls Gemini once,
    stores the result in `cache` (mutated in place), and returns it. Returns []
    when there's no API key or the call fails — the caller decides whether to
    fall back to previously published data.
    """
    h = content_hash(blob)
    entry = cache.get(source_id)
    if (
        entry
        and entry.get("content_hash") == h
        and entry.get("schema_version") == SCHEMA_VERSION
    ):
        return [ExtractedMeet(**m) for m in entry.get("meets", [])]

    if kind == "image":
        result = extract_meets_from_image(blob, mime_type)
    else:
        result = extract_meets_from_text(blob.decode("utf-8", "replace"))

    if result is None:
        # No key or transient failure — don't cache, so it retries next run.
        return []

    cache[source_id] = {
        "schema_version": SCHEMA_VERSION,
        "content_hash": h,
        "meets": [m.model_dump() for m in result.meets],
    }
    logger.info("Extracted %d meets from %s via Gemini", len(result.meets), source_id)
    return result.meets
