from __future__ import annotations

import logging
from datetime import date

from powerlifting_meets.scrapers.llm_extract_base import LLMExtractionScraper, visible_text

logger = logging.getLogger(__name__)

# 100% RAW Powerlifting Federation. WordPress; the per-year schedule page is a
# table (Dates | Event | Meet Director | Results), but the Event cell concatenates
# the meet name, venue, and "City, ST" with no delimiter — so deterministic
# splitting truncates multi-word city names ("Silver Spring" -> "Spring"). We
# hand the page text to the LLM extraction tier instead, which reads the cities
# (and meet directors) correctly.
SCHEDULE_URL = "https://rawpowerlifting.com/{year}-schedule-results/"

# The site sits behind Cloudflare, which serves a JS challenge (HTTP 403) to a
# bare User-Agent. A full browser-like header set clears it without a headless
# browser.
_BROWSER_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "sec-ch-ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}


class Raw100Scraper(LLMExtractionScraper):
    federation = "100RAW"
    source_id = "100RAW"
    kind = "text"

    def fetch_blob(self) -> tuple[bytes, str]:
        today = date.today()
        chunks: list[str] = []
        # The schedule is split into per-year pages; include this year and next.
        for year in (today.year, today.year + 1):
            url = SCHEDULE_URL.format(year=year)
            try:
                resp = self.client.get(url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
            except Exception as exc:
                logger.info("100RAW: no schedule page for %d (%s)", year, exc)
                continue
            text = visible_text(resp.text)
            if text:
                chunks.append(f"# {year} schedule\n{text}")
        return ("\n\n".join(chunks)).encode("utf-8"), "text/plain"
