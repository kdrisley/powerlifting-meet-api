"""100% RAW now goes through the LLM extraction tier (the table's Event cell
merges name/venue/city with no delimiter, truncating multi-word cities under
deterministic parsing). Here we cover fetch_blob; the prompt itself is validated
in the gated eval suite, and the meet conversion in test_llm_extract.py."""
import httpx

from powerlifting_meets import llm_extract
from powerlifting_meets.llm_extract import ExtractedMeet
from powerlifting_meets.scrapers.raw100 import Raw100Scraper


def test_fetch_blob_extracts_schedule_text_with_cloudflare_headers():
    captured = {}
    page = (
        "<html><body><table><tr><td>06/27/26</td>"
        "<td>American Challenge The Gym Silver Spring, MD</td>"
        "<td>Bruce Knox</td></tr></table></body></html>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured["sec-fetch-mode"] = request.headers.get("sec-fetch-mode")
        if "2026-schedule" in str(request.url):
            return httpx.Response(200, text=page)
        return httpx.Response(404, text="not found")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    sc = Raw100Scraper(client=client, extract_cache={})
    blob, mime = sc.fetch_blob()
    text = blob.decode("utf-8")

    assert mime == "text/plain"
    assert "American Challenge" in text and "Silver Spring, MD" in text
    # The Cloudflare-clearing browser headers were sent.
    assert captured["sec-fetch-mode"] == "navigate"


def test_scrape_converts_extracted_meets(monkeypatch):
    monkeypatch.setattr(
        llm_extract,
        "extract_cached",
        lambda *a, **k: [
            ExtractedMeet(
                name="Shenandoah Open",
                date_start="2026-08-22",
                city="Silver Spring",
                state="MD",
                director_name="Bruce Knox",
            )
        ],
    )
    sc = Raw100Scraper(extract_cache={})
    meets = sc.scrape()
    assert len(meets) == 1
    m = meets[0]
    assert m.federation == "100RAW"
    # Multi-word city preserved (the whole point of the switch).
    assert m.city == "Silver Spring"
    assert m.state == "MD"
    assert m.country == "United States"
    assert m.director_name == "Bruce Knox"
