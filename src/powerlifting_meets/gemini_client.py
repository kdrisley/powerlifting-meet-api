"""Shared Gemini client construction for the LLM tiers (geo + extraction).

Returns None when no API key is set or the SDK is unavailable, so every LLM tier
degrades to a no-op without a key — local runs and CI need no key or network.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def get_client():
    """Return a configured google-genai client, or None when unavailable."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    try:
        from google import genai

        return genai.Client(api_key=api_key)
    except Exception as exc:  # pragma: no cover - import/setup failure path
        logger.warning("Gemini client unavailable: %s", exc)
        return None
