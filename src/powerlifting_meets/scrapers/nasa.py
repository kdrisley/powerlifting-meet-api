from __future__ import annotations

import logging

from powerlifting_meets.scrapers.llm_extract_base import LLMExtractionScraper, visible_text

logger = logging.getLogger(__name__)

# NASA Powerlifting lists its schedule as free text on the schedule page
# ("June 13th – Illinois Tri-State Summer (Flora, IL)"), with years implied by
# ordering rather than written. The format is irregular (blank rows, multi-meet
# rows), so we hand the page text to the LLM extraction tier.
SCHEDULE_PAGE = "https://nasa-sports.com/schedule/"


class NASAScraper(LLMExtractionScraper):
    federation = "NASA"
    source_id = "NASA"
    kind = "text"

    def fetch_blob(self) -> tuple[bytes, str]:
        resp = self.client.get(SCHEDULE_PAGE)
        resp.raise_for_status()
        return visible_text(resp.text).encode("utf-8"), "text/plain"
