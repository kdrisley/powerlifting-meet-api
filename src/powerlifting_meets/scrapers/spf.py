from __future__ import annotations

import logging
from datetime import date

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import normalize_state
from powerlifting_meets.scrapers.base import BaseScraper
from powerlifting_meets.scrapers.tribe_events import (
    extract_equipment,
    extract_restrictions,
)

logger = logging.getLogger(__name__)

# SPF rebuilt their site at southernpowerliftingfederation.com on a Sanity CMS
# backend; the old WordPress/Tribe Events JSON API on southernpowerlifting.com
# is gone. Meets live in the public Sanity dataset and are read with GROQ via
# the CDN-backed query endpoint (no auth needed for published documents).
SANITY_PROJECT = "h342t985"
SANITY_DATASET = "production"
SANITY_API_VERSION = "2024-01-01"
SANITY_QUERY_URL = (
    f"https://{SANITY_PROJECT}.apicdn.sanity.io"
    f"/v{SANITY_API_VERSION}/data/query/{SANITY_DATASET}"
)

# Public meet detail page, used as the link when a meet has no external
# registration URL.
MEET_PAGE_BASE = "https://southernpowerliftingfederation.com/meet/"

# Upcoming meets ordered by date, projecting just the fields we surface. The
# {today} placeholder is filled in per run; everything else is literal GROQ.
# meetDirectors/contacts are reference arrays; we dereference name + emails.
_GROQ_TEMPLATE = (
    '*[_type == "meet" && startDate >= "{today}"] | order(startDate asc){{'
    "name, startDate, endDate, locationCity, locationState, venue, status, "
    'registrationUrl, "slug": slug.current, '
    "meetDirectors[]->{{name, emails}}, contacts[]->{{name, emails}}"
    "}}"
)


class SPFScraper(BaseScraper):
    federation = "SPF"

    def scrape(self) -> list[Meet]:
        query = _GROQ_TEMPLATE.format(today=date.today().isoformat())
        logger.info("Fetching SPF meets from Sanity")
        resp = self.client.get(SANITY_QUERY_URL, params={"query": query})
        resp.raise_for_status()
        result = resp.json().get("result", [])

        meets: list[Meet] = []
        for item in result:
            meet = self._parse_meet(item)
            if meet is not None:
                meets.append(meet)

        logger.info("Scraped %d SPF meets", len(meets))
        return meets

    def _parse_meet(self, item: dict) -> Meet | None:
        name = (item.get("name") or "").strip()
        date_start = self._parse_date(item.get("startDate"))
        if not name or date_start is None:
            return None

        date_end = self._parse_date(item.get("endDate"))
        if date_end == date_start:
            date_end = None

        city = self._clean_city(item.get("locationCity"))
        state = normalize_state(item.get("locationState"))
        venue = (item.get("venue") or "").strip() or None

        # url is the SPF meet page (info); registration_url is the external
        # sign-up link when the meet has one.
        slug = (item.get("slug") or "").strip()
        url = MEET_PAGE_BASE + slug if slug else None
        registration_url = (item.get("registrationUrl") or "").strip() or None

        status = "cancelled" if item.get("status") == "cancelled" else "active"

        director_name, director_email = self._extract_director(item)

        return Meet(
            name=name,
            federation=self.federation,
            date_start=date_start,
            date_end=date_end,
            state=state,
            city=city,
            url=url,
            registration_url=registration_url,
            venue=venue,
            status=status,
            equipment=extract_equipment(name),
            restrictions=extract_restrictions(name),
            director_name=director_name,
            director_email=director_email,
        )

    @staticmethod
    def _extract_director(item: dict) -> tuple[str | None, str | None]:
        """Take the first meet director (or contact) name and public email."""
        people = (item.get("meetDirectors") or []) + (item.get("contacts") or [])
        for person in people:
            if not isinstance(person, dict):
                continue
            name = (person.get("name") or "").strip() or None
            email = None
            for entry in person.get("emails") or []:
                if isinstance(entry, dict) and entry.get("email"):
                    # Prefer a public email but accept the first one otherwise.
                    email = entry["email"].strip()
                    if entry.get("visibility") == "public":
                        break
            if name or email:
                return name, email
        return None, None

    @staticmethod
    def _clean_city(raw: str | None) -> str | None:
        city = (raw or "").strip()
        if not city:
            return None
        # CMS entries are inconsistently cased; normalize SHOUTING values like
        # "LITTLE ROCK" to "Little Rock" while leaving good casing alone.
        return city.title() if city.isupper() else city

    @staticmethod
    def _parse_date(raw: str | None) -> date | None:
        if not raw:
            return None
        try:
            return date.fromisoformat(raw[:10])
        except (ValueError, TypeError):
            return None
