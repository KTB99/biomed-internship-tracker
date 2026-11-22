"""A company careers page that publishes its openings as schema.org JobPosting markup."""

from __future__ import annotations

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import mapping, param
from tracker.sources._html import json_ld_objects
from tracker.text import clean, html_to_text, to_iso_date


def fetch(client: Client, company: Company) -> list[Lead]:
    page = param(company, "page")
    if not page.startswith("https://"):
        raise ValueError(f"{company.name}: page must be https")
    leads: dict[str, Lead] = {}
    for item in json_ld_objects(client.get_text(page)):
        if not _is_job_posting(item):
            continue
        title = clean(item.get("title"))
        url = clean(item.get("url")) or clean(item.get("sameAs"))
        if not title or not url.startswith("https://"):
            continue
        identifier = item.get("identifier")
        job_id = clean(mapping(identifier).get("value")) if isinstance(identifier, dict) else ""
        locations, countries = _places(item.get("jobLocation"))
        leads.setdefault(
            job_id or url,
            Lead(
                company=company.name,
                platform="careers_page",
                external_id=job_id or url,
                title=title,
                url=url,
                locations=locations,
                country=countries[0] if len(set(countries)) == 1 else "",
                posted_on=to_iso_date(item.get("datePosted")),
                term=_text(item.get("employmentType")),
                description="\n".join(
                    part
                    for part in (
                        html_to_text(str(item.get("description") or "")),
                        _text(item.get("educationRequirements")),
                    )
                    if part
                ),
            ),
        )
    return list(leads.values())


def _is_job_posting(item: dict) -> bool:
    kind = item.get("@type")
    return kind == "JobPosting" or (isinstance(kind, list) and "JobPosting" in kind)


def _places(raw: object) -> tuple[list[str], list[str]]:
    places = raw if isinstance(raw, list) else [raw]
    locations, countries = [], []
    for place in places:
        address = mapping(mapping(place).get("address"))
        country = address.get("addressCountry")
        if isinstance(country, dict):
            country = mapping(country).get("name")
        country = clean(country)
        parts = [
            clean(address.get("addressLocality")),
            clean(address.get("addressRegion")),
            country,
        ]
        text = ", ".join(part for part in parts if part)
        if text:
            locations.append(text)
        if country:
            countries.append(country)
    return locations, countries


def _text(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(_text(item) for item in value)
    if isinstance(value, dict):
        return clean(value.get("name") or value.get("credentialCategory"))
    return clean(value)
