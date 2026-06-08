import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def scraper_runner():
    """Expose run_scraper_with_responses to tests (conftest isn't importable as
    a bare module since `tests` is a package)."""
    return run_scraper_with_responses


def run_scraper_with_responses(scraper_cls, responses, today: date = date(2026, 3, 1)):
    """Drive a scraper against canned HTTP responses with a pinned ``today``.

    ``responses`` is either an ``(request) -> httpx.Response`` handler, a dict
    (served as JSON), or a str (served as text). ``date.today()`` is pinned in
    both the scraper's own module and ``tribe_events`` (whichever it uses) so
    date-window queries are deterministic, while ``date(y, m, d)`` still builds
    real dates — mirroring the per-test pattern used across the suite.
    """
    if callable(responses):
        handler = responses
    elif isinstance(responses, dict):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=responses)
    else:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=responses)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    module = scraper_cls.__module__

    with patch.object(scraper_cls, "__init__", lambda self, **kw: None):
        scraper = scraper_cls()
        scraper.client = client
        scraper._owns_client = False

        patchers = [patch("powerlifting_meets.scrapers.tribe_events.date")]
        # Only patch the scraper's own module if it actually references `date`
        # (the trivial Tribe subclasses don't — they parse via tribe_events).
        if module != "powerlifting_meets.scrapers.tribe_events" and hasattr(
            sys.modules.get(module), "date"
        ):
            patchers.append(patch(f"{module}.date"))
        mocks = [p.start() for p in patchers]
        try:
            for mock_date in mocks:
                mock_date.today.return_value = today
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                mock_date.fromisoformat.side_effect = date.fromisoformat
            return scraper.scrape()
        finally:
            for p in patchers:
                p.stop()
