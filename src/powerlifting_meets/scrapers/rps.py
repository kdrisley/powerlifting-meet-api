from __future__ import annotations

import logging
import re
from datetime import date
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import LOCATION_CODES, normalize_state
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

MEETS_URL = "https://meets.revolutionpowerlifting.com/"


class RPSScraper(BaseScraper):
    federation = "RPS"

    def scrape(self) -> list[Meet]:
        logger.info("Fetching RPS meets")
        resp = self.client.get(MEETS_URL)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        meets: list[Meet] = []
        today = date.today()

        for li in soup.find_all("li", class_="postEvent"):
            meet = self._parse_meet_li(li, today)
            if meet is not None:
                meets.append(meet)

        logger.info("Scraped %d RPS meets", len(meets))
        return meets

    def _parse_meet_li(self, li: Tag, today: date) -> Meet | None:
        a = li.find("a", href=True)
        if a is None:
            return None

        href = a["href"]

        # Extract date from URL: /YYYY/MM/DD/slug/
        parsed = urlparse(href)
        path = parsed.path.strip("/")
        parts = path.split("/")
        if len(parts) < 4:
            return None

        try:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            meet_date = date(year, month, day)
        except (ValueError, IndexError):
            return None

        if meet_date < today:
            return None

        # Extract meet name and location from p.theTitle
        title_p = li.find("p", class_="theTitle")
        if title_p is None:
            return None

        # Get text content, skipping the time span
        # Structure: <span>Sat @ 9:30 am</span><br/><span style="color:red;">Sold Out</span> Meet Name – City, ST
        status = "active"
        name_parts: list[str] = []

        for child in title_p.children:
            if isinstance(child, Tag):
                if child.name == "span" and "color" in (child.get("style") or ""):
                    # Status badge
                    badge = child.get_text(strip=True).lower()
                    if "sold out" in badge:
                        status = "sold_out"
                    elif "cancelled" in badge or "canceled" in badge:
                        status = "cancelled"
                elif child.name == "br":
                    continue
                elif child.name == "span":
                    # Time span (e.g., "Sat @ 9:30 am") — skip
                    continue
                else:
                    name_parts.append(child.get_text(strip=True))
            elif isinstance(child, str):
                text = child.strip()
                if text:
                    name_parts.append(text)

        raw_title = " ".join(name_parts).strip()
        if not raw_title:
            return None

        name, city, state = self._parse_title(raw_title)
        if not name:
            return None

        return Meet(
            name=name,
            federation="RPS",
            date_start=meet_date,
            state=state,
            city=city,
            url=href,
            status=status,
        )

    # "City, ST" or, on some RPS listings, "City ST" with no comma.
    _LOCATION_RE = re.compile(r"^(?P<city>.+?),?\s+(?P<code>[A-Z]{2})$")

    def _parse_title(self, text: str) -> tuple[str | None, str | None, str | None]:
        """Parse 'Meet Name – City, ST' or 'Meet Name – City ST' into (name, city, state)."""
        separators = [" – ", " — ", " - "]

        for sep in separators:
            idx = text.rfind(sep)
            if idx == -1:
                continue

            candidate_loc = text[idx + len(sep):].strip()
            m = self._LOCATION_RE.match(candidate_loc)
            # Require a known state/province code so meet subtitles that merely
            # end in two capitals (e.g. "Women's Full Power", "Round IV") aren't
            # mistaken for a location.
            if m and m.group("code") in LOCATION_CODES:
                name = text[:idx].strip()
                city = m.group("city").strip()
                return name or None, city or None, normalize_state(m.group("code"))

        return text.strip() or None, None, None
