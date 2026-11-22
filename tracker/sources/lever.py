"""Lever public postings API. One request returns every published posting."""

from __future__ import annotations

from tracker.config import Company
from tracker.http import Client, SourceError
from tracker.models import Lead
from tracker.sources._common import mapping, param, path_segment
from tracker.text import clean, html_to_text, to_iso_date

POSTINGS_URL = "https://api.lever.co/v0/postings/{site}"


def fetch(client: Client, company: Company) -> list[Lead]:
    site = path_segment(param(company, "site"))
    payload = client.get_json(POSTINGS_URL.format(site=site), params={"mode": "json"})
    if not isinstance(payload, list):
        raise SourceError("unexpected response shape: expected a list of postings")
    leads = []
    for posting in payload:
        if not isinstance(posting, dict):
            continue
        title = clean(posting.get("text"))
        url = clean(posting.get("hostedUrl"))
        if not title or not url:
            continue
        categories = mapping(posting.get("categories"))
        locations = [clean(item) for item in categories.get("allLocations") or []]
        locations = [item for item in locations if item]
        if not locations and clean(categories.get("location")):
            locations = [clean(categories.get("location"))]
        teams = [clean(categories.get("department")), clean(categories.get("team"))]
        leads.append(
            Lead(
                company=company.name,
                platform="lever",
                external_id=clean(posting.get("id")),
                title=title,
                url=url,
                locations=locations,
                country=clean(posting.get("country")),
                posted_on=to_iso_date(posting.get("createdAt")),
                department=", ".join(team for team in teams if team),
                term=clean(categories.get("commitment")),
                description=_description(posting),
            )
        )
    return leads


def _description(posting: dict) -> str:
    parts = [str(posting.get("descriptionPlain") or "")]
    for section in posting.get("lists") or []:
        section = mapping(section)
        parts.append(clean(section.get("text")))
        parts.append(html_to_text(str(section.get("content") or "")))
    parts.append(str(posting.get("additionalPlain") or ""))
    return "\n".join(part for part in parts if part)
