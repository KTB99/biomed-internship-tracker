"""Paradox career sites: job search results embedded in the page as preloaded state."""

from __future__ import annotations

import json

from tracker.config import Company
from tracker.http import Client, SourceError
from tracker.models import Lead
from tracker.sources._common import mapping, origin, search_terms
from tracker.text import clean

STATE_MARKER = "window.__PRELOAD_STATE__ = "


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    path = str(company.params.get("jobs_path", "/jobs"))
    leads: dict[str, Lead] = {}
    # These sites ignore paging and return the first page of each search, so
    # coverage comes from several narrow search terms (see companies.toml).
    for term in search_terms(company):
        html = client.get_text(base + path, params={"keyword": term})
        for job in _jobs(html):
            lead = _lead(company, job)
            if lead:
                leads.setdefault(lead.external_id, lead)
    return list(leads.values())


def _jobs(html: str) -> list[dict]:
    start = html.find(STATE_MARKER)
    if start < 0:
        raise SourceError("page has no preloaded job state")
    try:
        state, _ = json.JSONDecoder().raw_decode(html, start + len(STATE_MARKER))
    except ValueError as exc:
        raise SourceError("preloaded job state is not JSON") from exc
    jobs = mapping(mapping(state).get("jobSearch")).get("jobs")
    if not isinstance(jobs, list):
        raise SourceError("unexpected preloaded state: no job list")
    return [job for job in jobs if isinstance(job, dict)]


def _lead(company: Company, job: dict) -> Lead | None:
    title = clean(job.get("title"))
    url = clean(job.get("applyURL"))
    job_id = clean(job.get("requisitionID")) or clean(job.get("reference")) or url
    if not title or not url.startswith("https://"):
        return None
    locations = []
    for place in job.get("locations") or []:
        place = mapping(place)
        locations.append(clean(place.get("locationParsedText")) or clean(place.get("cityState")))
    return Lead(
        company=company.name,
        platform="paradox",
        external_id=job_id,
        title=title,
        url=url,
        locations=[place for place in locations if place],
        term=clean(job.get("employmentType")),
    )
