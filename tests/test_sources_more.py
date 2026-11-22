"""Readers for Oracle, Pinpoint, TalentBrew, jobs2web, Kentico, Paradox, careers pages, Algolia."""

import json

import pytest
from conftest import FakeResponse, company, fake_client

from tracker.http import SourceError
from tracker.sources import fetch_leads
from tracker.sources._common import job_id_from_url, search_terms


def only(term="intern", **params):
    """Company params that search a single term, keeping call counts simple."""
    return {"search_terms": [term], **params}


def test_search_terms_default_and_override():
    assert search_terms(company()) == ("intern", "internship", "co-op")
    assert search_terms(company(search_terms=["summer 2027"])) == ("summer 2027",)
    with pytest.raises(ValueError):
        search_terms(company(search_terms=[" "]))


def test_job_id_from_url():
    assert job_id_from_url("https://x.example/job/Naples-Intern-FL/1373642157/") == "1373642157"
    assert job_id_from_url("https://x.example/job/abc") == "https://x.example/job/abc"


def test_oracle_pages_through_requisitions():
    def requisition(job_id, title, place="Marlborough, MA, United States"):
        return {
            "Id": job_id,
            "Title": title,
            "PrimaryLocation": place,
            "PrimaryLocationCountry": "US",
            "PostedDate": "2026-11-04",
            "JobFamily": "Engineering",
            "ExternalQualificationsStr": "<ul><li>Pursuing a BS</li></ul>",
        }

    def handler(method, url, kwargs):
        offset = int(kwargs["params"]["finder"].split("offset=")[1].split(",")[0])
        batch = {0: [requisition(str(n), f"Intern {n}") for n in range(25)], 25: []}[offset]
        if offset == 0:
            batch[0] = requisition("0", "R&D Engineering Intern")
        return FakeResponse({"items": [{"TotalJobsCount": 26, "requisitionList": batch}]})

    client, session = fake_client(handler)
    leads = fetch_leads(
        client,
        company(platform="oracle", **only(origin="https://acme.fa.us2.oraclecloud.com", site="CX")),
    )
    assert len(leads) == 25 and len(session.calls) == 2
    lead = next(item for item in leads if item.external_id == "0")
    assert lead.url == (
        "https://acme.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/0"
    )
    assert (lead.country, lead.posted_on, lead.department) == ("US", "2026-11-04", "Engineering")
    assert "Pursuing a BS" in lead.description
    finder = session.calls[0][2]["params"]["finder"]
    assert finder == "findReqs;siteNumber=CX,keyword=intern,offset=0,limit=25"


def test_pinpoint_reads_board_and_tidies_locations():
    payload = {
        "data": [
            {
                "id": 538,
                "title": "Software Engineering Intern",
                "url": "https://jobs.acme.example/en/jobs/538",
                "location": {"name": "US-California-San Jose"},
                "department": {"name": "Engineering"},
                "employment_type_text": "Internship",
                "description": "<p>Summer role</p>",
            },
            {"id": 539, "title": "No URL"},
        ]
    }
    client, _ = fake_client(lambda *args: FakeResponse(payload))
    (lead,) = fetch_leads(
        client, company(platform="pinpoint", jobs_url="https://jobs.acme.example/jobs.json")
    )
    assert lead.locations == ["San Jose, California, US"]
    assert (lead.external_id, lead.department, lead.term) == ("538", "Engineering", "Internship")


LINK_INSIDE_LOCATION_INSIDE = """
<section id="search-results" data-total-pages="2">
  <ul>
    <li><a href="/en/job/deerfield/engineering-intern/152/101" data-job-id="101">
      <h2>Engineering Intern</h2><span class="job-location">Deerfield, IL</span></a></li>
    <li><a href="/en/job/remote/data-intern/152/102" data-job-id="102">
      <h2>Data Intern</h2><span class="job-location">Remote</span></a></li>
  </ul>
</section>
"""
LOCATION_AFTER_LINK = """
<section id="search-results" data-total-pages="2">
  <li class="search-results-list__item">
    <button data-job-id="201">Save Job</button>
    <h2><a class="search-results-list__job-link" href="/en/job/sandy/quality-intern/159/201"
        data-job-id="201">Quality Intern</a></h2>
    <ul><li class="search-results-list__job-info job-location"> Sandy, UT </li></ul>
  </li>
</section>
"""


def test_talentbrew_handles_both_result_layouts_and_pages():
    pages = {1: LINK_INSIDE_LOCATION_INSIDE, 2: LOCATION_AFTER_LINK}

    def handler(method, url, kwargs):
        return FakeResponse({"results": pages[kwargs["params"]["CurrentPage"]], "hasJobs": True})

    client, session = fake_client(handler)
    leads = fetch_leads(
        client, company(platform="talentbrew", **only(origin="https://jobs.acme.example"))
    )
    by_id = {lead.external_id: lead for lead in leads}
    assert by_id["101"].title == "Engineering Intern"
    assert by_id["101"].locations == ["Deerfield, IL"]
    assert by_id["101"].url.endswith("/en/job/deerfield/engineering-intern/152/101")
    assert by_id["101"].url.startswith("https://jobs.acme.example/")
    assert by_id["201"].title == "Quality Intern" and by_id["201"].locations == ["Sandy, UT"]
    assert len(session.calls) == 2
    assert session.calls[0][2]["headers"]["X-Requested-With"] == "XMLHttpRequest"


def test_talentbrew_without_results_html_is_a_source_error():
    client, _ = fake_client(lambda *args: FakeResponse({"filters": []}))
    with pytest.raises(SourceError):
        fetch_leads(client, company(platform="talentbrew", origin="https://jobs.acme.example"))


JOBS2WEB_TABLE = """
<table><tr class="data-row">
  <td class="colTitle"><span class="jobTitle hidden-phone">
    <a href="/job/Olive-Branch-Industrial-Engineer-Intern-MS/1433767400/" class="jobTitle-link">
      Industrial Engineer Intern</a></span>
    <div class="visible-phone"><span class="jobTitle visible-phone">
      <a class="jobTitle-link" href="/job/Olive-Branch-Industrial-Engineer-Intern-MS/1433767400/">
        Industrial Engineer Intern</a></span>
      <span class="jobLocation visible-phone"><span class="jobLocation"> Olive Branch, MS, US
      </span></span></div></td>
  <td class="colLocation"><span class="jobLocation"> Olive Branch, MS, US </span></td>
</tr></table>
"""
JOBS2WEB_TILES = """
<a class="jobTitle-link"
   href="/NorthAmerica/job/Naples-Technical-Artist-Intern-FL-34108/1373642157/">
  Technical Artist Intern </a>
<div id="job-1373642157-desktop-section-customfield1-value">Marketing</div>
<div id="job-1373642157-desktop-section-location-value">Naples, FL, US, 34108 </div>
"""


@pytest.mark.parametrize(
    "html, job_id, title, location",
    [
        (JOBS2WEB_TABLE, "1433767400", "Industrial Engineer Intern", "Olive Branch, MS, US"),
        (JOBS2WEB_TILES, "1373642157", "Technical Artist Intern", "Naples, FL, US, 34108"),
    ],
)
def test_jobs2web_layouts(html, job_id, title, location):
    pages = [html, ""]
    client, session = fake_client(lambda *args: FakeResponse(body=pages.pop(0)))
    (lead,) = fetch_leads(
        client, company(platform="jobs2web", **only(origin="https://careers.acme.example"))
    )
    assert (lead.external_id, lead.title, lead.locations) == (job_id, title, [location])
    assert lead.url.startswith("https://careers.acme.example/")
    assert session.calls[1][2]["params"] == {"q": "intern", "startrow": "1"}


KENTICO_TABLE = """
<div data-partial-count> 2 results found </div>
<table class="table-fixed job-search-table w-full">
  <thead><tr><th>Title</th><th>Job ID</th><th>Category</th><th>Location</th></tr></thead>
  <tbody>
    <tr class="job-search-row">
      <td><a href="https://acme.wd1.myworkdayjobs.com/Careers/job/R-1" class="job-search-link">
        R&amp;D Intern</a></td>
      <td>JR-1</td><td>Science &amp; Engineering</td><td><div>Princeton, New Jersey, US</div></td>
    </tr>
    <tr class="job-search-row">
      <td><a href="javascript:void(0)">Bad link</a></td><td>JR-2</td><td>x</td><td>y</td>
    </tr>
  </tbody>
</table>
<div data-partial-pagination></div>
"""


def test_kentico_reads_results_table():
    client, session = fake_client(lambda *args: FakeResponse(body=KENTICO_TABLE))
    (lead,) = fetch_leads(
        client,
        company(
            platform="kentico",
            **only(origin="https://www.acme.example", page_url="/careers/job-search"),
        ),
    )
    assert (lead.external_id, lead.title, lead.department) == (
        "JR-1",
        "R&D Intern",
        "Science & Engineering",
    )
    assert lead.locations == ["Princeton, New Jersey, US"]
    assert session.calls[0][2]["params"] == {
        "pageUrl": "/careers/job-search",
        "page": 1,
        "keyword": "intern",
    }


def paradox_page(jobs):
    state = json.dumps({"jobSearch": {"totalJob": len(jobs), "jobs": jobs}})
    return f"<html><script>window.__PRELOAD_STATE__ = {state};\nwindow.other = 1;</script></html>"


def test_paradox_reads_preloaded_state_across_terms():
    job = {
        "title": "Summer 2027 Internship - Regulatory Affairs - Arizona",
        "applyURL": "https://acme.wd1.myworkdayjobs.com/Careers/job/Tempe/R572939",
        "requisitionID": "R572939",
        "locations": [{"locationParsedText": "Tempe, AZ 85280, United States"}],
    }
    client, session = fake_client(lambda *args: FakeResponse(body=paradox_page([job])))
    leads = fetch_leads(
        client,
        company(
            platform="paradox",
            origin="https://careers.acme.example",
            search_terms=["intern", "summer 2027"],
        ),
    )
    assert [lead.external_id for lead in leads] == ["R572939"]
    assert leads[0].locations == ["Tempe, AZ 85280, United States"]
    assert [call[2]["params"]["keyword"] for call in session.calls] == ["intern", "summer 2027"]


def test_paradox_without_state_is_a_source_error():
    client, _ = fake_client(lambda *args: FakeResponse(body="<html>maintenance</html>"))
    with pytest.raises(SourceError, match="no preloaded"):
        fetch_leads(client, company(platform="paradox", origin="https://careers.acme.example"))


CAREERS_PAGE = """
<html><head>
<script type="application/ld+json">{"@type": "Organization"}</script>
<script type="application/ld+json">{"@graph": [{
  "@type": "JobPosting",
  "title": "Mechanical Engineering Intern",
  "url": "https://acme.wd5.myworkdayjobs.com/en-US/acme/job/R-10",
  "identifier": {"@type": "PropertyValue", "value": "R-10"},
  "datePosted": "2026-10-15",
  "employmentType": ["INTERN"],
  "jobLocation": {"@type": "Place", "address": {"addressLocality": "Minneapolis",
    "addressRegion": "MN", "addressCountry": "US"}},
  "description": "&lt;p&gt;Summer 2027&lt;/p&gt;"
}]}</script>
<script type="application/ld+json">not json</script>
</head></html>
"""


def test_careers_page_reads_job_posting_markup():
    client, _ = fake_client(lambda *args: FakeResponse(body=CAREERS_PAGE))
    (lead,) = fetch_leads(
        client, company(platform="careers_page", page="https://www.acme.example/careers")
    )
    assert (lead.external_id, lead.title, lead.country) == (
        "R-10",
        "Mechanical Engineering Intern",
        "US",
    )
    assert lead.locations == ["Minneapolis, MN, US"]
    assert lead.posted_on == "2026-10-15" and lead.term == "INTERN"


def test_careers_page_without_postings_returns_nothing():
    client, _ = fake_client(lambda *args: FakeResponse(body="<html><p>Apply on Workday</p></html>"))
    assert fetch_leads(client, company(platform="careers_page", page="https://acme.example")) == []


def test_algolia_queries_index_with_site_key():
    hit = {
        "objectID": "R-55",
        "JobPostingTitle": "Engineering Intern",
        "ApplyUrl": "https://acme.wd5.myworkdayjobs.com/acme/job/R-55/apply",
        "Location": "Irvine, CA",
        "Country": "United States",
        "Category": "Engineering",
    }
    client, session = fake_client(
        lambda *args: FakeResponse({"results": [{"hits": [hit], "nbPages": 1}]})
    )
    (lead,) = fetch_leads(
        client,
        company(
            platform="algolia",
            **only(app_id="ABC123XYZ", search_key="public-search-key", index="Jobs"),
        ),
    )
    assert (lead.external_id, lead.locations, lead.country) == (
        "R-55",
        ["Irvine, CA"],
        "United States",
    )
    method, url, kwargs = session.calls[0]
    assert url == "https://abc123xyz-dsn.algolia.net/1/indexes/*/queries"
    assert kwargs["headers"]["X-Algolia-API-Key"] == "public-search-key"
    assert kwargs["json"]["requests"][0]["indexName"] == "Jobs"


def test_algolia_rejects_odd_app_ids():
    client, _ = fake_client(lambda *args: FakeResponse({}))
    with pytest.raises(ValueError, match="app_id"):
        fetch_leads(
            client,
            company(platform="algolia", app_id="evil.example/x", search_key="k", index="Jobs"),
        )
