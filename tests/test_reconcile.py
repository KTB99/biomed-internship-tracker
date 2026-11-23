import pytest

from tracker import catalog
from tracker.ids import listing_id
from tracker.models import Lead
from tracker.reconcile import CompanyRun, close_manually, display_location, new_record, reconcile
from tracker.screen import Verdict

SEASON = "summer-2027"


def record(external_id="1", company="Acme", today="2026-11-01", **overrides):
    lead = Lead(
        company=company,
        platform="greenhouse",
        external_id=external_id,
        title=f"Engineering Intern {external_id}",
        url=f"https://acme.example/jobs/{external_id}",
        locations=["Irvine, CA"],
    )
    row = new_record(lead, Verdict(True, "Other STEM"), season=SEASON, today=today)
    row.update(overrides)
    return row


def ok(company="Acme", *rows):
    return CompanyRun(company, ok=True, accepted=list(rows), fetched=len(rows))


def test_new_records_are_valid():
    assert catalog.problems([record()]) == []


def test_ids_are_stable_and_company_scoped():
    assert listing_id("Acme", "lever", "7", "u") == listing_id("ACME ", "lever", "7", "other")
    assert listing_id("Acme", "lever", "7", "u") != listing_id("Other", "lever", "7", "u")
    assert listing_id("Acme", "lever", "", "u1") != listing_id("Acme", "lever", "", "u2")


def test_seen_again_keeps_first_seen_and_refreshes_fields():
    old = record(today="2026-10-01", posted_on="2026-09-30")
    fresh = record(today="2026-11-01", title="Engineering Intern (Renamed)")
    (row,) = reconcile([old], [ok("Acme", fresh)], "2026-11-01", season=SEASON)
    assert row["first_seen"] == "2026-10-01"
    assert row["last_seen"] == "2026-11-01"
    assert row["title"] == "Engineering Intern (Renamed)"
    assert row["posted_on"] == "2026-09-30"


def test_two_missed_days_close_a_listing():
    rows = [record()]
    rows = reconcile(rows, [ok("Acme")], "2026-11-02", season=SEASON)
    assert (rows[0]["status"], rows[0]["misses"]) == ("open", 1)
    rows = reconcile(
        rows, [ok("Acme")], "2026-11-02", season=SEASON
    )  # same day again: no extra miss
    assert rows[0]["misses"] == 1
    rows = reconcile(rows, [ok("Acme")], "2026-11-03", season=SEASON)
    assert rows[0]["status"] == "closed"
    assert rows[0]["closed_on"] == "2026-11-03"
    assert rows[0]["close_reason"] == "missing"
    assert catalog.problems(rows) == []


def test_seen_again_resets_misses_and_reopens():
    closed = record(status="closed", misses=2, last_missed="2026-11-03")
    closed.update(closed_on="2026-11-03", close_reason="missing")
    (row,) = reconcile([closed], [ok("Acme", record())], "2026-11-05", season=SEASON)
    assert (row["status"], row["misses"], row["closed_on"]) == ("open", 0, None)


def test_manual_close_is_sticky():
    rows = close_manually([record()], record()["id"], "2026-11-02")
    (row,) = reconcile(rows, [ok("Acme", record())], "2026-11-03", season=SEASON)
    assert (row["status"], row["close_reason"]) == ("closed", "manual")


def test_failed_company_is_untouched():
    rows = [record()]
    failed = CompanyRun("Acme", ok=False, error="blocked")
    assert reconcile(rows, [failed], "2026-11-02", season=SEASON) == rows


def test_other_companies_are_not_marked_missing():
    rows = [record(company="Other")]
    (row,) = reconcile(rows, [ok("Acme")], "2026-11-02", season=SEASON)
    assert row["misses"] == 0


def test_close_unknown_id():
    with pytest.raises(KeyError):
        close_manually([record()], "nope", "2026-11-02")


def test_display_location_puts_us_first_and_truncates():
    places = ["Galway, Ireland", "Irvine, CA", "Irvine, CA", "Austin, TX", "Boston, MA", "Remote"]
    assert display_location(places) == "Irvine, CA; Austin, TX; Boston, MA (+2 more)"


def test_schema_rejects_inconsistent_closed_rows():
    bad = record(status="closed")
    assert catalog.problems([bad])
    assert catalog.problems([record(), record()]) == [f"{record()['id']}: duplicate id"]


def shown_location(*places):
    lead = Lead(
        company="Acme",
        platform="phenom",
        external_id="1",
        title="Engineering Intern",
        url="https://acme.example/jobs/1",
        locations=list(places),
    )
    return new_record(lead, Verdict(True, "Other STEM"), season=SEASON, today="2026-11-01")[
        "location"
    ]


@pytest.mark.parametrize(
    "places, expected",
    [
        (
            ["New Kensington, Pennsylvania, United States, Pennsylvania, United States of America"],
            "New Kensington, Pennsylvania, United States",
        ),
        (
            ["San Diego, California, United States, California, United States of America"],
            "San Diego, California, United States",
        ),
        (
            ["Marlborough US-MA, United States | N/A", "Marlboro, MA, US"],
            "Marlborough US-MA, United States; Marlboro, MA, United States",
        ),
        (
            ["Maple Grove US-MN, United States | N/A", "Maple Grove, MN, US"],
            "Maple Grove US-MN, United States; Maple Grove, MN, United States",
        ),
        (["United States | N/A", "US"], "United States"),
        (
            ["Utrecht, UT, NL", "Utrecht, Netherlands | N/A"],
            "Utrecht, UT, NL; Utrecht, Netherlands",
        ),
        (["  Bldg 4 / Lab 2 - Remote (Hybrid)  "], "Bldg 4 / Lab 2 - Remote (Hybrid)"),
        (["N/A"], ""),
    ],
)
def test_displayed_location_names_each_place_once(places, expected):
    assert shown_location(*places) == expected


def test_more_count_is_of_distinct_places_after_tidying():
    places = [
        "Galway, Ireland",
        "Irvine, CA, USA",
        "Irvine, CA, United States",
        "Austin, TX, US",
        "Boston, MA",
        "Remote | N/A",
    ]
    assert shown_location(*places) == (
        "Irvine, CA, United States; Austin, TX, United States; Boston, MA (+2 more)"
    )
