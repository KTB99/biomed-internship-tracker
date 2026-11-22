"""Helpers for reading platform responses defensively."""

from __future__ import annotations

from urllib.parse import quote

from tracker.config import Company
from tracker.http import SourceError

# Search terms for platforms that need a query rather than returning a whole board.
# Some sites return different results for "intern" and "internship", so both are used.
SEARCH_TERMS = ("intern", "internship", "co-op")


def search_terms(company: Company) -> tuple[str, ...]:
    """The company's `search_terms` parameter, or the defaults."""
    custom = company.params.get("search_terms")
    if custom is None:
        return SEARCH_TERMS
    terms = tuple(str(term).strip() for term in custom if str(term).strip())
    if not terms:
        raise ValueError(f"{company.name}: search_terms must not be empty")
    return terms


def job_id_from_url(url: str) -> str:
    """The last all-digit path segment of a job URL, or the URL itself."""
    digits = [part for part in url.split("?")[0].split("/") if part.isdigit()]
    return digits[-1] if digits else url


def param(company: Company, key: str) -> str:
    value = str(company.params.get(key, "")).strip()
    if not value:
        raise ValueError(f"{company.name}: missing platform parameter {key!r}")
    return value


def path_segment(value: str) -> str:
    return quote(value, safe="")


def origin(company: Company) -> str:
    value = param(company, "origin").rstrip("/")
    if not value.startswith("https://"):
        raise ValueError(f"{company.name}: origin must be https")
    return value


def dig(payload: object, *keys: str) -> object:
    """Follow dict keys, raising SourceError when the response has another shape."""
    current = payload
    for key in keys:
        if not isinstance(current, dict):
            raise SourceError(f"unexpected response shape at {key!r}")
        current = current.get(key)
    return current


def records(payload: object, *keys: str) -> list[dict]:
    value = dig(payload, *keys)
    if value is None:
        return []
    if not isinstance(value, list):
        raise SourceError("unexpected response shape: expected a list of jobs")
    return [item for item in value if isinstance(item, dict)]


def mapping(value: object) -> dict:
    return value if isinstance(value, dict) else {}


def as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
