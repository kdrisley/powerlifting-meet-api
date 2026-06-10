from __future__ import annotations

import abc
import logging

import httpx

from powerlifting_meets.models import Meet

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


class BaseScraper(abc.ABC):
    federation: str
    # Aggregator scrapers emit per-meet federation codes that differ from the
    # class `federation` (which stays the meta.json key). They list the emitted
    # codes here so the runner's stale-data fallback can find their meets in
    # the previous feed (see runner.get_previous_meets_for_federation).
    fallback_federations: frozenset[str] | None = None
    # Brittle scrapers that need the shared LLM-extraction cache set this True so
    # the runner constructs them with extract_cache= (see runner._instantiate).
    needs_extract_cache: bool = False

    def __init__(self, client: httpx.Client | None = None) -> None:
        if client is not None:
            self.client = client
            self._owns_client = False
        else:
            self.client = httpx.Client(
                headers={"User-Agent": USER_AGENT},
                timeout=30.0,
                follow_redirects=True,
            )
            self._owns_client = True

    @abc.abstractmethod
    def scrape(self) -> list[Meet]:
        ...

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> BaseScraper:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
