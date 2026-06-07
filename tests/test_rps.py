from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from bs4 import BeautifulSoup

from powerlifting_meets.scrapers.rps import RPSScraper


@pytest.fixture
def rps_html(fixtures_dir: Path) -> str:
    return (fixtures_dir / "rps_meets.html").read_text()


# Minimal RPS detail page carrying the meet-director line (email is plain text,
# not a mailto link, as on the real site) and a jotform sign-up link.
_DETAIL_HTML = (
    "<html><body><div class='entry-content'>"
    "<p>Meet Director: Matt Staub – hogmodetraining@gmail.com</p>"
    "<p>Some venue address, City, ST</p>"
    "<a href='https://form.jotform.com/253644134571153'>Register Here</a>"
    "</div></body></html>"
)


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def _route_handler(rps_html: str):
    """Return the listing for the root URL and a detail page for meet URLs."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.strip("/"):
            return httpx.Response(200, text=_DETAIL_HTML)
        return httpx.Response(200, text=rps_html)

    return handler


class TestRPSScraper:
    def test_scrape_from_fixture(self, rps_html: str):
        transport = httpx.MockTransport(_route_handler(rps_html))
        client = httpx.Client(transport=transport)

        with patch.object(RPSScraper, "__init__", lambda self, **kw: None):
            scraper = RPSScraper()
            scraper.client = client
            scraper._owns_client = False

            with patch("powerlifting_meets.scrapers.rps.date") as mock_date:
                mock_date.today.return_value = date(2026, 3, 1)
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                meets = scraper.scrape()

        assert len(meets) == 6
        assert all(m.federation == "RPS" for m in meets)

        # First meet - Sold Out
        m = meets[0]
        assert m.name == "Dominion"
        assert m.date_start == date(2026, 3, 14)
        assert m.city == "Farmingdale"
        assert m.state == "NY"
        assert m.status == "sold_out"
        # Director and sign-up link enriched from the detail page; url stays the
        # info page.
        assert m.director_name == "Matt Staub"
        assert m.director_email == "hogmodetraining@gmail.com"
        assert str(m.url).startswith("https://meets.revolutionpowerlifting.com/")
        assert str(m.registration_url) == "https://form.jotform.com/253644134571153"

        # Second meet - active, no status badge
        m = meets[1]
        assert m.name == "17th Bristol Big Bench"
        assert m.city == "Fairless Hills"
        assert m.state == "PA"
        assert m.status == "active"

        # Canadian meet - state should be None
        m = meets[2]
        assert m.name == "Iron Annihilation 9"
        assert m.city == "Ottawa"
        assert m.state is None  # ON is not a US state

        # No comma between city and state — must still split location off the name
        m = meets[5]
        assert m.name == "Power Palooza 29"
        assert m.city == "Lancaster"
        assert m.state == "PA"
        assert m.status == "active"

    def test_parse_director(self):
        scraper = RPSScraper.__new__(RPSScraper)

        name, email = scraper._parse_director(_soup(_DETAIL_HTML))
        assert name == "Matt Staub"
        assert email == "hogmodetraining@gmail.com"

        # "Director:" (no "Meet"), email in parentheses, nbsp in the name.
        name, email = scraper._parse_director(_soup(
            "<p>Natick MA, 01760 Director: Robert\xa0Popp "
            "(rpopp@nsiteam.com, 781-864-1347) Entry Fee: $135</p>"
        ))
        assert name == "Robert Popp"
        assert email == "rpopp@nsiteam.com"

        # "Meet Director –" with only a phone number: name parsed, email None.
        name, email = scraper._parse_director(_soup(
            "<p>Meet Director – Henri Skiba – 732-598-9369 Rare Breed Fitness</p>"
        ))
        assert name == "Henri Skiba"
        assert email is None

        # No director line -> both None, so the meet is left unenriched.
        name, email = scraper._parse_director(_soup("<p>No info</p>"))
        assert name is None
        assert email is None

    def test_find_registration(self):
        scraper = RPSScraper.__new__(RPSScraper)
        assert (
            scraper._find_registration(_soup(_DETAIL_HTML))
            == "https://form.jotform.com/253644134571153"
        )
        # No sign-up link present.
        assert scraper._find_registration(_soup("<p>nothing</p>")) is None

    def test_title_parsing(self):
        scraper = RPSScraper.__new__(RPSScraper)

        name, city, state = scraper._parse_title("Big Meet – Houston, TX")
        assert name == "Big Meet"
        assert city == "Houston"
        assert state == "TX"

        name, city, state = scraper._parse_title("Meet Name")
        assert name == "Meet Name"
        assert city is None
        assert state is None

        # No comma between city and state
        name, city, state = scraper._parse_title("Merry Gainzmas – Pflugerville TX")
        assert name == "Merry Gainzmas"
        assert city == "Pflugerville"
        assert state == "TX"

        # Multi-word city, no comma
        name, city, state = scraper._parse_title("Power Palooza 29 – Lancaster PA")
        assert name == "Power Palooza 29"
        assert city == "Lancaster"
        assert state == "PA"

        # Subtitle ending in two capitals must NOT be treated as a location
        name, city, state = scraper._parse_title("Crowned in Iron II – Women's Full Power")
        assert name == "Crowned in Iron II – Women's Full Power"
        assert city is None
        assert state is None

        # Two separators: only the trailing location is split off
        name, city, state = scraper._parse_title(
            "Crowned in Iron II – Women's Full Power – Fort Mill, SC"
        )
        assert name == "Crowned in Iron II – Women's Full Power"
        assert city == "Fort Mill"
        assert state == "SC"

        # Full state name spelled out, after a dash with no leading space.
        name, city, state = scraper._parse_title(
            "2026 RPS Tri- State Challenge at Mpower Gym- Dayton Ohio"
        )
        assert name == "2026 RPS Tri- State Challenge at Mpower Gym"
        assert city == "Dayton"
        assert state == "OH"

        # Hyphenated city name must stay intact (not split on its hyphen).
        name, city, state = scraper._parse_title("Bench Bash – Wilkes-Barre, PA")
        assert name == "Bench Bash"
        assert city == "Wilkes-Barre"
        assert state == "PA"
