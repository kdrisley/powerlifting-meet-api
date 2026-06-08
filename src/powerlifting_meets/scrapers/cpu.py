from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import parse_full_address
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import extract_equipment, extract_restrictions

logger = logging.getLogger(__name__)

# Canadian Powerlifting Union (powerlifting.ca) runs on Wix — the listing page is
# a JS SPA, but every event has a stable detail page with a JSON-LD <script>
# describing it, and all detail pages are enumerated in a sitemap. So: read the
# sitemap, then read each future event page's JSON-LD.
SITEMAP_URL = "https://www.powerlifting.ca/event-pages-sitemap.xml"

_LOC_RE = re.compile(r"<loc>\s*([^<]+?)\s*</loc>", re.I)
_LDJSON_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.I | re.S
)
_YEAR_RE = re.compile(r"\b(20\d{2})\b")


class CPUScraper(BaseScraper):
    federation = "CPU"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching CPU sitemap")
        resp = self.client.get(SITEMAP_URL)
        resp.raise_for_status()

        today = date.today()
        urls = self._event_urls(resp.text, today.year)
        logger.info("CPU: %d candidate event pages", len(urls))

        meets: list[Meet] = []
        for url in urls:
            try:
                page = self.client.get(url)
                page.raise_for_status()
            except Exception as exc:
                logger.warning("CPU: failed to fetch %s: %s", url, exc)
                continue
            meet = self._parse_event_page(page.text, url)
            if meet is not None and meet.date_start >= today:
                meets.append(meet)

        logger.info("Scraped %d CPU meets", len(meets))
        return meets

    @staticmethod
    def _event_urls(sitemap_xml: str, min_year: int) -> list[str]:
        """Event-detail URLs, keeping only those whose slug names a year >=
        the current year (or no year at all), to avoid fetching old events."""
        urls = []
        for loc in _LOC_RE.findall(sitemap_xml):
            if "event-details/" not in loc:
                continue
            years = [int(y) for y in _YEAR_RE.findall(loc)]
            if years and max(years) < min_year:
                continue
            urls.append(loc)
        return urls

    def _parse_event_page(self, html_text: str, url: str) -> Meet | None:
        event = self._find_event_ldjson(html_text)
        if event is None:
            return None

        name = (event.get("name") or "").strip()
        date_start = self._parse_iso_date(event.get("startDate"))
        if not name or date_start is None:
            return None
        date_end = self._parse_iso_date(event.get("endDate"))
        if date_end == date_start:
            date_end = None

        location = event.get("location") or {}
        if isinstance(location, list):
            location = location[0] if location else {}
        venue = (location.get("name") or "").strip() or None
        city, state, region, country = parse_full_address(location.get("address"))

        return Meet(
            name=name,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            state=state,
            region=region,
            city=city,
            country=country,
            venue=venue,
            url=url,
            status="active",
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
        )

    @staticmethod
    def _find_event_ldjson(html_text: str) -> dict | None:
        for block in _LDJSON_RE.findall(html_text):
            try:
                data = json.loads(block)
            except (ValueError, TypeError):
                continue
            candidates = data if isinstance(data, list) else [data]
            # Some sites nest items under @graph.
            graph = isinstance(data, dict) and data.get("@graph")
            if isinstance(graph, list):
                candidates = graph
            for item in candidates:
                if isinstance(item, dict) and item.get("@type") == "Event":
                    return item
        return None

    @staticmethod
    def _parse_iso_date(raw: str | None) -> date | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw).date()
        except (ValueError, TypeError):
            try:
                return date.fromisoformat(raw[:10])
            except (ValueError, TypeError):
                return None
