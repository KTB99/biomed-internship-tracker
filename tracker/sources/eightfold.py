"""Eightfold careers search API (the JSON behind Eightfold-hosted career sites)."""

from __future__ import annotations

from urllib.parse import urljoin

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import (
    as_int,
    dig,
    mapping,
    origin,
    param,
    records,
    search_terms,
)
from tracker.text import clean, to_iso_date

SEARCH_PATH = "/api/pcsx/search"
MAX_PAGES = 30


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    domain = param(company, "domain")
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        start = 0
        term_ids: set[str] = set()
        for _ in range(MAX_PAGES):
            payload = client.get_json(
                base + SEARCH_PATH, params={"domain": domain, "query": term, "start": start}
            )
            page = records(payload, "data", "positions")
            before = len(term_ids)
            for position in page:
                lead = _lead(company, base, position)
                if lead:
                    term_ids.add(lead.external_id)
                    leads.setdefault(lead.external_id, lead)
            start += len(page)
            total = as_int(mapping(dig(payload, "data")).get("count"))
            if len(term_ids) == before or (total is not None and start >= total):
                break
    return list(leads.values())


def _lead(company: Company, base: str, position: dict) -> Lead | None:
    position_id = clean(position.get("id"))
    title = clean(position.get("name"))
    if not position_id or not title:
        return None
    path = clean(position.get("positionUrl")) or f"/careers/job/{position_id}"
    url = urljoin(base + "/", path)
    if not url.startswith(base + "/"):
        url = f"{base}/careers/job/{position_id}"
    locations = [clean(item) for item in position.get("locations") or []]
    locations += [clean(item) for item in position.get("standardizedLocations") or []]
    return Lead(
        company=company.name,
        platform="eightfold",
        external_id=clean(position.get("atsJobId")) or position_id,
        title=title,
        url=url,
        locations=[item for item in locations if item],
        posted_on=to_iso_date(position.get("postedTs")),
        department=clean(position.get("department")),
    )
