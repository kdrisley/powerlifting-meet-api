"""HTTP transport that retries blocked requests through Jina Reader.

Several federation sites block our direct requests: USAPL's calendar sits
behind Cloudflare bot protection that rejects every non-browser client, and
PLU, NPL, APO and NASA return 403 to GitHub Actions IP ranges while serving
the same public pages to anyone else. Every scraper's client uses this
transport, so the direct request is always tried first. Only when it comes
back blocked (403, or a Cloudflare challenge) is the same GET re-issued via
https://r.jina.ai/, which fetches the page from Jina's own browsers and
returns the rendered HTML. No scraper code changes are needed.

Jina's keyless tier allows 20 requests/minute, so fallback calls are spaced
out. A Jina failure, or a Jina response that is itself a challenge page,
returns the original blocked response, so callers see the same error they
would have without the fallback.
"""
from __future__ import annotations

import html
import logging
import os
import re
import threading
import time

import httpx

logger = logging.getLogger(__name__)

JINA_ENDPOINT = "https://r.jina.ai/"
# Keyless limit is 20/min; 3.5s spacing keeps a burst (USAPL's ~26 pages) under it.
MIN_INTERVAL_S = 3.5
JINA_TIMEOUT_S = 90.0

_CHALLENGE_MARKERS = (
    "Attention Required! | Cloudflare",
    "<title>Just a moment...</title>",
    "cf-browser-verification",
    "challenge-platform/h/",
)
# A JSON or text body rendered by a browser comes back as a bare <pre>.
_BARE_PRE = re.compile(
    r"^\s*<html[^>]*>\s*<head>.*?</head>\s*<body>\s*<pre[^>]*>(.*)</pre>\s*</body>\s*</html>\s*$",
    re.DOTALL | re.IGNORECASE,
)

# Hosts that needed the fallback during this process, for the run summary.
fallback_hosts: set[str] = set()

# Every scraper builds its own client, so pacing is shared process-wide.
_pace_lock = threading.Lock()
_last_call = 0.0


def is_blocked(response: httpx.Response) -> bool:
    """True when a response looks like bot blocking rather than real content."""
    if response.status_code == 403:
        return True
    if response.status_code in (429, 503) and (
        "cf-mitigated" in response.headers or response.headers.get("server", "").lower() == "cloudflare"
    ):
        return True
    return False


def looks_like_challenge(text: str) -> bool:
    head = text[:5000]
    return any(marker in head for marker in _CHALLENGE_MARKERS)


def unwrap_pre(body: str) -> str:
    """Return the raw text of a browser-rendered JSON/text document."""
    m = _BARE_PRE.match(body)
    return html.unescape(m.group(1)) if m else body


def _wait_turn() -> None:
    global _last_call
    with _pace_lock:
        wait = _last_call + MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def jina_get(url: str, fmt: str = "html", client: httpx.Client | None = None) -> str | None:
    """Fetch `url` through Jina Reader, rendered as `fmt` ("html" or "markdown").

    Returns None on failure or when Jina itself was served a challenge page.
    Also used directly by scrapers whose pages only render with JavaScript.
    """
    headers = {"X-Return-Format": fmt}
    token = os.environ.get("JINA_API_KEY")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    own = client is None
    client = client or httpx.Client(timeout=JINA_TIMEOUT_S)
    try:
        for attempt in range(2):
            _wait_turn()
            try:
                r = client.get(JINA_ENDPOINT + url, headers=headers)
            except httpx.HTTPError as exc:
                logger.warning("Jina fetch failed for %s: %s", url, exc)
                return None
            if r.status_code == 429 and attempt == 0:
                time.sleep(20)
                continue
            break
        if r.status_code != 200 or looks_like_challenge(r.text):
            logger.warning("Jina fetch unusable for %s (HTTP %s)", url, r.status_code)
            return None
        return r.text
    finally:
        if own:
            client.close()


class JinaFallbackTransport(httpx.BaseTransport):
    def __init__(
        self,
        inner: httpx.BaseTransport | None = None,
        enabled: bool | None = None,
        jina_client: httpx.Client | None = None,
    ) -> None:
        self._inner = inner or httpx.HTTPTransport()
        # JINA_FALLBACK=0 turns the fallback off (e.g. for local debugging).
        self._enabled = enabled if enabled is not None else os.environ.get("JINA_FALLBACK", "1") != "0"
        self._jina = jina_client or httpx.Client(timeout=JINA_TIMEOUT_S)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        if not self._enabled or request.method != "GET" or not is_blocked(response):
            return response
        response.read()
        fallback = self._fetch_via_jina(request)
        if fallback is None:
            return response
        response.close()
        return fallback

    def _fetch_via_jina(self, request: httpx.Request) -> httpx.Response | None:
        url = str(request.url)
        text = jina_get(url, "html", client=self._jina)
        if text is None:
            return None
        fallback_hosts.add(request.url.host)
        logger.info("Fetched %s via Jina fallback (direct request was blocked)", url)
        body = unwrap_pre(text)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8", "x-fetched-via": "jina"},
            content=body.encode("utf-8"),
            request=request,
        )

    def close(self) -> None:
        self._inner.close()
        self._jina.close()
