from __future__ import annotations

import json

import pytest
import requests

from tracker.config import Company, Settings
from tracker.http import Client


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("tests must not use the network")

    monkeypatch.setattr(requests.Session, "request", refuse)


class FakeResponse:
    def __init__(self, payload=None, *, status: int = 200, body: str | None = None):
        self.status_code = status
        self.content = (body if body is not None else json.dumps(payload)).encode("utf-8")

    def json(self):
        return json.loads(self.content)


class FakeSession:
    """Answers each request with `handler(method, url, kwargs)` and records it."""

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[tuple[str, str, dict]] = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        response = self.handler(method, url, kwargs)
        if isinstance(response, Exception):
            raise response
        return response


def fake_client(handler) -> tuple[Client, FakeSession]:
    session = FakeSession(handler)
    return Client(session, min_interval=0, sleep=lambda seconds: None), session


def company(name="Acme Medical", platform="greenhouse", **params) -> Company:
    return Company(name=name, platform=platform, careers_url="https://acme.example", params=params)


def settings(*companies: Company, season="summer-2027") -> Settings:
    return Settings(season=season, companies=tuple(companies))
