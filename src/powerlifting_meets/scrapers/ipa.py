from __future__ import annotations

import logging

from powerlifting_meets.scrapers.llm_extract_base import LLMExtractionScraper, visible_text

logger = logging.getLogger(__name__)

# International Powerlifting Association (US-based). The upcoming-events page lays
# each meet out as a heading followed by prose (date, venue, city/state) with no
# consistent structure, so we extract the page text and let the LLM tier read it.
EVENTS_URL = "https://ipapower.com/upcoming-events/"


class IPAScraper(LLMExtractionScraper):
    federation = "IPA"
    source_id = "IPA"
    kind = "text"

    def fetch_blob(self) -> tuple[bytes, str]:
        resp = self.client.get(EVENTS_URL)
        resp.raise_for_status()
        return visible_text(resp.text).encode("utf-8"), "text/plain"
