"""SAP SuccessFactors career sites (jobs2web): the /search/ listing page."""

from __future__ import annotations

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import job_id_from_url, origin, search_terms
from tracker.sources._html import has_class, parse_cards
from tracker.text import clean

SEARCH_PATH = "/search/"
MAX_PAGES = 20


def _is_job_link(tag: str, attrs: dict) -> bool:
    return has_class(attrs, "jobTitle-link")


def _is_location(tag: str, attrs: dict) -> bool:
    # Table layouts use span.jobLocation; tile layouts use a "...-section-location-value" div.
    return has_class(attrs, "jobLocation") or attrs.get("id", "").endswith(
        "-section-location-value"
    )


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        term_ids: set[str] = set()
        start_row = 0
        for _ in range(MAX_PAGES):
            params = {"q": term}
            if start_row:
                params["startrow"] = str(start_row)
            html = client.get_text(base + SEARCH_PATH, params=params)
            cards = parse_cards(html, base + "/", _is_job_link, _is_location)
            new = 0
            for card in cards:
                job_id = job_id_from_url(card.url)
                if job_id not in term_ids:
                    term_ids.add(job_id)
                    new += 1
                    leads.setdefault(
                        job_id,
                        Lead(
                            company=company.name,
                            platform="jobs2web",
                            external_id=job_id,
                            title=card.title,
                            url=card.url,
                            locations=[clean(card.location)] if card.location else [],
                        ),
                    )
            # Page size varies by site, so advance by what this page held.
            start_row += len(cards)
            if not new:
                break
    return list(leads.values())
