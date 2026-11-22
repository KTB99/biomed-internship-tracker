"""Polite HTTP client shared by every source: throttling, timeouts and retries."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

USER_AGENT = "biomed-internship-tracker/0.1"
MAX_RESPONSE_BYTES = 25_000_000
RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class SourceError(RuntimeError):
    """A source could not be read. Its listings are left untouched for this run."""


class Client:
    def __init__(
        self,
        session: Any = None,
        *,
        timeout: float = 20.0,
        min_interval: float = 1.0,
        attempts: int = 3,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.session = session if session is not None else requests.Session()
        self.timeout = timeout
        self.min_interval = min_interval
        self.attempts = max(1, attempts)
        self.sleep = sleep
        self.clock = clock
        self._last_request: float | None = None

    def get_json(self, url: str, *, params: dict | None = None, headers: dict | None = None):
        return self._json("GET", url, params=params, headers=headers)

    def post_json(self, url: str, body: dict, *, headers: dict | None = None):
        return self._json("POST", url, json=body, headers=headers)

    def _json(self, method: str, url: str, **kwargs):
        response = self._send(method, url, **kwargs)
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise SourceError(f"{method} {url}: response too large")
        try:
            return response.json()
        except ValueError as exc:
            raise SourceError(f"{method} {url}: response was not JSON") from exc

    def _send(self, method: str, url: str, *, headers: dict | None = None, **kwargs):
        merged = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        merged.update(headers or {})
        problem = "no attempt made"
        for attempt in range(1, self.attempts + 1):
            self._throttle()
            try:
                response = self.session.request(
                    method, url, headers=merged, timeout=self.timeout, **kwargs
                )
            except requests.RequestException as exc:
                problem = type(exc).__name__
            else:
                status = response.status_code
                if 200 <= status < 300:
                    return response
                if status in (401, 403):
                    raise SourceError(f"{method} {url}: blocked (HTTP {status})")
                if status not in RETRYABLE_STATUSES:
                    raise SourceError(f"{method} {url}: HTTP {status}")
                problem = f"HTTP {status}"
            if attempt < self.attempts:
                self.sleep(2.0 * attempt)
        raise SourceError(f"{method} {url}: failed after {self.attempts} attempts ({problem})")

    def _throttle(self) -> None:
        if self._last_request is not None:
            wait = self.min_interval - (self.clock() - self._last_request)
            if wait > 0:
                self.sleep(wait)
        self._last_request = self.clock()
