"""The refresh run: read every company, screen, reconcile, validate, write."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tracker import catalog, render
from tracker.config import ROOT, Settings
from tracker.http import Client, SourceError
from tracker.reconcile import CompanyRun, new_record, reconcile
from tracker.screen import screen
from tracker.sources import fetch_leads

# A company that suddenly returns nothing while this many listings are open is
# more likely a changed or broken API than a mass closure. Treat it as failed.
EMPTY_READ_GUARD = 3


@dataclass(frozen=True)
class Paths:
    listings: Path
    status: Path
    readme: Path
    closed: Path
    screening_log: Path

    @classmethod
    def default(cls, root: Path = ROOT) -> Paths:
        return cls(
            listings=root / "data" / "listings.json",
            status=root / "data" / "status.json",
            readme=root / "README.md",
            closed=root / "CLOSED.md",
            screening_log=root / "logs" / "screening.json",
        )


@dataclass
class RefreshResult:
    runs: list[CompanyRun]
    rejected: list[dict]
    written: bool

    @property
    def all_failed(self) -> bool:
        return bool(self.runs) and not any(run.ok for run in self.runs)


def read_company(client: Client, company, settings: Settings, today: str, open_count: int):
    """Return (CompanyRun, rejected-lead log entries) for one company."""
    if company.link_only:
        return CompanyRun(company.name, ok=True), []
    try:
        leads = fetch_leads(client, company)
    except (SourceError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return CompanyRun(company.name, ok=False, error=str(exc)[:300]), []
    if not leads and open_count >= EMPTY_READ_GUARD:
        error = f"returned no postings while {open_count} listings are open"
        return CompanyRun(company.name, ok=False, error=error), []
    run = CompanyRun(company.name, ok=True, fetched=len(leads))
    rejected = []
    for lead in leads:
        verdict = screen(lead, year=settings.year)
        if verdict.accepted:
            run.accepted.append(new_record(lead, verdict, season=settings.season, today=today))
        else:
            rejected.append(
                {
                    "company": lead.company,
                    "title": lead.title,
                    "locations": lead.locations,
                    "url": lead.url,
                    "reasons": list(verdict.reasons),
                }
            )
    return run, rejected


def refresh(
    settings: Settings, client: Client, paths: Paths, *, today: str, dry_run: bool = False
) -> RefreshResult:
    existing = catalog.load(paths.listings)
    catalog.check(existing)
    runs: list[CompanyRun] = []
    rejected: list[dict] = []
    for company in settings.companies:
        open_count = sum(
            1 for row in existing if row["company"] == company.name and row["status"] == "open"
        )
        run, company_rejected = read_company(client, company, settings, today, open_count)
        runs.append(run)
        rejected.extend(company_rejected)
    result = RefreshResult(runs=runs, rejected=rejected, written=False)
    if dry_run or result.all_failed:
        return result
    listings = reconcile(existing, runs, today)
    catalog.check(listings)
    status = status_document(settings, runs, today)
    files = outputs(paths, settings, listings, status)
    files[paths.screening_log] = json.dumps(rejected, indent=2, ensure_ascii=False) + "\n"
    catalog.write_all(files)
    result.written = True
    return result


def status_document(settings: Settings, runs: list[CompanyRun], today: str) -> dict:
    return {
        "last_run": today,
        "season": settings.season,
        "companies": {
            run.company: {
                "ok": run.ok,
                "fetched": run.fetched,
                "accepted": len(run.accepted),
                "error": run.error,
            }
            for run in sorted(runs, key=lambda item: item.company.lower())
        },
    }


def outputs(paths: Paths, settings: Settings, listings: list[dict], status: dict) -> dict:
    """The catalog files and the Markdown views generated from them."""
    readme = paths.readme.read_text(encoding="utf-8")
    block = render.listings_block(listings, status, settings)
    return {
        paths.listings: catalog.dumps(listings),
        paths.status: json.dumps(status, indent=2, ensure_ascii=False) + "\n",
        paths.readme: render.splice(readme, block),
        paths.closed: render.closed_page(listings),
    }


def load_status(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
