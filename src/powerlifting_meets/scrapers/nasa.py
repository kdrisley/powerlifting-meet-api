from __future__ import annotations

import logging

from powerlifting_meets.fetch import jina_get
from powerlifting_meets.scrapers.llm_extract_base import LLMExtractionScraper

logger = logging.getLogger(__name__)

# NASA Powerlifting moved its schedule to /upcoming-meets/ (2026), which builds
# the meet list with JavaScript, so the page is fetched through Jina Reader
# (rendered to markdown) and handed to the LLM extraction tier. The old
# /schedule/ page now 404s.
SCHEDULE_PAGE = "https://nasa-sports.com/upcoming-meets/"


class NASAScraper(LLMExtractionScraper):
    federation = "NASA"
    source_id = "NASA"
    kind = "text"

    def fetch_blob(self) -> tuple[bytes, str]:
        rendered = jina_get(SCHEDULE_PAGE, "markdown")
        if rendered is None:
            raise RuntimeError(f"NASA schedule could not be rendered: {SCHEDULE_PAGE}")
        return rendered.encode("utf-8"), "text/plain"
