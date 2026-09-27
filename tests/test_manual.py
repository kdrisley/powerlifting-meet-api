"""ManualScraper: approved meet-submission issues become feed meets."""
import json
from datetime import date

import httpx
import pytest

from powerlifting_meets.scrapers.manual import ManualScraper, meet_from_issue_body

TODAY = date(2026, 9, 27)


def body(meet: dict) -> str:
    return (
        "Submitted through powerliftingrecords.com/submit-meet/.\n\n"
        "- **Meet:** whatever\n\n"
        "```json\n" + json.dumps(meet, indent=2) + "\n```"
    )


VALID = {
    "name": "Lone Star Open",
    "federation": "USAPL",
    "date_start": "2026-11-14",
    "date_end": None,
    "city": "Austin",
    "state": "TX",
    "region": None,
    "country": "United States",
    "url": "https://example.com/lone-star",
    "registration_url": None,
    "testing_status": "tested",
}


def scraper_for(pages: list[list[dict]], captured: dict | None = None) -> ManualScraper:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.setdefault("params", []).append(dict(request.url.params))
            captured["auth"] = request.headers.get("authorization")
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(200, json=pages[page - 1] if page <= len(pages) else [])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ManualScraper(client=client, today=TODAY)


def test_meet_from_issue_body_parses_valid_block():
    meet = meet_from_issue_body(body(VALID))
    assert meet is not None
    assert meet.name == "Lone Star Open"
    assert meet.state == "TX"
    assert meet.date_start == date(2026, 11, 14)
    assert meet.testing_status == "tested"


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "no json here",
        "```json\n{not json}\n```",
        "```json\n[1, 2]\n```",
        "```json\n" + json.dumps({**VALID, "date_start": "someday"}) + "\n```",
        "```json\n" + json.dumps({**VALID, "url": "not a url"}) + "\n```",
    ],
)
def test_meet_from_issue_body_rejects_bad_bodies(text):
    assert meet_from_issue_body(text) is None


def test_scrape_keeps_upcoming_and_skips_past_invalid_and_prs(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t0ken")
    captured: dict = {}
    issues = [
        {"number": 1, "body": body(VALID)},
        {"number": 2, "body": body({**VALID, "name": "Old Meet", "date_start": "2026-01-10"})},
        # Started yesterday but runs through tomorrow: still upcoming.
        {
            "number": 3,
            "body": body(
                {**VALID, "name": "Weekend Meet", "date_start": "2026-09-26", "date_end": "2026-09-28"}
            ),
        },
        {"number": 4, "body": "someone removed the json"},
        {"number": 5, "body": body(VALID), "pull_request": {"url": "x"}},
    ]
    meets = scraper_for([issues], captured).scrape()

    assert [m.name for m in meets] == ["Lone Star Open", "Weekend Meet"]
    params = captured["params"][0]
    assert params["labels"] == "meet-submission,approved"
    assert params["state"] == "all"
    assert captured["auth"] == "Bearer t0ken"


def test_scrape_follows_pagination():
    full_page = [{"number": i, "body": body({**VALID, "name": f"Meet {i}"})} for i in range(100)]
    second = [{"number": 100, "body": body({**VALID, "name": "Meet 100"})}]
    meets = scraper_for([full_page, second]).scrape()
    assert len(meets) == 101


def test_scrape_raises_on_api_error_so_runner_marks_it_failed():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, json={})))
    with pytest.raises(httpx.HTTPStatusError):
        ManualScraper(client=client, today=TODAY).scrape()
