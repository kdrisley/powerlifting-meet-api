"""fetch_blob tests for the LLM-extraction scrapers (no Gemini involved).

The extraction itself is covered (mocked) in test_llm_extract.py; here we verify
each scraper turns its source into the right blob/mime for the extraction tier.
"""
import httpx
import pytest

from powerlifting_meets.scrapers.ipa import IPAScraper
from powerlifting_meets.scrapers.nasa import NASAScraper
from powerlifting_meets.scrapers.wnpf import WNPFScraper


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_wnpf_fetch_blob_extracts_text():
    html = "<html><body><h1>2026 Schedule</h1><p>JUNE 20, 2026 WNPF Pan-Ams, Cocoa FL</p></body></html>"

    def handler(request):
        return httpx.Response(200, text=html)

    sc = WNPFScraper(client=_client(handler), extract_cache={})
    blob, mime = sc.fetch_blob()
    assert mime == "text/plain"
    text = blob.decode("utf-8")
    assert "WNPF Pan-Ams" in text
    # Wix markup is stripped to visible text.
    assert "<p>" not in text


def test_ipa_fetch_blob_strips_chrome():
    html = """<html><head><script>var x=1</script></head><body>
      <nav>menu junk</nav>
      <main><h2>WESTERN OHIO OPEN</h2><p>June 6 2026, Eaton Barbell, Camden OH</p></main>
      <footer>footer junk</footer></body></html>"""

    def handler(request):
        return httpx.Response(200, text=html)

    sc = IPAScraper(client=_client(handler), extract_cache={})
    blob, mime = sc.fetch_blob()
    text = blob.decode("utf-8")
    assert "WESTERN OHIO OPEN" in text
    assert "menu junk" not in text and "footer junk" not in text


def test_nasa_fetch_blob_uses_rendered_upcoming_meets(monkeypatch):
    # /upcoming-meets/ builds its list with JavaScript, so NASA always reads the
    # Jina-rendered markdown rather than the raw HTML.
    calls = []

    def fake_jina_get(url, fmt="html", client=None):
        calls.append((url, fmt))
        return "**October 2026**\nColorado Regional · October 17, 2026 · Greeley, CO"

    monkeypatch.setattr("powerlifting_meets.scrapers.nasa.jina_get", fake_jina_get)
    sc = NASAScraper(client=_client(lambda r: httpx.Response(500)), extract_cache={})
    blob, mime = sc.fetch_blob()
    assert calls == [("https://nasa-sports.com/upcoming-meets/", "markdown")]
    assert mime == "text/plain"
    assert "Colorado Regional" in blob.decode("utf-8")


def test_nasa_fetch_blob_raises_when_render_fails(monkeypatch):
    monkeypatch.setattr("powerlifting_meets.scrapers.nasa.jina_get", lambda *a, **k: None)
    sc = NASAScraper(client=_client(lambda r: httpx.Response(500)), extract_cache={})
    with pytest.raises(RuntimeError):
        sc.fetch_blob()
