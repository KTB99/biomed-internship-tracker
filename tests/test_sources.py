import pytest
from conftest import FakeResponse, company, fake_client

from tracker.http import SourceError
from tracker.sources import PLATFORMS, fetch_leads


def test_greenhouse_reads_board_with_content():
    payload = {
        "jobs": [
            {
                "id": 4001,
                "title": "R&D Engineering Intern",
                "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/4001",
                "location": {"name": "Plymouth, MN"},
                "first_published": "2026-10-02T09:00:00-05:00",
                "departments": [{"name": "Research & Development"}],
                "content": (
                    "&lt;p&gt;Design &amp;amp; test.&lt;/p&gt;&lt;script&gt;x()&lt;/script&gt;"
                ),
            },
            {"id": 4002, "title": "", "absolute_url": "https://x"},
        ]
    }
    client, session = fake_client(lambda *args: FakeResponse(payload))
    leads = fetch_leads(client, company(platform="greenhouse", board="acme"))
    assert [lead.title for lead in leads] == ["R&D Engineering Intern"]
    lead = leads[0]
    assert lead.external_id == "4001"
    assert lead.locations == ["Plymouth, MN"]
    assert lead.posted_on == "2026-10-02"
    assert lead.department == "Research & Development"
    assert lead.description == "Design & test."
    method, url, kwargs = session.calls[0]
    assert url == "https://boards-api.greenhouse.io/v1/boards/acme/jobs"
    assert kwargs["params"] == {"content": "true"}


def test_lever_uses_all_locations_and_commitment():
    payload = [
        {
            "id": "abc-123",
            "text": "Mechanical Engineering Intern",
            "hostedUrl": "https://jobs.lever.co/acme/abc-123",
            "createdAt": 1793491200000,
            "country": "US",
            "categories": {
                "location": "Alameda, CA",
                "allLocations": ["Alameda, CA", "Roseville, CA"],
                "team": "Engineering",
                "commitment": "Intern",
            },
            "descriptionPlain": "Summer role.",
            "lists": [{"text": "Requirements", "content": "<li>Pursuing a BS</li>"}],
        }
    ]
    client, _ = fake_client(lambda *args: FakeResponse(payload))
    (lead,) = fetch_leads(client, company(platform="lever", site="acme"))
    assert lead.locations == ["Alameda, CA", "Roseville, CA"]
    assert lead.country == "US"
    assert lead.term == "Intern"
    assert lead.department == "Engineering"
    assert lead.posted_on == "2026-11-01"
    assert "Pursuing a BS" in lead.description


def test_lever_rejects_unexpected_shape():
    client, _ = fake_client(lambda *args: FakeResponse({"error": "nope"}))
    with pytest.raises(SourceError):
        fetch_leads(client, company(platform="lever", site="acme"))


def test_smartrecruiters_pages_and_dedupes_across_terms():
    def posting(job_id, title):
        return {
            "id": job_id,
            "name": title,
            "releasedDate": "2026-09-30T12:00:00.000Z",
            "location": {"city": "Sunnyvale", "region": "CA", "country": "us", "remote": False},
            "department": {"label": "Engineering"},
            "typeOfEmployment": {"label": "Intern"},
        }

    def handler(method, url, kwargs):
        params = kwargs["params"]
        if params["q"] == "intern":
            pages = {
                0: [posting("1", "Robotics Intern"), posting("2", "Software Intern")],
                2: [posting("3", "Data Intern")],
            }
            return FakeResponse({"totalFound": 3, "content": pages[params["offset"]]})
        return FakeResponse({"totalFound": 1, "content": [posting("2", "Software Intern")]})

    client, session = fake_client(handler)
    leads = fetch_leads(client, company(platform="smartrecruiters", company_id="Acme"))
    assert sorted(lead.external_id for lead in leads) == ["1", "2", "3"]
    assert len(session.calls) == 4  # two pages for "intern", one each for the other terms
    lead = next(lead for lead in leads if lead.external_id == "1")
    assert lead.url == "https://jobs.smartrecruiters.com/Acme/1"
    assert lead.locations == ["Sunnyvale, CA, us"]
    assert lead.country == "us"


def test_eightfold_builds_urls_on_the_origin():
    payload = {
        "data": {
            "count": 2,
            "positions": [
                {
                    "id": 77,
                    "atsJobId": "JR-1",
                    "name": "Firmware Intern",
                    "locations": ["San Diego, CA, US"],
                    "standardizedLocations": ["US-CA"],
                    "department": "Engineering",
                    "positionUrl": "/careers/job/77",
                    "postedTs": 1790000000,
                },
                {
                    "id": 78,
                    "name": "Sneaky Intern",
                    "standardizedLocations": ["Marlborough US-MA, United States | N/A"],
                    "positionUrl": "https://evil.example/phish",
                },
            ],
        }
    }

    def handler(method, url, kwargs):
        if kwargs["params"]["query"] == "intern":
            return FakeResponse(payload)
        return FakeResponse({"data": {"count": 0, "positions": []}})

    client, session = fake_client(handler)
    leads = fetch_leads(
        client,
        company(platform="eightfold", origin="https://careers.acme.example", domain="acme.com"),
    )
    by_id = {lead.external_id: lead for lead in leads}
    assert by_id["JR-1"].url == "https://careers.acme.example/careers/job/77"
    assert by_id["JR-1"].locations == ["San Diego, CA, US"]
    assert by_id["78"].locations == ["Marlborough US-MA, United States | N/A"]
    assert by_id["78"].url == "https://careers.acme.example/careers/job/78"
    assert session.calls[0][2]["params"]["domain"] == "acme.com"


def test_phenom_posts_search_and_stops_when_nothing_new():
    job = {
        "title": "Quality Engineering Intern",
        "jobId": "R-9",
        "applyUrl": "https://acme.wd1.myworkdayjobs.com/en-US/acme/job/R-9/apply",
        "cityStateCountry": "Temecula, California, United States of America",
        "country": "United States of America",
        "category": "Engineering",
        "type": "Intern",
        "postedDate": "2026-10-20T00:00:00.000+0000",
    }
    # This server ignores the offset, so every page repeats.
    client, session = fake_client(
        lambda *args: FakeResponse({"refineSearch": {"data": {"jobs": [job]}}})
    )
    leads = fetch_leads(client, company(platform="phenom", origin="https://jobs.acme.example"))
    assert [lead.external_id for lead in leads] == ["R-9"]
    assert len(session.calls) == 6  # two pages for each of the three search terms
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("POST", "https://jobs.acme.example/widgets")
    assert kwargs["json"]["keywords"] == "intern"
    assert kwargs["headers"]["Origin"] == "https://jobs.acme.example"


def test_missing_parameter_is_a_clear_error():
    client, _ = fake_client(lambda *args: FakeResponse([]))
    with pytest.raises(ValueError, match="board"):
        fetch_leads(client, company(platform="greenhouse"))


def test_every_platform_is_registered_and_in_the_schema():
    from tracker.catalog import SCHEMA

    # `submitted` is a record platform (a maintainer added the listing), not a reader.
    assert "submitted" not in PLATFORMS
    assert set(PLATFORMS) | {"submitted"} == set(SCHEMA["properties"]["platform"]["enum"])
