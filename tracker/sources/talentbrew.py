"""TalentBrew (Radancy) career sites: the search-results endpoint returns listing HTML in JSON."""

from __future__ import annotations

import re

from tracker.config import Company
from tracker.http import Client, SourceError
from tracker.models import Lead
from tracker.sources._common import mapping, origin, search_terms
from tracker.sources._html import has_class, parse_cards
from tracker.text import clean

RESULTS_PATH = "/en/search-jobs/results"
PAGE_SIZE = 15
MAX_PAGES = 20
_TOTAL_PAGES = re.compile(r'data-total-pages="(\d+)"')
_LOCATION_LABEL = re.compile(r"^location:\s*", re.IGNORECASE)


def _is_job_link(tag: str, attrs: dict) -> bool:
    return "/job/" in attrs.get("href", "") and bool(attrs.get("data-job-id"))


def _is_location(tag: str, attrs: dict) -> bool:
    return has_class(attrs, "job-location") or has_class(attrs, "location")


def _is_title(tag: str, attrs: dict) -> bool:
    # Some sites put the location, category or posted date inside the job link
    # too; the heading holds just the title.
    return tag in ("h2", "h3")


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    module = str(company.params.get("results_module", "Search Results"))
    results_path = str(company.params.get("results_path", RESULTS_PATH))
    if not results_path.startswith("/"):
        raise ValueError(f"{company.name}: results_path must start with /")
    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "Referer": base + results_path.removesuffix("/results"),
    }
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        term_ids: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            payload = client.get_json(
                base + results_path,
                params={
                    "CurrentPage": page,
                    "RecordsPerPage": PAGE_SIZE,
                    "Keywords": term,
                    "SearchType": "1",
                    "SortCriteria": "0",
                    "SortDirection": "0",
                    "SearchResultsModuleName": module,
                    "ResultsType": "0",
                },
                headers=headers,
            )
            html = mapping(payload).get("results")
            if not isinstance(html, str):
                raise SourceError("unexpected response shape: no results HTML")
            new = 0
            for card in parse_cards(html, base + "/", _is_job_link, _is_location, _is_title):
                job_id = card.job_id or card.url
                if job_id not in term_ids:
                    term_ids.add(job_id)
                    new += 1
                    leads.setdefault(
                        job_id,
                        Lead(
                            company=company.name,
                            platform="talentbrew",
                            external_id=job_id,
                            title=card.title,
                            url=card.url,
                            locations=[_place(card.location)] if card.location else [],
                        ),
                    )
            pages = _TOTAL_PAGES.search(html)
            if not new or (pages and page >= int(pages.group(1))):
                break
    return list(leads.values())


def _place(text: str) -> str:
    """The location text without a leading "Location:" label."""
    return _LOCATION_LABEL.sub("", clean(text))
