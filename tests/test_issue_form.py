"""The "Add internship" issue form stays in step with companies.toml and `tracker add`."""

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
