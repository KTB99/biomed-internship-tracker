"""Command line: python -m tracker <command>."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from tracker import catalog
from tracker.config import load_settings
from tracker.http import Client
from tracker.pipeline import Paths, load_status, outputs, refresh, reset_baseline
from tracker.reconcile import close_manually


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tracker", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    run = commands.add_parser("refresh", help="read every company and update the catalog")
    run.add_argument("--today", type=_iso_date, default=date.today().isoformat())
    run.add_argument("--dry-run", action="store_true", help="read and screen, write nothing")

    commands.add_parser("validate", help="check data/listings.json against the schema")

    draw = commands.add_parser("render", help="regenerate README.md and CLOSED.md")
    draw.add_argument("--check", action="store_true", help="fail if the views are stale")

    shut = commands.add_parser("close", help="close a listing by hand")
    shut.add_argument("listing_id")
    shut.add_argument("--today", type=_iso_date, default=date.today().isoformat())

    reset = commands.add_parser(
        "reset-baseline",
        help="forget a company's last good fetch count, so an empty read is accepted",
    )
    reset.add_argument("company", help="the company's name as in companies.toml")

    args = parser.parse_args(argv)
    settings = load_settings()
    paths = Paths.default()
    handlers = {
        "refresh": _refresh,
        "validate": _validate,
        "render": _render,
        "close": _close,
        "reset-baseline": _reset_baseline,
    }
    return handlers[args.command](args, settings, paths)


def _refresh(args, settings, paths) -> int:
    result = refresh(settings, Client(), paths, today=args.today, dry_run=args.dry_run)
    for run in result.runs:
        if run.ok:
            print(f"[ok]     {run.company}: {run.fetched} fetched, {len(run.accepted)} accepted")
        else:
            print(f"[failed] {run.company}: {run.error}")
    print(f"{len(result.rejected)} postings rejected by screening")
    if result.all_failed:
        print("Every company failed; nothing was written.")
        return 1
    if result.written:
        print(f"Wrote {paths.listings.name}, {paths.status.name}, README.md, CLOSED.md")
    return 0


def _validate(args, settings, paths) -> int:
    listings = catalog.load(paths.listings)
    found = catalog.problems(listings)
    for problem in found:
        print(problem)
    print(f"{len(listings)} listings, {len(found)} problems")
    return 1 if found else 0


def _render(args, settings, paths) -> int:
    listings = catalog.load(paths.listings)
    catalog.check(listings)
    files = outputs(paths, settings, listings, load_status(paths.status))
    views = {path: text for path, text in files.items() if path in (paths.readme, paths.closed)}
    stale = [path for path, text in views.items() if _read(path) != text]
    if args.check:
        for path in stale:
            print(f"{path.name} is out of date; run `python -m tracker render`")
        return 1 if stale else 0
    catalog.write_all(views)
    print(f"Rendered {', '.join(path.name for path in views)}")
    return 0


def _close(args, settings, paths) -> int:
    listings = catalog.load(paths.listings)
    try:
        listings = close_manually(listings, args.listing_id, args.today)
    except KeyError:
        print(f"No listing with id {args.listing_id}")
        return 1
    catalog.check(listings)
    files = outputs(paths, settings, listings, load_status(paths.status))
    catalog.write_all({path: text for path, text in files.items() if path != paths.status})
    print(f"Closed {args.listing_id}")
    return 0


def _reset_baseline(args, settings, paths) -> int:
    if not reset_baseline(paths.status, args.company):
        print(f"No company named {args.company!r} in {paths.status.name}")
        return 1
    print(f"Reset the baseline of {args.company}; its next empty read will be accepted")
    return 0


def _read(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _iso_date(value: str) -> str:
    return date.fromisoformat(value).isoformat()
