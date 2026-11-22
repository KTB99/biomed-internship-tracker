"""Phenom career sites: the `refineSearch` widget endpoint behind the search page."""

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
    path_segment,
    records,
    search_terms,
)
from tracker.text import clean, to_iso_date

PAGE_SIZE = 50
MAX_PAGES = 20


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    headers = {"Origin": base, "Referer": base + "/"}
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        start = 0
        term_ids: set[str] = set()
        for _ in range(MAX_PAGES):
            payload = client.post_json(base + "/widgets", _query(term, start), headers=headers)
            page = records(payload, "refineSearch", "data", "jobs")
            before = len(term_ids)
            for job in page:
                lead = _lead(company, base, job)
                if lead:
                    term_ids.add(lead.external_id)
                    leads.setdefault(lead.external_id, lead)
            start += len(page)
            total = as_int(mapping(dig(payload, "refineSearch")).get("totalHits"))
            # Stop on an empty page, a page with nothing new (server ignored the
            # offset), or once the reported total is reached.
            if len(term_ids) == before or (total is not None and start >= total):
                break
    return list(leads.values())


def _query(term: str, start: int) -> dict:
    return {
        "ddoKey": "refineSearch",
        "pageName": "search-results",
        "siteType": "external",
        "lang": "en_us",
        "deviceType": "desktop",
        "country": "us",
        "keywords": term,
        "global": True,
        "jobs": True,
        "counts": False,
        "from": start,
        "size": PAGE_SIZE,
        "selected_fields": {},
    }


def _lead(company: Company, base: str, job: dict) -> Lead | None:
    title = clean(job.get("title"))
    job_id = clean(job.get("jobId")) or clean(job.get("reqId")) or clean(job.get("jobSeqNo"))
    if not title or not job_id:
        return None
    url = clean(job.get("applyUrl"))
    if not url.startswith("https://"):
        url = urljoin(base + "/", f"us/en/job/{path_segment(job_id)}")
    location = clean(job.get("cityStateCountry")) or ", ".join(
        part for part in (clean(job.get(key)) for key in ("city", "state", "country")) if part
    )
    # `multi_location` repeats the primary site in a noisier format, so it is
    # only a fallback.
    if not location:
        locations = [clean(item) for item in job.get("multi_location") or []]
    else:
        locations = [location]
    return Lead(
        company=company.name,
        platform="phenom",
        external_id=job_id,
        title=title,
        url=url,
        locations=[item for item in locations if item],
        country=clean(job.get("country")),
        posted_on=to_iso_date(job.get("postedDate")),
        department=clean(job.get("category")),
        term=clean(job.get("type")),
        description=clean(job.get("descriptionTeaser")),
    )
