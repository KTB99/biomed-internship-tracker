import json

import pytest
from conftest import FakeResponse, company, fake_client, settings
from test_reconcile import submitted

from tracker import catalog
from tracker.cli import main
from tracker.config import REGISTRY_PATH, load_settings
from tracker.pipeline import EMPTY_READ_GUARD, Paths, refresh
from tracker.reconcile import close_manually
from tracker.render import END_MARKER, START_MARKER

GOOD = company("Good Co", platform="greenhouse", board="good")
BROKEN = company("Broken Co", platform="lever", site="broken")
README = f"# Test\n\n{START_MARKER}\n{END_MARKER}\n\nFooter.\n"


def greenhouse_job(job_id, title, location="Irvine, CA"):
    return {
        "id": job_id,
        "title": title,
        "absolute_url": f"https://job-boards.greenhouse.io/good/jobs/{job_id}",
        "location": {"name": location},
    }


def handler(jobs):
    def respond(method, url, kwargs):
        if "greenhouse" in url:
            return FakeResponse({"jobs": jobs})
        return FakeResponse(status=403, body="")

    return respond


def paths(tmp_path) -> Paths:
    (tmp_path / "README.md").write_text(README, encoding="utf-8")
    return Paths(
        listings=tmp_path / "data" / "listings.json",
        status=tmp_path / "data" / "status.json",
        readme=tmp_path / "README.md",
        closed=tmp_path / "CLOSED.md",
        screening_log=tmp_path / "logs" / "screening.json",
    )


def test_refresh_writes_catalog_views_and_log(tmp_path):
    jobs = [greenhouse_job(1, "Software Engineering Intern"), greenhouse_job(2, "Sales Intern")]
    client, _ = fake_client(handler(jobs))
    files = paths(tmp_path)
    result = refresh(settings(GOOD, BROKEN), client, files, today="2026-11-01")

    assert result.written
    listings = json.loads(files.listings.read_text())
    assert [row["title"] for row in listings] == ["Software Engineering Intern"]
    status = json.loads(files.status.read_text())
    assert status["companies"]["Good Co"] == {
        "ok": True,
        "fetched": 2,
        "accepted": 1,
        "error": None,
        "last_good_fetched": 2,
        "last_good_date": "2026-11-01",
    }
    assert status["companies"]["Broken Co"]["ok"] is False
    assert "blocked" in status["companies"]["Broken Co"]["error"]
    readme = files.readme.read_text()
    assert "Software Engineering Intern" in readme and readme.endswith("Footer.\n")
    assert files.closed.read_text().startswith("# Closed listings")
    log = json.loads(files.screening_log.read_text())
    assert log[0]["title"] == "Sales Intern" and log[0]["reasons"] == ["non-STEM role"]


def test_refresh_tidies_an_existing_listings_location(tmp_path):
    messy = "New Kensington, Pennsylvania, United States, Pennsylvania, United States of America"
    files = paths(tmp_path)
    client, _ = fake_client(handler([greenhouse_job(1, "Software Engineering Intern", messy)]))
    refresh(settings(GOOD), client, files, today="2026-11-01")
    (row,) = json.loads(files.listings.read_text())
    files.listings.write_text(json.dumps([{**row, "location": messy}]))  # written before tidying

    refresh(settings(GOOD), client, files, today="2026-11-02")
    (row,) = json.loads(files.listings.read_text())
    assert row["location"] == "New Kensington, PA"
    assert row["first_seen"] == "2026-11-01"
    assert messy not in files.readme.read_text()


def test_failed_company_keeps_its_listings(tmp_path):
    files = paths(tmp_path)
    client, _ = fake_client(handler([greenhouse_job(1, "Software Engineering Intern")]))
    refresh(settings(GOOD), client, files, today="2026-11-01")

    def all_blocked(*args):
        return FakeResponse(status=403, body="")

    client, _ = fake_client(all_blocked)
    for day in ("2026-11-02", "2026-11-03"):
        result = refresh(settings(GOOD, BROKEN), client, files, today=day)
        assert result.all_failed and not result.written
    (row,) = json.loads(files.listings.read_text())
    assert (row["status"], row["misses"]) == ("open", 0)


def test_empty_read_with_many_open_listings_counts_as_failure(tmp_path):
    files = paths(tmp_path)
    jobs = [greenhouse_job(n, f"Software Engineering Intern {n}") for n in range(EMPTY_READ_GUARD)]
    client, _ = fake_client(handler(jobs))
    refresh(settings(GOOD), client, files, today="2026-11-01")

    client, _ = fake_client(handler([]))
    result = refresh(settings(GOOD), client, files, today="2026-11-02")
    assert result.all_failed
    assert all(row["misses"] == 0 for row in json.loads(files.listings.read_text()))


def test_dry_run_writes_nothing(tmp_path):
    files = paths(tmp_path)
    client, _ = fake_client(handler([greenhouse_job(1, "Software Engineering Intern")]))
    result = refresh(settings(GOOD), client, files, today="2026-11-01", dry_run=True)
    assert not result.written
    assert not files.listings.exists()
    assert files.readme.read_text() == README


def test_registry_loads():
    loaded = load_settings(REGISTRY_PATH)
    assert loaded.season.startswith("summer-")
    assert len(loaded.companies) >= 5


def test_registry_rejects_the_submitted_record_platform(tmp_path):
    registry = tmp_path / "companies.toml"
    registry.write_text(
        'season = "summer-2027"\n\n[[companies]]\nname = "Acme"\nplatform = "submitted"\n'
        'careers_url = "https://acme.example/careers"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unknown platform 'submitted'"):
        load_settings(registry)


def test_committed_catalog_is_valid_and_views_are_current():
    assert main(["validate"]) == 0
    assert main(["render", "--check"]) == 0


INELIGIBLE_TITLE = "Fall 2027 Software Engineering Intern"


def test_listing_screened_out_later_is_removed_in_the_same_run(tmp_path):
    files = paths(tmp_path)
    client, _ = fake_client(handler([greenhouse_job(1, "Software Engineering Intern")]))
    refresh(settings(GOOD), client, files, today="2026-11-01")
    closed_before = files.closed.read_text()

    client, _ = fake_client(handler([greenhouse_job(1, INELIGIBLE_TITLE)]))
    result = refresh(settings(GOOD), client, files, today="2026-11-02")

    assert result.written
    assert json.loads(files.listings.read_text()) == []
    assert "Software Engineering Intern" not in files.readme.read_text()
    assert files.closed.read_text() == closed_before
    (logged,) = json.loads(files.screening_log.read_text())
    assert logged["title"] == INELIGIBLE_TITLE
    assert logged["reasons"] == ["not a summer term"]


def test_manually_closed_listing_is_kept_when_screened_out(tmp_path):
    files = paths(tmp_path)
    client, _ = fake_client(handler([greenhouse_job(1, "Software Engineering Intern")]))
    refresh(settings(GOOD), client, files, today="2026-11-01")
    (row,) = catalog.load(files.listings)
    files.listings.write_text(
        catalog.dumps(close_manually([row], row["id"], "2026-11-01")), encoding="utf-8"
    )

    client, _ = fake_client(handler([greenhouse_job(1, INELIGIBLE_TITLE)]))
    refresh(settings(GOOD), client, files, today="2026-11-02")

    (kept,) = json.loads(files.listings.read_text())
    assert (kept["id"], kept["status"], kept["close_reason"]) == (row["id"], "closed", "manual")


def test_listing_absent_from_a_successful_read_still_closes_after_two_misses(tmp_path):
    files = paths(tmp_path)
    jobs = [greenhouse_job(1, "Software Engineering Intern"), greenhouse_job(2, "Data Intern")]
    client, _ = fake_client(handler(jobs))
    refresh(settings(GOOD), client, files, today="2026-11-01")

    client, _ = fake_client(handler([greenhouse_job(2, "Data Intern")]))
    for day in ("2026-11-02", "2026-11-03"):
        refresh(settings(GOOD), client, files, today=day)

    rows = {row["title"]: row for row in json.loads(files.listings.read_text())}
    gone = rows["Software Engineering Intern"]
    assert (gone["status"], gone["misses"], gone["close_reason"]) == ("closed", 2, "missing")
    assert "Software Engineering Intern" in files.closed.read_text()


def test_failed_company_read_removes_nothing(tmp_path):
    files = paths(tmp_path)
    other = company("Other Co", platform="greenhouse", board="other")
    client, _ = fake_client(handler([greenhouse_job(1, "Software Engineering Intern")]))
    refresh(settings(GOOD), client, files, today="2026-11-01")
    (before,) = catalog.load(files.listings)

    def good_down(method, url, kwargs):
        if "/boards/good/" in url:
            return FakeResponse(status=403, body="")
        return FakeResponse({"jobs": [greenhouse_job(9, INELIGIBLE_TITLE)]})

    client, _ = fake_client(good_down)
    result = refresh(settings(GOOD, other), client, files, today="2026-11-02")

    assert result.written
    assert json.loads(files.listings.read_text()) == [before]


def test_listing_closed_as_missing_that_returns_ineligible_is_removed(tmp_path):
    files = paths(tmp_path)
    jobs = [greenhouse_job(1, "Software Engineering Intern"), greenhouse_job(2, "Data Intern")]
    client, _ = fake_client(handler(jobs))
    refresh(settings(GOOD), client, files, today="2026-11-01")
    client, _ = fake_client(handler([greenhouse_job(2, "Data Intern")]))
    for day in ("2026-11-02", "2026-11-03"):
        refresh(settings(GOOD), client, files, today=day)
    assert "Software Engineering Intern" in files.closed.read_text()

    returned = [greenhouse_job(1, INELIGIBLE_TITLE), greenhouse_job(2, "Data Intern")]
    client, _ = fake_client(handler(returned))
    refresh(settings(GOOD), client, files, today="2026-11-04")

    assert [row["title"] for row in json.loads(files.listings.read_text())] == ["Data Intern"]
    assert "Software Engineering Intern" not in files.closed.read_text()


def test_id_returned_both_accepted_and_rejected_keeps_its_listing(tmp_path):
    files = paths(tmp_path)
    client, _ = fake_client(handler([greenhouse_job(1, "Software Engineering Intern")]))
    refresh(settings(GOOD), client, files, today="2026-11-01")

    duplicated = [
        greenhouse_job(1, "Software Engineering Intern"),
        greenhouse_job(1, INELIGIBLE_TITLE),
    ]
    client, _ = fake_client(handler(duplicated))
    refresh(settings(GOOD), client, files, today="2026-11-02")

    (row,) = json.loads(files.listings.read_text())
    assert (row["first_seen"], row["last_seen"]) == ("2026-11-01", "2026-11-02")


def test_season_change_keeps_the_previous_seasons_listings(tmp_path):
    files = paths(tmp_path)
    title = "Summer 2027 Software Engineering Intern"
    client, _ = fake_client(handler([greenhouse_job(1, title)]))
    refresh(settings(GOOD, season="summer-2027"), client, files, today="2026-11-01")

    client, _ = fake_client(handler([greenhouse_job(1, title)]))
    result = refresh(settings(GOOD, season="summer-2028"), client, files, today="2026-11-02")

    assert result.written
    (row,) = json.loads(files.listings.read_text())
    assert (row["title"], row["season"], row["first_seen"]) == (title, "summer-2027", "2026-11-01")


def test_screening_rejecting_every_open_listing_counts_as_failure(tmp_path):
    files = paths(tmp_path)
    jobs = [greenhouse_job(n, f"Software Engineering Intern {n}") for n in range(EMPTY_READ_GUARD)]
    client, _ = fake_client(handler(jobs))
    refresh(settings(GOOD), client, files, today="2026-11-01")
    before = files.listings.read_text()

    changed = [greenhouse_job(n, f"{INELIGIBLE_TITLE} {n}") for n in range(EMPTY_READ_GUARD)]
    client, _ = fake_client(handler(changed))
    result = refresh(settings(GOOD), client, files, today="2026-11-02")

    assert result.all_failed and not result.written
    (run,) = result.runs
    assert run.error == (
        f"screening rejected all {EMPTY_READ_GUARD} open listings; treating as a changed response"
    )
    assert files.listings.read_text() == before


STEADY = company("Steady Co", platform="greenhouse", board="steady")


def boards(**jobs_by_board):
    """Greenhouse answers per board; a board not named returns no jobs."""

    def respond(method, url, kwargs):
        for board, jobs in jobs_by_board.items():
            if f"/boards/{board}/" in url:
                return FakeResponse({"jobs": jobs})
        return FakeResponse({"jobs": []})

    return respond


def unscreened(count):
    """Postings that all fail screening: the read fetches them but accepts none."""
    return [greenhouse_job(n, f"Sales Intern {n}") for n in range(count)]


STEADY_JOBS = [greenhouse_job(100, "Software Engineering Intern")]


def read_days(files, *days):
    """Run one refresh per (date, Good Co's jobs) pair; Steady Co always reads fine."""
    for today, good_jobs in days:
        client, _ = fake_client(boards(good=good_jobs, steady=STEADY_JOBS))
        refresh(settings(GOOD, STEADY), client, files, today=today)
    return json.loads(files.status.read_text())["companies"]["Good Co"]


def failed_reads_cell(files) -> str:
    """The "Failed reads" cell of the README's stats row."""
    lines = files.readme.read_text().splitlines()
    header = next(n for n, line in enumerate(lines) if "Failed reads" in line)
    columns = [part.strip() for part in lines[header].split("|")]
    return [part.strip() for part in lines[header + 2].split("|")][columns.index("Failed reads")]


def test_empty_read_after_a_large_fetch_counts_as_failure(tmp_path):
    files = paths(tmp_path)
    good = read_days(files, ("2026-11-01", unscreened(20)), ("2026-11-02", []))

    assert good["ok"] is False
    assert good["error"] == "returned no postings after 20 last time"
    assert (good["last_good_fetched"], good["last_good_date"]) == (20, "2026-11-01")
    assert failed_reads_cell(files) == "Good Co"


def test_empty_read_keeps_failing_while_the_reader_stays_broken(tmp_path):
    files = paths(tmp_path)
    good = read_days(files, ("2026-11-01", unscreened(20)), ("2026-11-02", []), ("2026-11-03", []))

    assert good["ok"] is False
    assert good["error"] == "returned no postings after 20 last time"
    assert (good["last_good_fetched"], good["last_good_date"]) == (20, "2026-11-01")


def test_dry_run_reports_an_empty_read_after_a_large_fetch_and_writes_nothing(tmp_path):
    files = paths(tmp_path)
    read_days(files, ("2026-11-01", unscreened(20)))
    before = {path: path.read_text() for path in (files.listings, files.status, files.readme)}

    client, _ = fake_client(boards(good=[], steady=STEADY_JOBS))
    result = refresh(settings(GOOD, STEADY), client, files, today="2026-11-02", dry_run=True)

    good = next(run for run in result.runs if run.company == "Good Co")
    assert (good.ok, good.error) == (False, "returned no postings after 20 last time")
    assert not result.written
    assert {path: path.read_text() for path in before} == before


def test_reader_that_always_fetches_nothing_stays_ok(tmp_path):
    files = paths(tmp_path)
    good = read_days(files, ("2026-11-01", []), ("2026-11-02", []))

    assert (good["ok"], good["error"]) == (True, None)
    assert (good["last_good_fetched"], good["last_good_date"]) == (None, None)
    assert failed_reads_cell(files) == "none"


def test_empty_read_after_a_small_fetch_stays_ok_and_keeps_the_baseline(tmp_path):
    files = paths(tmp_path)
    good = read_days(files, ("2026-11-01", unscreened(3)), ("2026-11-02", []))

    assert (good["ok"], good["fetched"], good["error"]) == (True, 0, None)
    assert (good["last_good_fetched"], good["last_good_date"]) == (3, "2026-11-01")


def test_successful_read_moves_the_baseline(tmp_path):
    files = paths(tmp_path)
    good = read_days(files, ("2026-11-01", unscreened(20)), ("2026-11-02", unscreened(12)))

    assert good["ok"] is True
    assert (good["last_good_fetched"], good["last_good_date"]) == (12, "2026-11-02")


def test_status_from_before_baselines_means_only_the_open_listings_guard_applies(tmp_path):
    files = paths(tmp_path)
    read_days(files, ("2026-11-01", unscreened(20)))
    old = json.loads(files.status.read_text())
    for entry in old["companies"].values():
        del entry["last_good_fetched"], entry["last_good_date"]
    files.status.write_text(json.dumps(old), encoding="utf-8")

    good = read_days(files, ("2026-11-02", []))

    assert (good["ok"], good["error"]) == (True, None)
    assert (good["last_good_fetched"], good["last_good_date"]) == (None, None)


def cli_on(monkeypatch, files):
    """Point `python -m tracker` at the test's files and companies."""
    monkeypatch.setattr("tracker.cli.Paths.default", lambda: files)
    monkeypatch.setattr("tracker.cli.load_settings", lambda: settings(GOOD, STEADY))


def test_reset_baseline_lets_the_next_empty_read_pass(tmp_path, monkeypatch, capsys):
    files = paths(tmp_path)
    read_days(files, ("2026-11-01", unscreened(20)), ("2026-11-02", []))
    cli_on(monkeypatch, files)

    assert main(["reset-baseline", "Good Co"]) == 0
    reset = json.loads(files.status.read_text())["companies"]["Good Co"]
    assert (reset["last_good_fetched"], reset["last_good_date"]) == (None, None)
    assert "Good Co" in capsys.readouterr().out

    good = read_days(files, ("2026-11-03", []))
    assert (good["ok"], good["error"]) == (True, None)


def test_reset_baseline_of_an_unknown_company_fails(tmp_path, monkeypatch, capsys):
    files = paths(tmp_path)
    read_days(files, ("2026-11-01", unscreened(20)))
    before = files.status.read_text()
    cli_on(monkeypatch, files)

    assert main(["reset-baseline", "Nobody Inc"]) == 1
    assert "Nobody Inc" in capsys.readouterr().out
    assert files.status.read_text() == before


def test_error_text_is_kept_on_one_line(tmp_path):
    # Error text can come from a job board. Kept on one line, it can't forge
    # another company's "[failed]" line in the refresh output.
    def respond(method, url, kwargs):
        if "/boards/good/" in url:
            return ValueError("bad payload\n[failed] Steady Co: forged\r\n\tnext")
        return FakeResponse({"jobs": STEADY_JOBS})

    client, _ = fake_client(respond)
    files = paths(tmp_path)
    result = refresh(settings(GOOD, STEADY), client, files, today="2026-11-01")

    good = next(run for run in result.runs if run.company == "Good Co")
    assert good.error == "bad payload [failed] Steady Co: forged next"
    status = json.loads(files.status.read_text())
    assert status["companies"]["Good Co"]["error"] == good.error


PAGE_ONLY = company("Page Co", platform="careers_page", page="https://page.example/careers")
LINK_ONLY = company("Link Co", platform="link")


def test_submitted_listings_of_companies_reading_no_job_board_never_go_missing(tmp_path):
    files = paths(tmp_path)
    rows = [
        submitted("https://page.example/jobs/1", company="Page Co"),
        submitted("https://link.example/jobs/1", company="Link Co"),
        submitted("https://good.example/jobs/1", company="Good Co"),
    ]
    files.listings.parent.mkdir(parents=True)
    files.listings.write_text(json.dumps(rows), encoding="utf-8")

    def respond(method, url, kwargs):
        if "page.example" in url:
            return FakeResponse(body="<html><p>Apply on Workday</p></html>")
        return FakeResponse({"jobs": STEADY_JOBS})

    for today in ("2026-11-02", "2026-11-03"):
        client, _ = fake_client(respond)
        refresh(settings(GOOD, PAGE_ONLY, LINK_ONLY), client, files, today=today)

    listings = {
        row["company"]: row
        for row in json.loads(files.listings.read_text())
        if row["platform"] == "submitted"
    }
    assert (listings["Page Co"]["status"], listings["Page Co"]["misses"]) == ("open", 0)
    assert (listings["Link Co"]["status"], listings["Link Co"]["misses"]) == ("open", 0)
    assert (listings["Good Co"]["status"], listings["Good Co"]["close_reason"]) == (
        "closed",
        "missing",
    )


def test_submitted_listings_do_not_make_an_empty_careers_page_read_fail(tmp_path):
    files = paths(tmp_path)
    rows = [
        submitted(f"https://page.example/jobs/{n}", company="Page Co")
        for n in range(EMPTY_READ_GUARD + 1)
    ]
    files.listings.parent.mkdir(parents=True)
    files.listings.write_text(json.dumps(rows), encoding="utf-8")
    client, _ = fake_client(lambda *args: FakeResponse(body="<html><p>Apply on Workday</p></html>"))

    result = refresh(settings(PAGE_ONLY), client, files, today="2026-11-02")

    (run,) = result.runs
    assert (run.ok, run.error) == (True, None)
    assert result.written


def test_screening_rejecting_every_read_listing_fails_despite_a_submitted_one(tmp_path):
    files = paths(tmp_path)
    jobs = [greenhouse_job(n, f"Software Engineering Intern {n}") for n in range(EMPTY_READ_GUARD)]
    client, _ = fake_client(handler(jobs))
    refresh(settings(GOOD), client, files, today="2026-11-01")
    rows = json.loads(files.listings.read_text())
    rows.append(submitted("https://good.example/jobs/1", company="Good Co"))
    files.listings.write_text(json.dumps(rows), encoding="utf-8")

    changed = [greenhouse_job(n, f"{INELIGIBLE_TITLE} {n}") for n in range(EMPTY_READ_GUARD)]
    client, _ = fake_client(handler(changed))
    result = refresh(settings(GOOD), client, files, today="2026-11-02")

    (run,) = result.runs
    assert run.error == (
        f"screening rejected all {EMPTY_READ_GUARD} open listings; treating as a changed response"
    )
