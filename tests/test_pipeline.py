import json

from conftest import FakeResponse, company, fake_client, settings

from tracker.cli import main
from tracker.config import REGISTRY_PATH, load_settings
from tracker.pipeline import EMPTY_READ_GUARD, Paths, refresh
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
    }
    assert status["companies"]["Broken Co"]["ok"] is False
    assert "blocked" in status["companies"]["Broken Co"]["error"]
    readme = files.readme.read_text()
    assert "Software Engineering Intern" in readme and readme.endswith("Footer.\n")
    assert files.closed.read_text().startswith("# Closed listings")
    log = json.loads(files.screening_log.read_text())
    assert log[0]["title"] == "Sales Intern" and log[0]["reasons"] == ["non-STEM role"]


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


def test_committed_catalog_is_valid_and_views_are_current():
    assert main(["validate"]) == 0
    assert main(["render", "--check"]) == 0
