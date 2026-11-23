"""`python -m tracker add`: accept an "Add internship" issue as a submitted listing."""

import io
import json

import pytest
from conftest import company, settings
from test_pipeline import paths
from test_reconcile import submitted

from tracker import catalog
from tracker.cli import main
from tracker.config import Company
from tracker.ids import listing_id
from tracker.render import APPLY_BUTTON

WORKDAY = "medtronic.wd1.myworkdayjobs.com"
MEDTRONIC = Company(
    name="Medtronic",
    platform="careers_page",
    careers_url="https://www.medtronic.com/careers",
    params={"page": "https://www.medtronic.com/careers"},
    submit_hosts=(WORKDAY, "www.medtronic.com"),
)
ABBOTT = company("Abbott", platform="phenom", origin="https://www.jobs.abbott")
URL = f"https://{WORKDAY}/en-US/MedtronicCareers/job/Minneapolis/Quality-Engineering-Intern_R1"
FIELDS = {
    "Company": "Medtronic",
    "Title": "Quality Engineering Intern",
    "Apply URL": URL,
    "Location": "Minneapolis, MN",
    "Term": "Summer 2027",
    "Closes on": "_No response_",
}


def form(**changes) -> str:
    """An issue body the way GitHub renders the "Add internship" form."""
    fields = dict(FIELDS)
    fields.update({label.replace("_", " "): value for label, value in changes.items()})
    return "\n\n".join(f"### {label}\n\n{value}" for label, value in fields.items()) + "\n"


def prepare(tmp_path, monkeypatch, body: str, existing=()):
    """Test files holding `existing` listings and the issue body; return (files, issue file)."""
    files = paths(tmp_path)
    if existing:
        files.listings.parent.mkdir()
        files.listings.write_text(catalog.dumps(list(existing)), encoding="utf-8")
    monkeypatch.setattr("tracker.cli.Paths.default", lambda: files)
    monkeypatch.setattr("tracker.cli.load_settings", lambda: settings(MEDTRONIC, ABBOTT))
    issue_file = tmp_path / "issue.md"
    issue_file.write_text(body, encoding="utf-8")
    return files, issue_file


def run_add(issue_file, *extra: str, issue: int = 42) -> int:
    return main(["add", "--issue", str(issue), str(issue_file), "--today", "2026-11-23", *extra])


def add(tmp_path, monkeypatch, body: str, *extra: str, existing=()):
    """Run `python -m tracker add --issue 42 FILE` on test files; return (code, files)."""
    files, issue_file = prepare(tmp_path, monkeypatch, body, existing)
    return run_add(issue_file, *extra), files


def refused(tmp_path, monkeypatch, capsys, body: str, *extra: str, existing=()) -> str:
    """Run an add that must be refused: exit 1, nothing written. Return its output."""
    _, issue_file = prepare(tmp_path, monkeypatch, body, existing)
    before = snapshot(tmp_path)
    assert run_add(issue_file, *extra) == 1
    assert snapshot(tmp_path) == before
    return capsys.readouterr().out


def snapshot(root) -> dict:
    return {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}


def listings(files) -> list[dict]:
    return json.loads(files.listings.read_text(encoding="utf-8"))


def test_add_writes_a_submitted_listing_and_the_views(tmp_path, monkeypatch, capsys):
    code, files = add(tmp_path, monkeypatch, form(Closes_on="2027-01-15"))

    assert code == 0
    [row] = listings(files)
    assert row == {
        "id": listing_id("Medtronic", "submitted", URL, URL),
        "company": "Medtronic",
        "title": "Quality Engineering Intern",
        "location": "Minneapolis, MN, US",
        "url": URL,
        "platform": "submitted",
        "external_id": URL,
        "family": "Quality & Manufacturing",
        "season": "summer-2027",
        "posted_on": None,
        "first_seen": "2026-11-23",
        "last_seen": "2026-11-23",
        "status": "open",
        "misses": 0,
        "last_missed": None,
        "closed_on": None,
        "close_reason": None,
        "closes_on": "2027-01-15",
        "submitted_in": 42,
    }
    assert "Quality Engineering Intern" in files.readme.read_text(encoding="utf-8")
    assert files.closed.exists()
    assert not files.status.exists()
    assert row["id"] in capsys.readouterr().out


@pytest.mark.parametrize("name", ["Nobody Inc", "", "Abbott"])
def test_add_refuses_a_company_that_accepts_no_submissions(tmp_path, monkeypatch, capsys, name):
    # Abbott is in the registry but lists no submit_hosts.
    out = refused(tmp_path, monkeypatch, capsys, form(Company=name))
    assert "does not accept submissions" in out


@pytest.mark.parametrize(
    "url",
    [
        "",
        f"http://{WORKDAY}/job/1",  # not https
        "https://evil.example/job/1",  # host not in submit_hosts
        f"https://jobs.{WORKDAY}/job/1",  # a subdomain is not the host
        f"https://{WORKDAY}:8443/job/1",  # a port
        f"https://user@{WORKDAY}/job/1",  # userinfo
        "javascript:alert(1)//https://www.medtronic.com/",
    ],
)
def test_add_refuses_an_apply_url_off_the_companys_submit_hosts(tmp_path, monkeypatch, capsys, url):
    out = refused(tmp_path, monkeypatch, capsys, form(Apply_URL=url))
    assert (
        "Apply URL must be https on one of: medtronic.wd1.myworkdayjobs.com, www.medtronic.com"
        in out
    )


@pytest.mark.parametrize("label", ["Title", "Location"])
@pytest.mark.parametrize("value", ["", "   ", "_No response_"])
def test_add_refuses_an_empty_title_or_location(tmp_path, monkeypatch, capsys, label, value):
    out = refused(tmp_path, monkeypatch, capsys, form(**{label: value}))
    assert f"{label} is empty" in out


@pytest.mark.parametrize("value", ["next week", "2027-1-15", "20270115", "2027-02-30", "1/15/2027"])
def test_add_refuses_a_closing_date_that_is_not_an_iso_date(tmp_path, monkeypatch, capsys, value):
    out = refused(tmp_path, monkeypatch, capsys, form(Closes_on=value))
    assert "Closes on must be a date written YYYY-MM-DD" in out


def test_add_refuses_a_closing_date_before_today(tmp_path, monkeypatch, capsys):
    out = refused(
        tmp_path, monkeypatch, capsys, form(Closes_on="2027-01-15"), "--today", "2027-01-16"
    )
    assert "Closes on 2027-01-15 is before today (2027-01-16)" in out


@pytest.mark.parametrize(("value", "closes_on"), [("2026-11-23", "2026-11-23"), ("", None)])
def test_add_accepts_a_closing_date_of_today_or_none(tmp_path, monkeypatch, value, closes_on):
    code, files = add(tmp_path, monkeypatch, form(Closes_on=value))
    assert code == 0
    assert listings(files)[0]["closes_on"] == closes_on


def test_add_refuses_a_posting_screening_rejects_and_says_why(tmp_path, monkeypatch, capsys):
    body = form(Title="Marketing Intern", Location="Galway, Ireland", Term="Fall 2027")
    out = refused(tmp_path, monkeypatch, capsys, body)
    assert "screening rejected it" in out
    for reason in ("no US location", "non-STEM role", "not a summer term"):
        assert reason in out


def test_add_screens_the_term_for_the_target_year(tmp_path, monkeypatch, capsys):
    out = refused(tmp_path, monkeypatch, capsys, form(Term="Summer 2028"))
    assert "term year 2028 is not 2027" in out


@pytest.mark.parametrize(
    "state",
    [{}, {"status": "closed", "closed_on": "2026-11-20", "close_reason": "manual"}],
)
def test_add_refuses_a_listing_that_already_exists(tmp_path, monkeypatch, capsys, state):
    existing = submitted(URL, company="Medtronic", submitted_in=7, **state)
    out = refused(tmp_path, monkeypatch, capsys, form(), existing=[existing])
    assert f"listing {existing['id']} already exists" in out


def read_listing(url, company="Medtronic", **overrides) -> dict:
    """A listing a job-board read found at `url`."""
    return submitted(
        url,
        company=company,
        id=listing_id(company, "greenhouse", "R1", url),
        platform="greenhouse",
        external_id="R1",
        **overrides,
    )


def test_add_refuses_a_url_an_open_listing_of_the_company_already_has(
    tmp_path, monkeypatch, capsys
):
    # Same posting as URL: reconcile's match ignores the query and a trailing /apply.
    existing = read_listing(f"{URL.replace(WORKDAY, WORKDAY.upper())}/apply?source=LinkedIn")
    out = refused(tmp_path, monkeypatch, capsys, form(), existing=[existing])
    assert f"open listing {existing['id']} already has this Apply URL" in out


@pytest.mark.parametrize(
    "existing",
    [
        read_listing(URL, status="closed", closed_on="2026-11-20", close_reason="missing"),
        read_listing(URL, company="Other Co"),
    ],
    ids=["closed", "other company"],
)
def test_add_accepts_a_url_only_a_closed_or_other_listing_has(tmp_path, monkeypatch, existing):
    code, files = add(tmp_path, monkeypatch, form(), existing=[existing])
    assert code == 0
    assert sorted(row["platform"] for row in listings(files)) == ["greenhouse", "submitted"]


def test_add_reads_the_issue_body_from_stdin(tmp_path, monkeypatch):
    # What `gh issue view 42 --json body -q .body | python -m tracker add --issue 42 -` pipes in.
    files, _ = prepare(tmp_path, monkeypatch, "")
    monkeypatch.setattr("sys.stdin", io.StringIO(form().replace("\n", "\r\n")))

    assert main(["add", "--issue", "42", "-", "--today", "2026-11-23"]) == 0
    [row] = listings(files)
    assert (row["title"], row["url"], row["submitted_in"]) == (
        "Quality Engineering Intern",
        URL,
        42,
    )


def test_untrusted_fields_are_escaped_in_the_readme(tmp_path, monkeypatch):
    body = form(
        Title="Quality Engineering Intern | [click](javascript:alert(1)) <script>x</script>",
        Location="Minneapolis, MN | <img src=x onerror=alert(1)>",
        Apply_URL=f"https://{WORKDAY}/job/1?a=1)[x](javascript:alert(1))",
    )
    code, files = add(tmp_path, monkeypatch, body)

    assert code == 0
    readme = files.readme.read_text(encoding="utf-8")
    line = next(text for text in readme.splitlines() if "Quality Engineering Intern" in text)
    assert line.count(" | ") == 4  # five cells: the title and location add no columns
    assert "<script>" not in readme and "<img" not in readme
    assert (
        "Intern \\| \\[click\\]\\(javascript:alert\\(1\\)\\) &lt;script&gt;x&lt;/script&gt;" in line
    )
    assert "&lt;img src=x onerror=alert\\(1\\)&gt;" in line
    target = f"https://{WORKDAY}/job/1?a=1%29[x]%28javascript:alert%281%29%29"
    assert f"| [![Apply]({APPLY_BUTTON})]({target}) |" in line
    assert "](javascript:" not in readme
