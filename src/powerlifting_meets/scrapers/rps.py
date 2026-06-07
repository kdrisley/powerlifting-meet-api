from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

from powerlifting_meets.models import Meet
from powerlifting_meets.normalize import parse_trailing_location
from powerlifting_meets.scrapers.base import BaseScraper

logger = logging.getLogger(__name__)

MEETS_URL = "https://meets.revolutionpowerlifting.com/"

# Number of meet detail pages to fetch in parallel when enriching directors.
_DETAIL_WORKERS = 8


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

        # The listing has no contact info; the meet director's name and email
        # live on each meet's detail page. Fetch them in parallel and attach.
        self._enrich_directors(meets)

        logger.info("Scraped %d RPS meets", len(meets))
        return meets

    def _enrich_directors(self, meets: list[Meet]) -> None:
        """Populate director_name/director_email from each meet's detail page."""
        def fetch(meet: Meet) -> None:
            if not meet.url:
                return
            try:
                resp = self.client.get(str(meet.url))
                resp.raise_for_status()
            except Exception as exc:  # one bad page shouldn't sink the scrape
                logger.warning("RPS detail fetch failed for %s: %s", meet.url, exc)
                return
            meet.director_name, meet.director_email = self._parse_director(resp.text)

        with ThreadPoolExecutor(max_workers=_DETAIL_WORKERS) as pool:
            list(pool.map(fetch, meets))

    # Detail pages label the director inconsistently: "Meet Director:",
    # "Director:", "Directors:" (plural), lowercase, or "Meet Director –". A
    # separator after the label avoids matching breadcrumbs like "Director /".
    _DIRECTOR_RE = re.compile(
        r"\b(?:Meet\s+)?Directors?\b\s*[:–—-]\s*(?P<rest>.{0,120})", re.IGNORECASE
    )
    _EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
    # Leading run of name characters; stops at a dash, comma, paren, ampersand,
    # digit, or email — i.e. where co-directors or contact details begin.
    _NAME_RE = re.compile(r"[A-Za-z][A-Za-z .'\-]*")
    # Contact labels that can trail the name ("John Doe Email: ...").
    _NAME_LABEL_RE = re.compile(
        r"\b(?:Email|E-mail|Phone|Tel|Cell|Mobile|Contact)\b.*$", re.IGNORECASE
    )

    def _parse_director(self, html: str) -> tuple[str | None, str | None]:
        text = BeautifulSoup(html, "lxml").get_text(" ", strip=True).replace("\xa0", " ")
        m = self._DIRECTOR_RE.search(text)
        if not m:
            return None, None
        rest = m.group("rest")

        email_m = self._EMAIL_RE.search(rest)
        email = email_m.group(0) if email_m else None

        name_m = self._NAME_RE.match(rest)
        name = name_m.group(0) if name_m else ""
        # Drop a trailing contact label ("... Email"), then a swallowed email
        # local part if there was no separator ("Robert Popp rpopp@...").
        name = self._NAME_LABEL_RE.sub("", name)
        if email:
            local = email.split("@", 1)[0]
            if local in name:
                name = name.split(local)[0]
        name = name.strip(" .,-") or None
        return name, email

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

    # A dash (-, –, —) followed by whitespace. A leading space is optional so
    # listings like "...Mpower Gym- Dayton Ohio" split as well as the usual
    # spaced " – ". Requiring trailing whitespace keeps hyphenated names intact
    # ("Wilkes-Barre", "Push-Pull").
    _SEPARATOR_RE = re.compile(r"[–—-]\s+")

    def _parse_title(self, text: str) -> tuple[str | None, str | None, str | None]:
        """Parse 'Meet Name – City, ST' / 'Meet Name – City ST' / 'Meet Name - City StateName'."""
        # Try each separator from right to left; the first whose trailing
        # segment parses as a real location wins. Validating the segment is a
        # known location keeps meet subtitles (e.g. "– Women's Full Power") from
        # being mistaken for a city/state split.
        for m in reversed(list(self._SEPARATOR_RE.finditer(text))):
            loc = parse_trailing_location(text[m.end():])
            if loc:
                name = text[: m.start()].rstrip()
                city, state = loc
                return name or None, city or None, state

        return text.strip() or None, None, None
