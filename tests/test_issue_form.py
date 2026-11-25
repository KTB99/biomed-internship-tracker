"""The issue forms: "Add internship" stays in step with companies.toml and `tracker add`."""

import yaml

from tracker.config import ROOT, load_settings

FORM = ROOT / ".github" / "ISSUE_TEMPLATE" / "add-internship.yml"


def fields() -> dict[str, dict]:
    form = yaml.safe_load(FORM.read_text(encoding="utf-8"))
    return {item["id"]: item for item in form["body"] if "id" in item}


def test_company_options_are_the_companies_that_accept_submissions():
    company = fields()["company"]
    accepting = [entry.name for entry in load_settings().companies if entry.submit_hosts]
    assert company["type"] == "dropdown"
    assert company["attributes"]["options"] == accepting
    assert accepting  # the registry lists at least one company that accepts submissions


def test_form_labels_are_the_ones_tracker_add_reads():
    labels = {item["attributes"]["label"]: item for item in fields().values()}
    assert list(labels) == ["Company", "Title", "Apply URL", "Location", "Term", "Closes on"]
    required = [label for label, item in labels.items() if item["validations"]["required"]]
    assert required == ["Company", "Title", "Apply URL", "Location", "Term"]


TEMPLATES = ROOT / ".github" / "ISSUE_TEMPLATE"
TRIAGE_LABELS = {"needs-triage", "needs-info", "ready-for-agent", "ready-for-human", "wontfix"}


def test_every_issue_form_is_well_formed_and_starts_in_triage():
    forms = sorted(p for p in TEMPLATES.glob("*.yml") if p.name != "config.yml")
    assert [p.name for p in forms] == [
        "add-internship.yml",
        "report-listing.yml",
        "suggest-company.yml",
    ]
    for path in forms:
        form = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert form["name"] and form["description"], path.name
        assert "needs-triage" in form["labels"], path.name
        assert not TRIAGE_LABELS & set(form["labels"]) - {"needs-triage"}, path.name
        ids = [item["id"] for item in form["body"] if "id" in item]
        assert len(ids) == len(set(ids)), path.name
        for item in form["body"]:
            if item["type"] != "markdown":
                assert item["attributes"]["label"], (path.name, item.get("id"))
                assert "required" in item.get("validations", {}), (path.name, item["id"])


def test_blank_issues_are_off():
    config = yaml.safe_load((TEMPLATES / "config.yml").read_text(encoding="utf-8"))
    assert config["blank_issues_enabled"] is False
