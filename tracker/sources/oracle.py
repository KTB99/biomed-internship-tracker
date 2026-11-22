"""Oracle Recruiting Cloud: the requisition search behind *.oraclecloud.com career sites."""

from __future__ import annotations

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import (
    as_int,
    mapping,
    origin,
    param,
    path_segment,
    records,
    search_terms,
)
from tracker.text import clean, html_to_text, to_iso_date

SEARCH_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
PAGE_SIZE = 25
MAX_PAGES = 20
DESCRIPTION_FIELDS = (
    "ShortDescriptionStr",
    "ExternalResponsibilitiesStr",
    "ExternalQualificationsStr",
)


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    site = param(company, "site")
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        # The finder is a ;/,-delimited expression, so keep those out of the keyword.
        keyword = term.replace(",", " ").replace(";", " ")
        for page in range(MAX_PAGES):
            finder = (
                f"findReqs;siteNumber={site},keyword={keyword},"
                f"offset={page * PAGE_SIZE},limit={PAGE_SIZE}"
            )
            payload = client.get_json(
                base + SEARCH_PATH,
                params={"onlyData": "true", "expand": "requisitionList", "finder": finder},
            )
            results = records(payload, "items")
            if not results:
                break
            listed = results[0].get("requisitionList") or []
            batch = [item for item in listed if isinstance(item, dict)]
            for requisition in batch:
                lead = _lead(company, base, site, requisition)
                if lead:
                    leads.setdefault(lead.external_id, lead)
            total = as_int(results[0].get("TotalJobsCount"))
            seen = (page + 1) * PAGE_SIZE
            if not batch or (total is not None and seen >= total):
                break
    return list(leads.values())


def _lead(company: Company, base: str, site: str, requisition: dict) -> Lead | None:
    job_id = clean(requisition.get("Id"))
    title = clean(requisition.get("Title"))
    if not job_id or not title:
        return None
    locations = [clean(requisition.get("PrimaryLocation"))]
    for extra in requisition.get("secondaryLocations") or []:
        locations.append(clean(mapping(extra).get("Name")))
    description = "\n".join(
        html_to_text(str(requisition.get(key) or "")) for key in DESCRIPTION_FIELDS
    )
    return Lead(
        company=company.name,
        platform="oracle",
        external_id=job_id,
        title=title,
        url=(
            f"{base}/hcmUI/CandidateExperience/en/sites/{path_segment(site)}"
            f"/job/{path_segment(job_id)}"
        ),
        locations=[place for place in locations if place],
        country=clean(requisition.get("PrimaryLocationCountry")),
        posted_on=to_iso_date(requisition.get("PostedDate")),
        department=clean(requisition.get("JobFamily")) or clean(requisition.get("Department")),
        term=clean(requisition.get("JobSchedule")),
        description=description.strip(),
    )
