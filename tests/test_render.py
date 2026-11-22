import pytest
from conftest import company, settings
from test_reconcile import record

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
    assert f"| Acme | FPGA Intern | Irvine, CA | {button} | 1d |" in block
    assert "| Acme | Firmware Intern | Irvine, CA |" in block and "| 4w |" in block
    assert "Old season" not in block and "| Acme | Closed |" not in block
    assert "| [Acme](https://acme.example) | greenhouse | 2 | ok |" in block
    assert "## Tracker stats" in block
    assert "| 2026-11-02 | 2 | 1 | 1 | none | 1 |" in block


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
    assert "| 2026-11-02 | 0 | 0 | 2 | Acme | 0 |" in block
