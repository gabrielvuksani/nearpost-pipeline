import logging

import httpx

from nearpost.health import Healthchecks


def _pinger(handler, key="ping-key-123"):
    return Healthchecks(httpx.Client(transport=httpx.MockTransport(handler)), key, "nearpost-tick")


def test_start_success_and_fail_hit_the_slug_urls_with_auto_create():
    seen = []

    def handler(request):
        seen.append((request.method, str(request.url), request.content))
        return httpx.Response(200)

    pinger = _pinger(handler)
    pinger.start()
    pinger.success("appended 4 entries")
    pinger.fail("odds-api unavailable")

    assert seen == [
        ("POST", "https://hc-ping.com/ping-key-123/nearpost-tick/start?create=1", b""),
        ("POST", "https://hc-ping.com/ping-key-123/nearpost-tick?create=1", b"appended 4 entries"),
        ("POST", "https://hc-ping.com/ping-key-123/nearpost-tick/fail?create=1", b"odds-api unavailable"),
    ]


def test_long_bodies_are_truncated_to_the_healthchecks_limit():
    bodies = []
    _pinger(lambda r: bodies.append(r.content) or httpx.Response(200)).fail("x" * 200_000)
    assert len(bodies[0]) == 100_000


def test_without_a_key_pings_are_skipped_with_a_warning(caplog):
    calls = []
    pinger = _pinger(lambda r: calls.append(r) or httpx.Response(200), key=None)
    with caplog.at_level(logging.WARNING):
        pinger.success("ok")
    assert calls == []
    assert "healthchecks disabled" in caplog.text


def test_a_failed_ping_is_logged_but_never_raised_and_never_leaks_the_key(caplog):
    def handler(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    with caplog.at_level(logging.ERROR):
        _pinger(handler).fail("boom")
    assert "healthchecks ping failed" in caplog.text
    assert "ping-key-123" not in caplog.text
