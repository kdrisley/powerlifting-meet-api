from __future__ import annotations

import html
import logging
from datetime import date, datetime

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import normalize_state, parse_address_location
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)


def extract_equipment(title: str) -> str | None:
    """Infer the equipment division from a meet title, if stated."""
    lower = title.lower()
    if "raw w/ wraps" in lower or "raw with wraps" in lower or "raw/wraps" in lower:
        return "Raw w/ Wraps"
    if "equipped" in lower:
        return "Equipped"
    if "raw" in lower:
        return "Raw"
    return None


def extract_restrictions(title: str) -> str | None:
    """Infer entry restrictions (women-only, masters, etc.) from a meet title."""
    lower = title.lower()
    restrictions: list[str] = []
    if "women" in lower:
        restrictions.append("Women Only")
    if "collegiate" in lower:
        restrictions.append("Collegiate")
    if "high school" in lower:
        restrictions.append("High School")
    if "masters" in lower:
        restrictions.append("Masters")
    if "teen" in lower:
        restrictions.append("Teen")
    return ", ".join(restrictions) if restrictions else None


class TribeEventsScraper(BaseScraper):
    """Scraper for sites using The Events Calendar (Tribe Events) WordPress plugin.

    Subclass and set `federation` and `base_url` to use.
    """

    base_url: str
    federation: str

    def scrape(self) -> list[Meet]:
        meets: list[Meet] = []
        today = date.today().isoformat()
        url: str | None = (
            f"{self.base_url}/wp-json/tribe/events/v1/events"
            f"?start_date={today}&per_page=50&status=publish"
        )

        while url:
            logger.info("Fetching %s", url)
            resp = self.client.get(url)
            resp.raise_for_status()
            data = resp.json()

            for event in data.get("events", []):
                meet = self._parse_event(event)
                if meet is not None:
                    meets.append(meet)

            url = data.get("next_rest_url")

        logger.info("Scraped %d %s meets", len(meets), self.federation)
        return meets

    def _parse_event(self, event: dict) -> Meet | None:
        title = event.get("title", "").strip()
        if not title:
            return None

        venue_data = event.get("venue", {}) or {}

        date_start = self._parse_date(event.get("start_date"))
        if date_start is None:
            return None

        date_end = self._parse_date(event.get("end_date"))
        if date_end == date_start:
            date_end = None

        state = normalize_state(
            venue_data.get("stateprovince") or venue_data.get("state") or venue_data.get("province")
        )
        city = (venue_data.get("city") or "").strip() or None
        venue_name = (venue_data.get("venue") or "").strip() or None

        # Some venues leave the structured city/state empty and stuff the whole
        # address into the venue name or address field (e.g. "Arkansas State
        # Fair, 2600 Howard St, Little Rock, AR 72206, USA"). Fall back to
        # parsing the city/state out of that free text.
        if city is None or state is None:
            loc = parse_address_location(venue_name or "") or parse_address_location(
                venue_data.get("address") or ""
            )
            if loc:
                city = city or loc[0]
                state = state or loc[1]

        event_url = event.get("url") or None

        equipment = self._extract_equipment(title)
        restrictions = self._extract_restrictions(title)
        status = self._extract_status(event)
        director_name, director_email = self._extract_organizer(event)

        return Meet(
            name=title,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            state=state,
            city=city,
            url=event_url,
            venue=venue_name,
            status=status,
            equipment=equipment,
            restrictions=restrictions,
            director_name=director_name,
            director_email=director_email,
        )

    @staticmethod
    def _extract_organizer(event: dict) -> tuple[str | None, str | None]:
        """Pull the meet director's name and email from the Tribe organizer."""
        organizer = event.get("organizer")
        if isinstance(organizer, list):
            organizer = organizer[0] if organizer else None
        if not isinstance(organizer, dict):
            return None, None
        # The name field is HTML-escaped in the API (e.g. "Katie &#038; Will").
        name = html.unescape((organizer.get("organizer") or "").strip()) or None
        email = (organizer.get("email") or "").strip() or None
        return name, email

    def _parse_date(self, raw: str | None) -> date | None:
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw).date()
        except (ValueError, TypeError):
            return None

    def _extract_equipment(self, title: str) -> str | None:
        return extract_equipment(title)

    def _extract_restrictions(self, title: str) -> str | None:
        return extract_restrictions(title)

    def _extract_status(self, event: dict) -> str | None:
        return "active"
