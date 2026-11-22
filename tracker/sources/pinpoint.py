"""Pinpoint job boards: one public jobs.json listing every open job."""

from __future__ import annotations

import re

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import mapping, param, records
from tracker.text import clean, html_to_text, to_iso_date

# Pinpoint location names look like "US-California-San Jose" or "EMEA-Poland".
_REGION_NAME = re.compile(r"^([A-Za-z]{2,4})-([^-]+)-(.+)$")


def fetch(client: Client, company: Company) -> list[Lead]:
    jobs_url = param(company, "jobs_url")
    if not jobs_url.startswith("https://"):
        raise ValueError(f"{company.name}: jobs_url must be https")
    leads = []
    for job in records(client.get_json(jobs_url), "data"):
        title = clean(job.get("title"))
        url = clean(job.get("url"))
        if not title or not url.startswith("https://"):
            continue
        location = _location(clean(mapping(job.get("location")).get("name")))
        description = "\n".join(
            html_to_text(str(job.get(key) or ""))
            for key in ("description", "key_responsibilities", "skills_knowledge_expertise")
        )
        leads.append(
            Lead(
                company=company.name,
                platform="pinpoint",
                external_id=clean(job.get("id")) or clean(job.get("requisition_id")),
                title=title,
                url=url,
                locations=[location] if location else [],
                posted_on=to_iso_date(job.get("published_at") or job.get("created_at")),
                department=clean(mapping(job.get("department")).get("name")),
                term=clean(job.get("employment_type_text")),
                description=description.strip(),
            )
        )
    return leads


def _location(name: str) -> str:
    match = _REGION_NAME.match(name)
    if not match:
        return name
    country, region, city = match.groups()
    return f"{city.strip()}, {region.strip()}, {country.upper()}"
