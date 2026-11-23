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
- Companies whose read failed are left exactly as they were.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tracker.ids import listing_id
from tracker.models import Lead
from tracker.places import is_us_location, tidy_place
from tracker.screen import Verdict

MISSES_TO_CLOSE = 2
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
            previous = by_id.get(record["id"])
            if previous is None:
                by_id[record["id"]] = dict(record)
                continue
            if previous["status"] == "closed" and previous["close_reason"] == "manual":
                continue
            updated = dict(previous)
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
            row["misses"] += 1
            row["last_missed"] = today
            if row["misses"] >= MISSES_TO_CLOSE:
                row.update(status="closed", closed_on=today, close_reason="missing")
    return list(by_id.values())


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
