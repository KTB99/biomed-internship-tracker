from dataclasses import replace

import pytest
from conftest import company, settings
from test_reconcile import record, submitted

from tracker.config import Program
from tracker.render import (
    APPLY_BUTTON,
    END_MARKER,
    START_MARKER,
    age,
    anchor,
    apply_button,
    cell,
    closed_page,
    link,
    listings_block,
    safe_url,
    splice,
)


def test_cell_escapes_markdown_and_html():
    assert cell("A | B") == "A \\| B"
    assert cell("<img src=x>") == "&lt;img src=x&gt;"
    assert cell("[click](javascript:alert(1))") == "\\[click\\]\\(javascript:alert\\(1\\)\\)"
    assert cell("two\nlines") == "two lines"
    assert cell(None) == ""


def test_links_only_allow_http_and_encode_breakers():
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("https://a.example/x (y)") == "https://a.example/x%20%28y%29"
    assert link("Role", "javascript:alert(1)") == "Role"
    assert link("Role", "https://a.example/1") == "[Role](https://a.example/1)"


def test_block_groups_by_family_newest_first():
    rows = [
        record(
            "1", title="Firmware Intern", family="Electrical & Firmware", posted_on="2026-10-01"
        ),
        record("2", title="FPGA Intern", family="Electrical & Firmware", posted_on="2026-11-01"),
        record("3", title="Old season", season="summer-2026"),
        record("4", title="Closed", status="closed", closed_on="2026-11-01", close_reason="manual"),
    ]
    status = {"last_run": "2026-11-02", "companies": {"Acme": {"ok": True}}}
    block = listings_block(rows, status, settings(company("Acme")))
    assert block.startswith(START_MARKER) and block.endswith(END_MARKER)
    assert "**2 open Summer 2027 internships** at 1 of 1 tracked companies" in block
    assert "[Electrical / Firmware](#electrical--firmware) (2)" in block
    assert "## Electrical / Firmware\n" in block
    assert "| Company | Role | Location | Apply | Age |" in block
    assert block.index("FPGA Intern") < block.index("Firmware Intern")
    button = f"[![Apply]({APPLY_BUTTON})](https://acme.example/jobs/2)"
    assert f"| Acme | FPGA Intern | Irvine, CA, US | {button} | 1d |" in block
    assert "| Acme | Firmware Intern | Irvine, CA, US |" in block and "| 4w |" in block
    assert "Old season" not in block and "| Acme | Closed |" not in block
    assert "| [Acme](https://acme.example) | greenhouse | 2 | ok |" in block
    assert "## Tracker stats" in block
    assert "| 2026-11-02 | 2 | 1 | 0 | 1 | none | 1 |" in block


def test_empty_block():
    block = listings_block([], {}, settings())
    assert "_No open listings right now._" in block
    assert "Last refreshed never" in block


def test_splice_replaces_only_between_markers():
    readme = f"intro\n{START_MARKER}\nold\n{END_MARKER}\noutro\n"
    assert splice(readme, f"{START_MARKER}new{END_MARKER}") == (
        f"intro\n{START_MARKER}new{END_MARKER}\noutro\n"
    )
    with pytest.raises(ValueError):
        splice("no markers", "x")


def test_closed_page_lists_closed_rows():
    row = record(status="closed", closed_on="2026-11-03", close_reason="missing")
    page = closed_page([row, record("2")])
    assert "(1 total)" in page
    assert "| Acme | Engineering Intern 1 |" in page
    assert "Engineering Intern 2" not in page


def test_closed_page_explains_each_close_reason():
    page = closed_page([])
    assert "`missing` means" in page
    assert "`manual` means" in page
    assert "`deadline` means the closing date given when the listing was submitted passed" in page


HOSTILE = {
    "title": "Intern | [click](javascript:alert(1)) <script>x</script>",
    "location": "Boston | <img src=x onerror=alert(1)>",
}


def test_submitted_rows_are_escaped_in_the_readme():
    row = submitted(
        "https://acme.example/jobs/1?a=1)[x](javascript:alert(1))",
        company="Acme",
        **HOSTILE,
    )
    javascript = submitted("javascript:alert(1)//https://acme.example/jobs/2", company="Acme")
    status = {"last_run": "2026-11-02", "companies": {"Acme": {"ok": True}}}
    block = listings_block([row, javascript], status, settings(company("Acme")))
    line = next(text for text in block.splitlines() if "Intern \\|" in text)
    assert line.count(" | ") == 4  # five cells: the title and location add no columns
    assert "<script>" not in block and "<img" not in block
    assert "\\[click\\]\\(javascript:alert\\(1\\)\\)" in line
    assert "&lt;img src=x onerror=alert\\(1\\)&gt;" in line
    target = "https://acme.example/jobs/1?a=1%29[x]%28javascript:alert%281%29%29"
    assert f"| [![Apply]({APPLY_BUTTON})]({target}) |" in line
    assert "| Acme | Quality Engineering Intern | Minneapolis, MN, US | — |" in block
    assert "](javascript:" not in block


def test_submitted_rows_are_escaped_on_the_closed_page():
    row = submitted(
        closes_on="2026-11-01", status="closed", closed_on="2026-11-02", close_reason="deadline"
    )
    row.update(HOSTILE)
    line = next(text for text in closed_page([row]).splitlines() if "Intern \\|" in text)
    assert line.count(" | ") == 6
    assert "<script>" not in line and "<img" not in line
    assert line.endswith("| 2026-11-02 | deadline |")


@pytest.mark.parametrize(
    "heading, fragment",
    [
        ("Biomedical / R&D", "biomedical--rd"),
        ("Data / ML / AI", "data--ml--ai"),
        ("Other STEM", "other-stem"),
    ],
)
def test_anchor_matches_github_heading_ids(heading, fragment):
    assert anchor(heading) == fragment


@pytest.mark.parametrize(
    "since, expected",
    [
        ("2026-11-02", "new"),
        ("2026-10-30", "3d"),
        ("2026-10-12", "3w"),
        ("2026-08-01", "3mo"),
    ],
)
def test_age(since, expected):
    assert age(since, "2026-11-02") == expected


def test_age_without_a_refresh_date():
    assert age("2026-11-02", None) == "—"


def test_apply_button_refuses_unsafe_urls():
    assert apply_button("javascript:alert(1)") == "—"
    assert apply_button("https://a.example/1") == f"[![Apply]({APPLY_BUTTON})](https://a.example/1)"


def test_stats_name_failed_companies():
    status = {"last_run": "2026-11-02", "companies": {"Acme": {"ok": False}, "Beta": {"ok": True}}}
    block = listings_block([], status, settings(company("Acme"), company("Beta")))
    assert "| 2026-11-02 | 0 | 0 | 0 | 2 | Acme | 0 |" in block


def test_company_table_shows_each_reads_fetched_count():
    status = {
        "last_run": "2026-11-02",
        "companies": {
            "Acme": {"ok": True, "fetched": 202, "accepted": 0},
            "Beta": {"ok": False, "fetched": 0, "accepted": 0},
            "Links": {"ok": True, "fetched": 0, "accepted": 0},
        },
    }
    companies = (company("Acme"), company("Beta"), company("Gamma"), company("Links", "link"))
    block = listings_block([], status, settings(*companies))
    assert "| Company | Platform | Open | Last read | Fetched |" in block
    assert "| --- | --- | --- | --- | ---: |" in block
    assert "| [Acme](https://acme.example) | greenhouse | 0 | ok | 202 |" in block
    assert "| [Beta](https://acme.example) | greenhouse | 0 | failed | 0 |" in block
    assert "| [Gamma](https://acme.example) | greenhouse | 0 | — | — |" in block
    assert "| [Links](https://acme.example) | — | 0 | link only | — |" in block


def test_a_company_note_shows_under_its_listing_titles():
    noted = replace(company("Acme"), note="Apply once | <b>all labs</b>")
    status = {"last_run": "2026-11-02", "companies": {}}
    block = listings_block([record("1", title="Lab Intern")], status, settings(noted))
    note = "<br><sub>Apply once \\| &lt;b&gt;all labs&lt;/b&gt;</sub>"
    assert f"| Acme | Lab Intern{note} | Irvine, CA, US |" in block


def test_a_company_note_shows_under_its_program_page():
    program = Program(label="Summer program", url="https://acme.example/sip", location="")
    noted = replace(company("Acme"), program=program, note="Apply once")
    block = listings_block([], {"last_run": "2026-11-02", "companies": {}}, settings(noted))
    assert "| Acme | Summer program<br><sub>Apply once</sub> |" in block


def test_a_role_without_a_note_has_no_subtext():
    status = {"last_run": "2026-11-02", "companies": {}}
    block = listings_block([record("1", title="Lab Intern")], status, settings(company("Acme")))
    assert "| Acme | Lab Intern | Irvine, CA, US |" in block
    assert "<sub>" not in block


def test_a_rolling_company_shows_rolling_instead_of_an_age():
    rolling = replace(company("Acme"), rolling=True)
    row = record("1", title="Neuro Intern", posted_on="2024-06-13", first_seen="2026-11-02")
    block = listings_block([row], {"last_run": "2026-11-02", "companies": {}}, settings(rolling))
    assert "| Acme | Neuro Intern | Irvine, CA, US |" in block
    assert block.count(" | rolling |") == 1
    assert "2y" not in block and "mo |" not in block


def test_rolling_listings_sort_by_when_the_tracker_first_saw_them():
    rolling = replace(company("Acme"), rolling=True)
    old_posting = record(
        "1", company="Acme", title="Rolling Intern", posted_on="2024-06-13", first_seen="2026-11-02"
    )
    dated = record(
        "2", company="Beta", title="Dated Intern", posted_on="2026-10-01", first_seen="2026-10-01"
    )
    status = {"last_run": "2026-11-02", "companies": {}}
    block = listings_block([dated, old_posting], status, settings(rolling, company("Beta")))
    assert block.index("Rolling Intern") < block.index("Dated Intern")
