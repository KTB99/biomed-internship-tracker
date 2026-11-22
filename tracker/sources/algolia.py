"""Career sites whose job search runs on an Algolia index.

These sites embed a search-only Algolia key in their public pages. It is a
per-site parameter in companies.toml, so this reader is only enabled for a
company once a maintainer has added those parameters.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import as_int, mapping, param, records, search_terms
from tracker.text import clean, to_iso_date

PAGE_SIZE = 50
MAX_PAGES = 20
_APP_ID = re.compile(r"^[A-Z0-9]{6,20}$")


def fetch(client: Client, company: Company) -> list[Lead]:
    app_id = param(company, "app_id")
    if not _APP_ID.match(app_id):
        raise ValueError(f"{company.name}: app_id looks wrong")
    index = param(company, "index")
    headers = {
        "X-Algolia-Application-Id": app_id,
        "X-Algolia-API-Key": param(company, "search_key"),
    }
    referer = str(company.params.get("referer", ""))
    if referer.startswith("https://"):
        headers["Referer"] = referer
    url = f"https://{app_id.lower()}-dsn.algolia.net/1/indexes/*/queries"
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        for page in range(MAX_PAGES):
            query = urlencode({"query": term, "hitsPerPage": PAGE_SIZE, "page": page})
            payload = client.post_json(
                url, {"requests": [{"indexName": index, "params": query}]}, headers=headers
            )
            results = records(payload, "results")
            result = results[0] if results else {}
            for hit in records(result, "hits"):
                lead = _lead(company, hit)
                if lead:
                    leads.setdefault(lead.external_id, lead)
            pages = as_int(result.get("nbPages")) or 0
            if page + 1 >= pages:
                break
    return list(leads.values())


def _lead(company: Company, hit: dict) -> Lead | None:
    title = clean(hit.get("JobPostingTitle")) or clean(hit.get("title"))
    url = clean(hit.get("ApplyUrl")) or clean(hit.get("applyUrl"))
    job_id = clean(hit.get("objectID")) or clean(hit.get("JobRequisition")) or url
    if not title or not url.startswith("https://"):
        return None
    location = clean(hit.get("Location")) or clean(hit.get("PrimaryJobPostingLocation"))
    return Lead(
        company=company.name,
        platform="algolia",
        external_id=job_id,
        title=title,
        url=url,
        locations=[location] if location else [],
        country=clean(hit.get("Country")),
        posted_on=to_iso_date(hit.get("PostedDate") or hit.get("postedDate")),
        department=clean(hit.get("Category")),
        term=clean(hit.get("EmployeeType")),
        description=clean(mapping(hit).get("JobDescription")),
    )
