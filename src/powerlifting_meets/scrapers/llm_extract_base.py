from __future__ import annotations

import logging
import os
from datetime import date, datetime

from bs4 import BeautifulSoup

from powerlifting_meets import llm_extract
from powerlifting_meets.llm_extract import ExtractedMeet
from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import normalize_country, normalize_state
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)


_CHROME_TAGS = ("script", "style", "nav", "header", "footer")


def visible_text(html: str) -> str:
    """Reduce an HTML page to its visible text, dropping chrome that adds noise
    and would churn the content hash. Shared by the brittle scrapers (and their
    eval) so they hash/extract identical text."""
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(_CHROME_TAGS):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    return main.get_text("\n", strip=True)


class ExtractionUnavailable(RuntimeError):
    """Raised when a brittle source can't be extracted (no API key and no cached
    extraction), so the runner falls back to previously published data instead of
    silently dropping the federation's meets."""


class LLMExtractionScraper(BaseScraper):
    """Base for federations whose schedule must be interpreted by the LLM tier.

    Subclasses set `source_id`, `federation`, `kind` ("text"|"image") and
    implement `fetch_blob()`. The shared extraction cache is injected by the
    runner (see runner._instantiate) so unchanged content is never re-sent to
    Gemini.
    """

    needs_extract_cache = True
    source_id: str
    kind: str = "text"

    def __init__(self, client=None, extract_cache: dict | None = None) -> None:
        super().__init__(client)
        self.extract_cache = extract_cache if extract_cache is not None else {}

    def fetch_blob(self) -> tuple[bytes, str]:
        """Return (raw source bytes, mime type). Implemented by subclasses."""
        raise NotImplementedError

    def scrape(self) -> list[Meet]:
        blob, mime = self.fetch_blob()
        extracted = llm_extract.extract_cached(
            self.source_id, blob, self.extract_cache, kind=self.kind, mime_type=mime
        )
        if not extracted and not os.environ.get("GEMINI_API_KEY"):
            raise ExtractionUnavailable(
                f"{self.source_id}: no API key and no cached extraction"
            )
        meets: list[Meet] = []
        for e in extracted:
            meet = self._to_meet(e)
            if meet is not None:
                meets.append(meet)
        logger.info("Scraped %d %s meets", len(meets), self.federation)
        return meets

    def _to_meet(self, e: ExtractedMeet) -> Meet | None:
        date_start = self._parse_date(e.date_start)
        if not e.name or date_start is None:
            return None
        date_end = self._parse_date(e.date_end)
        if date_end == date_start:
            date_end = None

        state = normalize_state(e.state)
        if state:
            region = None
            country = "United States"
        else:
            region = (e.region or "").strip() or None
            country = normalize_country(e.country) or (e.country or "").strip() or None

        city = (e.city or "").strip() or None

        return Meet(
            name=e.name.strip(),
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            state=state,
            region=region,
            city=city,
            country=country,
            status="active",
            equipment=extract_equipment(e.name),
            restrictions=extract_restrictions(e.name),
            director_name=(e.director_name or "").strip() or None,
            director_email=(e.director_email or "").strip() or None,
        )

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw).date()
        except (ValueError, TypeError):
            try:
                return date.fromisoformat(raw[:10])
            except (ValueError, TypeError):
                return None
