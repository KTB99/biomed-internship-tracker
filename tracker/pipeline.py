"""The refresh run: read every company, screen, reconcile, validate, write."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from tracker import catalog, render
from tracker.config import ROOT, Settings
from tracker.http import Client, SourceError
from tracker.ids import listing_id
from tracker.reconcile import CompanyRun, new_record, reconcile
from tracker.screen import screen
from tracker.sources import fetch_leads
from tracker.text import clean

# A company that suddenly returns nothing while this many listings are open, or
# whose open listings screening suddenly rejects all at once, is more likely a
# changed or broken API than a mass closure. Treat the read as failed.
EMPTY_READ_GUARD = 3

# A company whose last good read fetched at least this many postings (eligible
# or not) and that now returns nothing most likely has a broken reader: most
# companies have few open listings, so EMPTY_READ_GUARD alone misses them. Treat
# the read as failed until the reader is fixed or the baseline is reset
# (`python -m tracker reset-baseline <company>`).
EMPTY_FETCH_GUARD = 10


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


@dataclass(frozen=True)
class Baseline:
    """A company's last good read that fetched something: how many, and when.

    Stored in data/status.json as `last_good_fetched` and `last_good_date`.
    """

    fetched: int
    date: str


@dataclass
class RefreshResult:
    runs: list[CompanyRun]
    rejected: list[dict]
    written: bool

    @property
    def all_failed(self) -> bool:
        return bool(self.runs) and not any(run.ok for run in self.runs)


def read_company(
    client: Client,
    company,
    settings: Settings,
    today: str,
    open_listings: list[dict],
    baseline: Baseline | None,
):
    """Return (CompanyRun, rejected-lead log entries) for one company.

    `open_listings` are the company's open catalog rows before this run, and
    `baseline` is its last good read that fetched something (None if none).
    """
    if company.link_only:
        return CompanyRun(company.name, ok=True), []
    try:
        leads = fetch_leads(client, company)
    except (SourceError, ValueError, KeyError, TypeError, AttributeError) as exc:
        return _failed(company, str(exc)), []
    if not leads and len(open_listings) >= EMPTY_READ_GUARD:
        return _failed(
            company, f"returned no postings while {len(open_listings)} listings are open"
        ), []
    if not leads and baseline and baseline.fetched >= EMPTY_FETCH_GUARD:
        return _failed(company, f"returned no postings after {baseline.fetched} last time"), []
    run = CompanyRun(company.name, ok=True, fetched=len(leads))
    rejected = []
    for lead in leads:
        verdict = screen(lead, year=settings.year)
        if verdict.accepted:
            run.accepted.append(new_record(lead, verdict, season=settings.season, today=today))
        else:
            run.rejected_ids.add(
                listing_id(lead.company, lead.platform, lead.external_id, lead.url)
            )
            rejected.append(
                {
                    "company": lead.company,
                    "title": lead.title,
                    "locations": lead.locations,
                    "url": lead.url,
                    "reasons": list(verdict.reasons),
                }
            )
    # A reader can return one posting twice; if any copy passes screening, keep it.
    run.rejected_ids -= {record["id"] for record in run.accepted}
    in_season = {row["id"] for row in open_listings if row["season"] == settings.season}
    if len(in_season) >= EMPTY_READ_GUARD and in_season <= run.rejected_ids:
        error = (
            f"screening rejected all {len(in_season)} open listings; treating as a changed response"
        )
        return _failed(company, error, fetched=len(leads)), rejected
    return run, rejected


def _failed(company, error: str, *, fetched: int = 0) -> CompanyRun:
    # Error text can come from a job board. One line of it per company keeps the
    # refresh output's "[failed] <company>: <error>" lines unforgeable.
    return CompanyRun(company.name, ok=False, fetched=fetched, error=clean(error)[:300])


def refresh(
    settings: Settings, client: Client, paths: Paths, *, today: str, dry_run: bool = False
) -> RefreshResult:
    existing = catalog.load(paths.listings)
    catalog.check(existing)
    previous = load_status(paths.status).get("companies", {})
    runs: list[CompanyRun] = []
    rejected: list[dict] = []
    for company in settings.companies:
        open_listings = [
            row for row in existing if row["company"] == company.name and row["status"] == "open"
        ]
        run, company_rejected = read_company(
            client, company, settings, today, open_listings, _baseline(previous.get(company.name))
        )
        runs.append(run)
        rejected.extend(company_rejected)
    result = RefreshResult(runs=runs, rejected=rejected, written=False)
    if dry_run or result.all_failed:
        return result
    listings = reconcile(existing, runs, today, season=settings.season)
    catalog.check(listings)
    status = status_document(settings, runs, today, previous)
    files = outputs(paths, settings, listings, status)
    files[paths.screening_log] = json.dumps(rejected, indent=2, ensure_ascii=False) + "\n"
    catalog.write_all(files)
    result.written = True
    return result


def status_document(settings: Settings, runs: list[CompanyRun], today: str, previous: dict) -> dict:
    """The status document for this run.

    `previous` is the last status document's "companies" map. A company's
    baseline moves only on a good read that fetched something; otherwise it is
    carried over.
    """
    companies = {}
    for run in sorted(runs, key=lambda item: item.company.lower()):
        if run.ok and run.fetched > 0:
            baseline = Baseline(fetched=run.fetched, date=today)
        else:
            baseline = _baseline(previous.get(run.company))
        companies[run.company] = {
            "ok": run.ok,
            "fetched": run.fetched,
            "accepted": len(run.accepted),
            "error": run.error,
            **_baseline_fields(baseline),
        }
    return {"last_run": today, "season": settings.season, "companies": companies}


def reset_baseline(path: Path, company: str) -> bool:
    """Forget a company's baseline in the status file, so its next empty read
    is accepted. False if the status file has no entry for that company."""
    status = load_status(path)
    entry = status.get("companies", {}).get(company)
    if entry is None:
        return False
    entry.update(_baseline_fields(None))
    catalog.write_all({path: dump_status(status)})
    return True


def _baseline(entry: dict | None) -> Baseline | None:
    """A status entry's baseline. Entries written before baselines have none."""
    fetched = (entry or {}).get("last_good_fetched")
    return None if fetched is None else Baseline(fetched=fetched, date=entry["last_good_date"])


def _baseline_fields(baseline: Baseline | None) -> dict:
    return {
        "last_good_fetched": baseline.fetched if baseline else None,
        "last_good_date": baseline.date if baseline else None,
    }


def outputs(paths: Paths, settings: Settings, listings: list[dict], status: dict) -> dict:
    """The catalog files and the Markdown views generated from them."""
    readme = paths.readme.read_text(encoding="utf-8")
    block = render.listings_block(listings, status, settings)
    return {
        paths.listings: catalog.dumps(listings),
        paths.status: dump_status(status),
        paths.readme: render.splice(readme, block),
        paths.closed: render.closed_page(listings),
    }


def dump_status(status: dict) -> str:
    return json.dumps(status, indent=2, ensure_ascii=False) + "\n"


def load_status(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
