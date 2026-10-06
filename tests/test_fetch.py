"""Jina fallback transport: direct requests first, Jina only when blocked."""
import httpx
import pytest

from powerlifting_meets import fetch
from powerlifting_meets.fetch import JinaFallbackTransport, is_blocked, looks_like_challenge, unwrap_pre


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch):
    monkeypatch.setattr(fetch, "MIN_INTERVAL_S", 0)
    fetch.fallback_hosts.clear()


def make_client(direct, jina):
    jina_calls = []

    def jina_handler(request):
        jina_calls.append(request)
        return jina(request)

    transport = JinaFallbackTransport(
        inner=httpx.MockTransport(direct),
        enabled=True,
        jina_client=httpx.Client(transport=httpx.MockTransport(jina_handler)),
    )
    return httpx.Client(transport=transport), jina_calls


def test_success_never_calls_jina():
    client, calls = make_client(lambda r: httpx.Response(200, text="ok"), lambda r: httpx.Response(500))
    assert client.get("https://example.com/a").text == "ok"
    assert calls == []


def test_403_retries_through_jina_with_html_format():
    client, calls = make_client(
        lambda r: httpx.Response(403, text="Attention Required! | Cloudflare"),
        lambda r: httpx.Response(200, text="<html><body><div class='meet'>Real meet</div></body></html>"),
    )
    resp = client.get("https://www.usapowerlifting.com/events?page=2")
    assert resp.status_code == 200
    assert "Real meet" in resp.text
    assert resp.headers["x-fetched-via"] == "jina"
    assert str(calls[0].url) == "https://r.jina.ai/https://www.usapowerlifting.com/events?page=2"
    assert calls[0].headers["X-Return-Format"] == "html"
    assert fetch.fallback_hosts == {"www.usapowerlifting.com"}


def test_json_wrapped_in_pre_is_unwrapped():
    wrapped = (
        '<html><head><meta name="color-scheme" content="light dark"></head><body>'
        '<pre style="word-wrap: break-word;">{"events":[{"title":"A &amp; B"}]}</pre></body></html>'
    )
    client, _ = make_client(lambda r: httpx.Response(403), lambda r: httpx.Response(200, text=wrapped))
    assert client.get("https://powerliftingunited.com/wp-json/tribe/events/v1/events").json() == {
        "events": [{"title": "A & B"}]
    }


def test_jina_challenge_or_error_returns_original_403():
    for jina_resp in (
        httpx.Response(200, text="<title>Just a moment...</title>"),
        httpx.Response(451, text="blocked"),
    ):
        client, _ = make_client(lambda r: httpx.Response(403, text="nope"), lambda r, j=jina_resp: j)
        resp = client.get("https://example.com/")
        assert resp.status_code == 403
        with pytest.raises(httpx.HTTPStatusError):
            resp.raise_for_status()


def test_404_and_post_are_not_retried():
    client, calls = make_client(lambda r: httpx.Response(404), lambda r: httpx.Response(200, text="x"))
    assert client.get("https://example.com/missing").status_code == 404
    client2, calls2 = make_client(lambda r: httpx.Response(403), lambda r: httpx.Response(200, text="x"))
    assert client2.post("https://example.com/form").status_code == 403
    assert calls == [] and calls2 == []


def test_disabled_by_env(monkeypatch):
    monkeypatch.setenv("JINA_FALLBACK", "0")
    transport = JinaFallbackTransport(inner=httpx.MockTransport(lambda r: httpx.Response(403)))
    assert httpx.Client(transport=transport).get("https://example.com/").status_code == 403


def test_helpers():
    assert is_blocked(httpx.Response(403))
    assert is_blocked(httpx.Response(503, headers={"cf-mitigated": "challenge"}))
    assert not is_blocked(httpx.Response(503))
    assert looks_like_challenge("<title>Attention Required! | Cloudflare</title>")
    assert unwrap_pre("<p>not wrapped</p>") == "<p>not wrapped</p>"
