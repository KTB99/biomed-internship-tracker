"""Attrax career sites (AbbVie): the server-rendered /en/jobs search page."""

from __future__ import annotations

import re

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import origin, search_terms
from tracker.sources._html import has_class, parse_cards
from tracker.text import clean

SEARCH_PATH = "/en/jobs"
MAX_PAGES = 20
_JOB_ID = re.compile(r"-jid-(\d+)/?$")
_LOCATION_LABEL = re.compile(r"^location\s*", re.IGNORECASE)


def _is_job_link(tag: str, attrs: dict) -> bool:
    return has_class(attrs, "attrax-vacancy-tile__title")


def _is_location(tag: str, attrs: dict) -> bool:
    # The free-text location ("North Chicago, IL"), not the city-only facet.
    return has_class(attrs, "attrax-vacancy-tile__location-freetext")


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        seen: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            params = {"q": term, "page": str(page)} if page > 1 else {"q": term}
            html = client.get_text(base + SEARCH_PATH, params=params)
            new = 0
            for card in parse_cards(html, base + "/", _is_job_link, _is_location):
                found = _JOB_ID.search(card.url)
                job_id = found.group(1) if found else card.url
                if job_id in seen:
                    continue
                seen.add(job_id)
                new += 1
                location = _LOCATION_LABEL.sub("", clean(card.location))
                leads.setdefault(
                    job_id,
                    Lead(
                        company=company.name,
                        platform="attrax",
                        external_id=job_id,
                        title=card.title,
                        url=card.url,
                        locations=[location] if location else [],
                    ),
                )
            if not new:
                break
    return list(leads.values())
