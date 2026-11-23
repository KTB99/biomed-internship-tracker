"""Merge one refresh run into the catalog.

Rules:
- A listing seen again is refreshed and its miss count reset; a listing that
  closed because it went missing reopens. Manually closed listings stay closed.
- An open listing absent from a successful read of its company gains one miss
  per calendar day. Two misses close it.
- A listing of the current season whose posting a successful read still
  returns, but which screening now rejects, is removed from the catalog in that
  run: no miss, no close. Manually closed listings and listings from other
  seasons are never removed.
- Companies whose read failed are left exactly as they were, apart from the
  deadline rule below.

Submitted listings (`platform = "submitted"`, added by a maintainer rather than
read from a job board) follow the same rules, plus:
- While their company doesn't read a job board (`careers_page` or `link`), they
  never gain a miss. Once it reads one, they gain misses like any other listing.
- On every refresh, an open one whose `closes_on` is before today closes with
  reason `deadline`, even when that company's read failed, except a run where
  every read fails writes nothing (`pipeline.refresh`), so its deadline closes
  wait for the next run that writes.
- An accepted record of a successful read whose Apply URL matches a submitted
  listing of the same company (same `apply_url_key`) replaces it in that run:
  the submitted row is removed and the read row keeps its `first_seen`, and its
  manual close if it had one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from tracker.ids import listing_id
from tracker.models import Lead
from tracker.places import is_us_location, tidy_place
from tracker.screen import Verdict

MISSES_TO_CLOSE = 2
SUBMITTED = "submitted"
REFRESHED_FIELDS = ("title", "location", "url", "family", "season")
MAX_LOCATIONS_SHOWN = 3


@dataclass
class CompanyRun:
    company: str
    ok: bool
    accepted: list[dict] = field(default_factory=list)
    fetched: int = 0
    rejected_ids: set[str] = field(default_factory=set)
    error: str | None = None
    # False for a company that doesn't read a job board (careers_page or link):
    # its submitted listings can never appear in a read, so they gain no misses.
    reads_job_board: bool = True


def new_record(lead: Lead, verdict: Verdict, *, season: str, today: str) -> dict:
    return {
        "id": listing_id(lead.company, lead.platform, lead.external_id, lead.url),
        "company": lead.company,
        "title": lead.title[:300],
        "location": display_location(lead.locations),
        "url": lead.url,
        "platform": lead.platform,
        "external_id": lead.external_id[:200],
        "family": verdict.family,
        "season": season,
        "posted_on": lead.posted_on,
        "first_seen": today,
        "last_seen": today,
        "status": "open",
        "misses": 0,
        "last_missed": None,
        "closed_on": None,
        "close_reason": None,
    }


def display_location(locations: list[str]) -> str:
    tidied = (tidy_place(place) for place in locations)
    unique = list(dict.fromkeys(place for place in tidied if place))
    ordered = sorted(unique, key=lambda place: not is_us_location(place))  # stable: US first
    shown = "; ".join(ordered[:MAX_LOCATIONS_SHOWN])
    if len(ordered) > MAX_LOCATIONS_SHOWN:
        shown += f" (+{len(ordered) - MAX_LOCATIONS_SHOWN} more)"
    return shown[:300]


def reconcile(
    existing: list[dict], runs: list[CompanyRun], today: str, *, season: str
) -> list[dict]:
    by_id = {row["id"]: dict(row) for row in existing}
    for row in by_id.values():
        if row["status"] == "open" and (row.get("closes_on") or today) < today:
            row.update(status="closed", closed_on=today, close_reason="deadline")
    for run in runs:
        if not run.ok:
            continue
        for listing in list(by_id):
            row = by_id[listing]
            if (
                row["company"] == run.company
                and row["season"] == season
                and listing in run.rejected_ids
                and row["close_reason"] != "manual"
            ):
                del by_id[listing]
        seen: set[str] = set()
        for record in run.accepted:
            seen.add(record["id"])
            record, absorbed = _absorb_submitted(by_id, run.company, record)
            previous = by_id.get(record["id"])
            if previous is None:
                by_id[record["id"]] = dict(record)
                continue
            if previous["status"] == "closed" and previous["close_reason"] == "manual":
                continue
            updated = dict(previous)
            if absorbed:
                updated["first_seen"] = min(previous["first_seen"], record["first_seen"])
            updated.update({key: record[key] for key in REFRESHED_FIELDS})
            updated["posted_on"] = record["posted_on"] or previous["posted_on"]
            updated.update(
                last_seen=today,
                status="open",
                misses=0,
                last_missed=None,
                closed_on=None,
                close_reason=None,
            )
            by_id[record["id"]] = updated
        for row in by_id.values():
            if row["company"] != run.company or row["status"] != "open" or row["id"] in seen:
                continue
            if row["last_missed"] == today:
                continue
            if row["platform"] == SUBMITTED and not run.reads_job_board:
                continue
            row["misses"] += 1
            row["last_missed"] = today
            if row["misses"] >= MISSES_TO_CLOSE:
                row.update(status="closed", closed_on=today, close_reason="missing")
    return list(by_id.values())


def apply_url_key(url: str) -> tuple[str, str, str]:
    """What two Apply URLs must share to be the same posting: scheme, lowercased
    host and path, ignoring userinfo, port, the query, fragment, a trailing `/`
    and a trailing `/apply`."""
    parts = urlsplit(url.strip())
    path = parts.path.removesuffix("/").removesuffix("/apply")
    return parts.scheme.lower(), parts.hostname or "", path


def same_posting(row: dict, company: str, key: tuple[str, str, str]) -> bool:
    """True when catalog row `row` is a posting of `company` whose Apply URL has
    `apply_url_key` `key`."""
    return row["company"] == company and apply_url_key(row["url"]) == key


def _absorb_submitted(by_id: dict[str, dict], company: str, record: dict) -> tuple[dict, bool]:
    """Remove the company's submitted listings with the record's Apply URL.

    Returns the record carrying their earliest `first_seen` and any manual
    close, and whether any were removed."""
    key = apply_url_key(record["url"])
    matches = [
        row
        for row in by_id.values()
        if row["platform"] == SUBMITTED and same_posting(row, company, key)
    ]
    if not matches:
        return record, False
    for row in matches:
        del by_id[row["id"]]
    merged = {**record, "first_seen": min(row["first_seen"] for row in matches)}
    manual = [row for row in matches if row["close_reason"] == "manual"]
    if manual:
        merged.update(status="closed", closed_on=manual[0]["closed_on"], close_reason="manual")
    return merged, True


def close_manually(listings: list[dict], listing_id_: str, today: str) -> list[dict]:
    updated = []
    found = False
    for row in listings:
        if row["id"] == listing_id_:
            found = True
            row = {**row, "status": "closed", "closed_on": today, "close_reason": "manual"}
        updated.append(row)
    if not found:
        raise KeyError(listing_id_)
    return updated
