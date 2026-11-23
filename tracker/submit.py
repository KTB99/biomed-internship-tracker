"""Turn an "Add internship" issue into a submitted listing.

The issue body is what GitHub renders from `.github/ISSUE_TEMPLATE/add-internship.yml`:
each field is a `### <Label>` heading followed by its value, and `_No response_`
stands for an empty field. Everything in it is untrusted.
"""

from __future__ import annotations

import re
from datetime import date

from tracker.config import Settings
from tracker.models import Lead
from tracker.reconcile import SUBMITTED, apply_url_key, new_record, same_posting
from tracker.screen import screen

NO_RESPONSE = "_No response_"
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class Refused(ValueError):
    """The submission can't be accepted; the message says why."""


def parse_form(body: str) -> dict[str, str]:
    """The form's fields by label, each value stripped, `_No response_` as ""."""
    fields: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in body.splitlines():
        if line.startswith("### "):
            current = fields.setdefault(line[4:].strip(), [])
        elif current is not None:
            current.append(line)
    values = {label: "\n".join(lines).strip() for label, lines in fields.items()}
    return {label: "" if value == NO_RESPONSE else value for label, value in values.items()}


def submitted_listing(
    fields: dict[str, str], listings: list[dict], settings: Settings, *, issue: int, today: str
) -> dict:
    """The new listing for an issue's form fields; raises Refused, saying why, if it can't be."""
    name = fields.get("Company", "")
    company = next((c for c in settings.companies if c.name == name), None)
    if company is None or not company.submit_hosts:
        raise Refused(f"company {name!r} does not accept submissions")
    url = fields.get("Apply URL", "")
    if not company.allows_submission_url(url):
        raise Refused(f"Apply URL must be https on one of: {', '.join(company.submit_hosts)}")
    for label in ("Title", "Location"):
        if not fields.get(label):
            raise Refused(f"{label} is empty")
    closes_on = _closing_date(fields.get("Closes on", ""), today)
    lead = Lead(
        company=company.name,
        platform=SUBMITTED,
        external_id=url,
        title=fields.get("Title", ""),
        url=url,
        locations=[fields.get("Location", "")],
        term=fields.get("Term", ""),
    )
    verdict = screen(lead, year=settings.year)
    if not verdict.accepted:
        raise Refused(f"screening rejected it: {'; '.join(verdict.reasons)}")
    record = new_record(lead, verdict, season=settings.season, today=today)
    if any(row["id"] == record["id"] for row in listings):
        raise Refused(f"listing {record['id']} already exists")
    # The same match reconcile uses to let a read listing replace a submitted one.
    key = apply_url_key(url)
    for row in listings:
        if row["status"] == "open" and same_posting(row, company.name, key):
            raise Refused(f"open listing {row['id']} already has this Apply URL")
    record["closes_on"] = closes_on
    record["submitted_in"] = issue
    return record


def _closing_date(value: str, today: str) -> str | None:
    if not value:
        return None
    try:
        # fromisoformat also takes forms like 20270115; the catalog stores only YYYY-MM-DD.
        valid = bool(ISO_DATE.fullmatch(value)) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        valid = False
    if not valid:
        raise Refused(f"Closes on must be a date written YYYY-MM-DD, not {value!r}")
    if value < today:
        raise Refused(f"Closes on {value} is before today ({today})")
    return value
