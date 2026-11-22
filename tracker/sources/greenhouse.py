"""Greenhouse public job board API. One request returns the whole board."""

from __future__ import annotations

import html

from tracker.config import Company
from tracker.http import Client
from tracker.models import Lead
from tracker.sources._common import mapping, param, path_segment, records
from tracker.text import clean, html_to_text, to_iso_date

BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs"


def fetch(client: Client, company: Company) -> list[Lead]:
    board = path_segment(param(company, "board"))
    payload = client.get_json(BOARD_URL.format(board=board), params={"content": "true"})
    leads = []
    for job in records(payload, "jobs"):
        title = clean(job.get("title"))
        url = clean(job.get("absolute_url"))
        if not title or not url:
            continue
        location = clean(mapping(job.get("location")).get("name"))
        departments = [clean(mapping(item).get("name")) for item in job.get("departments") or []]
        leads.append(
            Lead(
                company=company.name,
                platform="greenhouse",
                external_id=clean(job.get("id")),
                title=title,
                url=url,
                locations=[location] if location else [],
                posted_on=to_iso_date(job.get("first_published")),
                department=", ".join(name for name in departments if name),
                # Greenhouse returns the description as escaped HTML.
                description=html_to_text(html.unescape(str(job.get("content") or ""))),
            )
        )
    return leads
