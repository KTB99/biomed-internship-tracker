import pytest
import requests
from conftest import FakeResponse, fake_client

from tracker.http import Client, SourceError


def test_retries_transient_errors_then_succeeds():
    responses = [
        requests.ConnectionError("boom"),
        FakeResponse(status=503, body=""),
        FakeResponse({"ok": True}),
    ]
    client, session = fake_client(lambda *args: responses.pop(0))
    assert client.get_json("https://api.example/jobs") == {"ok": True}
    assert len(session.calls) == 3


def test_gives_up_after_all_attempts():
    client, session = fake_client(lambda *args: FakeResponse(status=500, body=""))
    with pytest.raises(SourceError, match="failed after 3 attempts"):
        client.get_json("https://api.example/jobs")
    assert len(session.calls) == 3


def test_blocked_is_not_retried():
    client, session = fake_client(lambda *args: FakeResponse(status=403, body=""))
    with pytest.raises(SourceError, match="blocked"):
        client.get_json("https://api.example/jobs")
    assert len(session.calls) == 1


def test_non_json_body_is_a_source_error():
    client, _ = fake_client(lambda *args: FakeResponse(body="<html>"))
    with pytest.raises(SourceError, match="not JSON"):
        client.get_json("https://api.example/jobs")


def test_sends_user_agent_and_timeout():
    client, session = fake_client(lambda *args: FakeResponse([]))
    client.get_json("https://api.example/jobs", params={"q": "intern"})
    _, _, kwargs = session.calls[0]
    assert kwargs["headers"]["User-Agent"].startswith("biomed-internship-tracker/")
    assert kwargs["timeout"] == client.timeout
    assert kwargs["params"] == {"q": "intern"}


def test_throttles_between_requests():
    waits = []
    now = [100.0]
    session_calls = []

    class Session:
        def request(self, *args, **kwargs):
            session_calls.append(args)
            return FakeResponse([])

    client = Client(Session(), min_interval=1.5, sleep=waits.append, clock=lambda: now[0])
    client.get_json("https://api.example/a")
    now[0] += 0.5
    client.get_json("https://api.example/b")
    assert waits == [1.0]
