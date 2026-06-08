from __future__ import annotations

import logging
from datetime import date

from powerlifting_meets.scrapers.llm_extract_base import LLMExtractionScraper, visible_text

logger = logging.getLogger(__name__)

# World Natural Powerlifting Federation. The site is a Wix build whose schedule
# is free-text (date + name + rough location) with PayPal buttons per event — no
# structured markup. We extract the visible text and let the LLM tier interpret
# it. The blob is the *extracted text* (not raw Wix HTML), which is stable across
# requests so the content hash doesn't churn and burn a daily API call.
SCHEDULE_URL = "https://www.wnpfpl.com/{year}-schedule-online-payment"


class WNPFScraper(LLMExtractionScraper):
    federation = "WNPF"
    source_id = "WNPF"
    kind = "text"

    def fetch_blob(self) -> tuple[bytes, str]:
        today = date.today()
        chunks: list[str] = []
        for year in (today.year, today.year + 1):
            url = SCHEDULE_URL.format(year=year)
            try:
                resp = self.client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.info("WNPF: no schedule page for %d (%s)", year, exc)
                continue
            text = visible_text(resp.text)
            if text:
                chunks.append(f"# {year} schedule\n{text}")
        return ("\n\n".join(chunks)).encode("utf-8"), "text/plain"
