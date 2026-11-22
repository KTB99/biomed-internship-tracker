"""SmartRecruiters public postings API, searched by keyword and paged by offset."""

from __future__ import annotations

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import SEARCH_TERMS, as_int, mapping, param, path_segment, records
from tracker.text import clean, to_iso_date

POSTINGS_URL = "https://api.smartrecruiters.com/v1/companies/{company_id}/postings"
JOB_URL = "https://jobs.smartrecruiters.com/{company_id}/{job_id}"
PAGE_SIZE = 100
MAX_PAGES = 10


def fetch(client: Client, company: Company) -> list[Lead]:
    company_id = path_segment(param(company, "company_id"))
    url = POSTINGS_URL.format(company_id=company_id)
    leads: dict[str, Lead] = {}
    for term in SEARCH_TERMS:
        offset = 0
        term_ids: set[str] = set()
        for _ in range(MAX_PAGES):
            payload = client.get_json(
                url, params={"q": term, "limit": PAGE_SIZE, "offset": offset}
            )
            page = records(payload, "content")
            before = len(term_ids)
            for posting in page:
                lead = _lead(company, company_id, posting)
                if lead:
                    term_ids.add(lead.external_id)
                    leads.setdefault(lead.external_id, lead)
            offset += len(page)
            total = as_int(mapping(payload).get("totalFound"))
            if len(term_ids) == before or (total is not None and offset >= total):
                break
    return list(leads.values())


def _lead(company: Company, company_id: str, posting: dict) -> Lead | None:
    job_id = clean(posting.get("id"))
    title = clean(posting.get("name"))
    if not job_id or not title:
        return None
    place = mapping(posting.get("location"))
    location = clean(place.get("fullLocation")) or ", ".join(
        part for part in (clean(place.get(key)) for key in ("city", "region", "country")) if part
    )
    if place.get("remote") is True and location:
        location += " (remote)"
    return Lead(
        company=company.name,
        platform="smartrecruiters",
        external_id=job_id,
        title=title,
        url=JOB_URL.format(company_id=company_id, job_id=path_segment(job_id)),
        locations=[location] if location else [],
        country=clean(place.get("country")),
        posted_on=to_iso_date(posting.get("releasedDate")),
        department=clean(mapping(posting.get("department")).get("label")),
        term=clean(mapping(posting.get("typeOfEmployment")).get("label")),
    )
