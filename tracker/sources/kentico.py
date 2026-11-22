"""Kentico-built career sites whose job search returns an HTML results table."""

from __future__ import annotations

import re

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import origin, param, search_terms
from tracker.sources._html import parse_table

SEARCH_PATH = "/api/jobs/search"
MAX_PAGES = 20
_LAST_PAGE = re.compile(r'data-page="(\d+)"')


def fetch(client: Client, company: Company) -> list[Lead]:
    base = origin(company)
    page_url = param(company, "page_url")
    leads: dict[str, Lead] = {}
    for term in search_terms(company):
        term_ids: set[str] = set()
        for page in range(1, MAX_PAGES + 1):
            html = client.get_text(
                base + SEARCH_PATH,
                params={"pageUrl": page_url, "page": page, "keyword": term},
                headers={"Referer": base + page_url},
            )
            new = 0
            for row in parse_table(html, base + "/", "job-search-table"):
                title = row.get("title")
                if title is None or not title.text or not title.href.startswith("https://"):
                    continue
                job_id = row["job id"].text if "job id" in row else title.href
                if job_id in term_ids:
                    continue
                term_ids.add(job_id)
                new += 1
                location = row["location"].text if "location" in row else ""
                leads.setdefault(
                    job_id,
                    Lead(
                        company=company.name,
                        platform="kentico",
                        external_id=job_id,
                        title=title.text,
                        url=title.href,
                        locations=[location] if location else [],
                        department=row["category"].text if "category" in row else "",
                    ),
                )
            pages = [int(found) for found in _LAST_PAGE.findall(html)]
            if not new or page >= max(pages, default=1):
                break
    return list(leads.values())
