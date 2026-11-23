"""The Daily refresh workflow's failed-read reporting (.github/scripts/failed-reads.sh).

The script reads saved `python -m tracker refresh` output. Error text can come
from job boards, so these cases include text that tries to inject workflow
commands or HTML.
"""

import subprocess
from pathlib import Path

from conftest import FakeResponse, company, fake_client, settings

from tracker.cli import main
from tracker.pipeline import Paths

SCRIPT = Path(__file__).resolve().parent.parent / ".github" / "scripts" / "failed-reads.sh"

OUTPUT = (
    "[ok]     Acme: 12 fetched, 2 accepted\n"
    "[failed] Medtronic: HTTP 503 from https://jobs.medtronic.com\n"
    "[failed] Evil & Co: returned ::error::pwned %0A::error::next <script>alert(1)</script>\r\n"
    "3 postings rejected by screening\n"
)


def run(command: str, tmp_path: Path, output: str = OUTPUT) -> str:
    saved = tmp_path / "refresh.txt"
    saved.write_bytes(output.encode())
    done = subprocess.run(
        ["bash", str(SCRIPT), command, str(saved)],
        capture_output=True,
        check=True,
    )
    return done.stdout.decode()


def test_one_warning_per_failed_company_with_workflow_command_escaping(tmp_path):
    assert run("annotations", tmp_path).splitlines() == [
        "::warning title=Failed read::Medtronic: HTTP 503 from https://jobs.medtronic.com",
        "::warning title=Failed read::Evil & Co: returned ::error::pwned %250A::error::next "
        "<script>alert(1)</script>%0D",
    ]


def test_report_lists_failed_lines_html_escaped(tmp_path):
    assert run("report", tmp_path) == (
        "### Failed reads (2)\n"
        "\n"
        "<pre>\n"
        "[failed] Medtronic: HTTP 503 from https://jobs.medtronic.com\n"
        "[failed] Evil &amp; Co: returned ::error::pwned %0A::error::next "
        "&lt;script&gt;alert(1)&lt;/script&gt;\n"
        "</pre>\n"
    )


def test_error_with_a_line_break_gives_one_warning(tmp_path, monkeypatch, capsys):
    # A job board's error text with a real LF and a forged "[failed]" line, run
    # through `python -m tracker refresh` itself to get the output the
    # workflow saves.
    def respond(method, url, kwargs):
        if "/boards/evil/" in url:
            return ValueError("bad payload\n[failed] Acme: forged")
        return FakeResponse({"jobs": []})

    client, _ = fake_client(respond)
    companies = (company("Acme", board="acme"), company("Evil Co", board="evil"))
    monkeypatch.setattr("tracker.cli.Client", lambda: client)
    monkeypatch.setattr("tracker.cli.load_settings", lambda: settings(*companies))
    monkeypatch.setattr("tracker.cli.Paths.default", lambda: unused_paths(tmp_path))
    assert main(["refresh", "--dry-run"]) == 0

    assert run("annotations", tmp_path, capsys.readouterr().out).splitlines() == [
        "::warning title=Failed read::Evil Co: bad payload [failed] Acme: forged",
    ]


def unused_paths(tmp_path: Path) -> Paths:
    """Paths a dry run reads (and finds missing) but never writes."""
    data = tmp_path / "data"
    return Paths(
        listings=data / "listings.json",
        status=data / "status.json",
        readme=tmp_path / "README.md",
        closed=tmp_path / "CLOSED.md",
        screening_log=tmp_path / "logs" / "screening.json",
    )


def test_nothing_reported_when_every_read_succeeded(tmp_path):
    output = "[ok]     Acme: 12 fetched, 2 accepted\n0 postings rejected by screening\n"
    assert run("annotations", tmp_path, output) == ""
    assert run("report", tmp_path, output) == ""
    assert run("summary", tmp_path, output) == "No failed reads.\n"


def test_summary_is_the_report_when_reads_failed(tmp_path):
    assert run("summary", tmp_path) == run("report", tmp_path)


def test_log_is_the_whole_output_html_escaped(tmp_path):
    assert run("log", tmp_path) == (
        "<pre>\n"
        "[ok]     Acme: 12 fetched, 2 accepted\n"
        "[failed] Medtronic: HTTP 503 from https://jobs.medtronic.com\n"
        "[failed] Evil &amp; Co: returned ::error::pwned %0A::error::next "
        "&lt;script&gt;alert(1)&lt;/script&gt;\r\n"
        "3 postings rejected by screening\n"
        "</pre>\n"
    )
