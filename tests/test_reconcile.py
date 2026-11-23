import pytest

from tracker import catalog
from tracker.ids import listing_id
from tracker.models import Lead
from tracker.reconcile import (
    CompanyRun,
    apply_url_key,
    close_manually,
    display_location,
    new_record,
    reconcile,
)
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


def test_seen_again_keeps_first_seen_even_if_the_record_claims_an_earlier_one():
    old = record(today="2026-11-05")
    fresh = record(today="2026-11-03")
    (row,) = reconcile([old], [ok("Acme", fresh)], "2026-11-03", season=SEASON)
    assert row["first_seen"] == "2026-11-05"


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
            "New Kensington, PA",
        ),
        (
            ["San Diego, California, United States, California, United States of America"],
            "San Diego, CA",
        ),
        (
            ["Marlborough US-MA, United States | N/A", "Marlboro, MA, US"],
            "Marlborough, MA; Marlboro, MA",
        ),
        (["Maple Grove US-MN, United States | N/A", "Maple Grove, MN, US"], "Maple Grove, MN"),
        (["Irvine, CA 92602, United States"], "Irvine, CA"),
        (["Naples, FL, US, 34108"], "Naples, FL"),
        (["Boston, MA 02110-1234"], "Boston, MA"),
        (["La Jolla, California, United States"], "La Jolla, CA"),
        (["Newark, Delaware, United States of America"], "Newark, DE"),
        (["Washington, District of Columbia, USA"], "Washington, DC"),
        (["New York, NY, US"], "New York, NY"),
        (["Cleveland, Bolivar, MS"], "Cleveland, Bolivar, MS"),
        (["Columbus, NE"], "Columbus, NE"),
        (["Pennsylvania, United States"], "Pennsylvania"),
        (["United States | N/A", "US"], "United States"),
        (["Remote, United States of America"], "Remote, United States"),
        (
            ["Utrecht, UT, NL", "Utrecht, Netherlands | N/A"],
            "Utrecht, UT, NL; Utrecht, Netherlands",
        ),
        (["Toronto, ON, CA"], "Toronto, ON, CA"),
        (["Dublin, D02 X285, Ireland"], "Dublin, D02 X285, Ireland"),
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
    assert shown_location(*places) == ("Irvine, CA; Austin, TX; Boston, MA (+2 more)")


def submitted(url="https://acme.example/jobs/77", company="Acme", today="2026-11-01", **overrides):
    """A submitted listing, shaped the way the maintainer command will write one."""
    row = {
        "id": listing_id(company, "submitted", url, url),
        "company": company,
        "title": "Quality Engineering Intern",
        "location": "Minneapolis, MN",
        "url": url,
        "platform": "submitted",
        "external_id": url,
        "family": "Quality & Manufacturing",
        "season": SEASON,
        "posted_on": None,
        "first_seen": today,
        "last_seen": today,
        "status": "open",
        "misses": 0,
        "last_missed": None,
        "closed_on": None,
        "close_reason": None,
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "extra",
    [
        {},
        {"closes_on": "2027-01-15", "submitted_in": 42},
        {"closes_on": None, "submitted_in": None},
    ],
)
def test_a_submitted_row_is_valid_with_or_without_deadline_and_issue(extra):
    assert catalog.problems([submitted(**extra)]) == []


@pytest.mark.parametrize(
    "extra", [{"closes_on": "2027-01-15"}, {"submitted_in": 42}, {"closes_on": None}]
)
def test_a_read_row_may_not_carry_submission_fields(extra):
    assert catalog.problems([record(**extra)])


@pytest.mark.parametrize("issue", [0, -3, "42", 4.5, True])
def test_submitted_in_is_an_issue_number(issue):
    assert catalog.problems([submitted(submitted_in=issue)])


def test_closes_on_is_a_date():
    assert catalog.problems([submitted(closes_on="next week")])


def unreadable(company="Acme", *rows):
    """A good run of a company that doesn't read a job board (careers_page or link)."""
    return CompanyRun(company, ok=True, accepted=list(rows), reads_job_board=False)


def test_a_submitted_listing_gains_no_miss_while_its_company_reads_no_job_board():
    rows = [submitted()]
    for today in ("2026-11-02", "2026-11-03", "2026-11-04"):
        rows = reconcile(rows, [unreadable("Acme")], today, season=SEASON)
    (row,) = rows
    assert (row["status"], row["misses"], row["last_missed"]) == ("open", 0, None)


def test_a_submitted_listing_gains_misses_once_its_company_reads_a_job_board():
    rows = reconcile([submitted()], [unreadable("Acme")], "2026-11-02", season=SEASON)
    rows = reconcile(rows, [ok("Acme", record("1"))], "2026-11-03", season=SEASON)
    by_platform = {row["platform"]: row for row in rows}
    assert by_platform["submitted"]["misses"] == 1
    rows = reconcile(rows, [ok("Acme", record("1"))], "2026-11-04", season=SEASON)
    by_platform = {row["platform"]: row for row in rows}
    assert by_platform["submitted"]["status"] == "closed"
    assert by_platform["submitted"]["close_reason"] == "missing"
    assert by_platform["greenhouse"]["status"] == "open"
    assert catalog.problems(rows) == []


@pytest.mark.parametrize(
    "run",
    [
        unreadable("Acme"),
        ok("Acme"),
        CompanyRun("Acme", ok=False, error="blocked"),
    ],
    ids=["no job board read", "good read", "failed read"],
)
def test_a_submitted_listing_closes_the_day_after_its_deadline(run):
    rows = [submitted(closes_on="2026-11-02")]
    (row,) = reconcile(rows, [run], "2026-11-02", season=SEASON)
    assert row["status"] == "open"
    (row,) = reconcile([row], [run], "2026-11-03", season=SEASON)
    assert (row["status"], row["closed_on"], row["close_reason"]) == (
        "closed",
        "2026-11-03",
        "deadline",
    )
    assert catalog.problems([row]) == []


def test_a_deadline_closes_a_listing_whose_company_was_not_read():
    rows = [submitted(closes_on="2026-11-01")]
    (row,) = reconcile(rows, [], "2026-11-03", season=SEASON)
    assert (row["status"], row["close_reason"]) == ("closed", "deadline")


def test_listings_without_a_deadline_or_already_closed_are_left_alone():
    manual = submitted(
        "https://acme.example/jobs/78",
        closes_on="2026-11-01",
        status="closed",
        closed_on="2026-10-20",
        close_reason="manual",
    )
    rows = [submitted(), manual, record()]
    failed = CompanyRun("Acme", ok=False, error="blocked")
    assert reconcile(rows, [failed], "2026-11-03", season=SEASON) == rows


@pytest.mark.parametrize(
    "submitted_url, read_url",
    [
        ("https://acme.example/jobs/9", "https://acme.example/jobs/9"),
        ("https://acme.example/jobs/9/apply", "https://acme.example/jobs/9"),
        ("https://acme.example/jobs/9/", "https://acme.example/jobs/9/apply/"),
        ("https://acme.example/jobs/9?source=linkedin", "https://acme.example/jobs/9?gh_src=x"),
        ("https://acme.example/jobs/9#apply", "https://acme.example/jobs/9"),
        ("https://ACME.example/jobs/9", "https://acme.example/jobs/9"),
    ],
)
def test_a_read_listing_replaces_the_submitted_listing_with_its_url(submitted_url, read_url):
    mine = submitted(submitted_url, today="2026-10-01", closes_on="2027-01-15", submitted_in=42)
    read = record("9", today="2026-11-03", url=read_url)
    rows = reconcile([mine], [ok("Acme", read)], "2026-11-03", season=SEASON)
    (row,) = rows
    assert (row["id"], row["platform"], row["url"]) == (read["id"], "greenhouse", read_url)
    assert row["first_seen"] == "2026-10-01"
    assert row["last_seen"] == "2026-11-03"
    assert "closes_on" not in row and "submitted_in" not in row
    assert catalog.problems(rows) == []


def test_a_tracked_read_listing_absorbs_a_submitted_copy_and_its_earlier_first_seen():
    mine = submitted("https://acme.example/jobs/9", today="2026-10-01")
    tracked = record("9", today="2026-10-15", url="https://acme.example/jobs/9")
    read = record("9", today="2026-11-03", url="https://acme.example/jobs/9")
    (row,) = reconcile([tracked, mine], [ok("Acme", read)], "2026-11-03", season=SEASON)
    assert (row["id"], row["first_seen"], row["last_seen"]) == (
        tracked["id"],
        "2026-10-01",
        "2026-11-03",
    )


def test_a_read_listing_keeps_the_manual_close_of_the_submitted_listing_it_replaces():
    mine = submitted("https://acme.example/jobs/9", today="2026-10-01")
    (mine,) = close_manually([mine], mine["id"], "2026-10-20")
    read = record("9", today="2026-11-03", url="https://acme.example/jobs/9")
    rows = reconcile([mine], [ok("Acme", read)], "2026-11-03", season=SEASON)
    (row,) = rows
    assert (row["id"], row["status"], row["closed_on"], row["close_reason"]) == (
        read["id"],
        "closed",
        "2026-10-20",
        "manual",
    )
    assert row["first_seen"] == "2026-10-01"
    assert catalog.problems(rows) == []
    (row,) = reconcile(rows, [ok("Acme", read)], "2026-11-04", season=SEASON)
    assert (row["status"], row["close_reason"]) == ("closed", "manual")


@pytest.mark.parametrize(
    "submitted_url, other",
    [
        ("https://acme.example/jobs/9", {"url": "https://acme.example/jobs/10"}),
        ("https://acme.example/jobs/9", {"url": "http://acme.example/jobs/9"}),
        ("https://acme.example/Jobs/9", {"url": "https://acme.example/jobs/9"}),
        ("https://acme.example/jobs/9", {"url": "https://jobs.acme.example/jobs/9"}),
        ("https://acme.example/jobs/9", {"company": "Other"}),
    ],
    ids=["other path", "other scheme", "path case", "other host", "other company"],
)
def test_a_read_listing_with_a_different_url_or_company_does_not_replace(submitted_url, other):
    mine = submitted(submitted_url)
    read = record("9", **other)
    rows = reconcile([mine], [ok(read["company"], read)], "2026-11-03", season=SEASON)
    assert {row["platform"] for row in rows} == {"submitted", "greenhouse"}


@pytest.mark.parametrize(
    "url",
    [
        "https://ACME.example/jobs/9",
        "https://acme.example:443/jobs/9",
        "https://someone@acme.example/jobs/9",
        "https://someone:secret@Acme.Example:8443/jobs/9/apply",
    ],
)
def test_apply_url_key_uses_the_lowercased_host_without_userinfo_or_port(url):
    assert apply_url_key(url) == ("https", "acme.example", "/jobs/9")
