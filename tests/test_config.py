from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pytest

from tracker.config import REGISTRY_PATH, Company, load_settings


def write_registry(tmp_path: Path, company_extra: str = "") -> Path:
    path = tmp_path / "companies.toml"
    path.write_text(
        'season = "summer-2027"\n\n'
        "[[companies]]\n"
        'name = "Acme Medical"\n'
        'platform = "careers_page"\n'
        'careers_url = "https://www.acme.example/careers"\n'
        'params = { page = "https://www.acme.example/careers" }\n'
        f"{company_extra}",
        encoding="utf-8",
    )
    return path


def load_company(tmp_path: Path, company_extra: str = ""):
    (company,) = load_settings(write_registry(tmp_path, company_extra)).companies
    return company


def test_submit_hosts_load_from_the_registry(tmp_path):
    company = load_company(
        tmp_path, 'submit_hosts = ["acme.wd5.myworkdayjobs.com", "www.acme.example"]\n'
    )

    assert company.submit_hosts == ("acme.wd5.myworkdayjobs.com", "www.acme.example")


def test_submit_hosts_default_to_empty(tmp_path):
    assert load_company(tmp_path).submit_hosts == ()


@pytest.mark.parametrize(
    "entry",
    [
        '"https://acme.wd5.myworkdayjobs.com"',
        '"acme.wd5.myworkdayjobs.com/en-US/careers"',
        '"acme.wd5.myworkdayjobs.com:443"',
        '"*.myworkdayjobs.com"',
        '"user@acme.wd5.myworkdayjobs.com"',
        '"Acme.wd5.myworkdayjobs.com"',
        '" acme.wd5.myworkdayjobs.com"',
        '""',
        '"acme..myworkdayjobs.com"',
        "5",
    ],
)
def test_a_submit_host_must_be_a_bare_lowercase_hostname(tmp_path, entry):
    with pytest.raises(ValueError, match="Acme Medical"):
        load_company(tmp_path, f"submit_hosts = [{entry}]\n")


def test_submit_hosts_must_be_a_list(tmp_path):
    with pytest.raises(ValueError, match="Acme Medical"):
        load_company(tmp_path, 'submit_hosts = "acme.wd5.myworkdayjobs.com"\n')


MEDTRONIC_HOST = "medtronic.wd1.myworkdayjobs.com"
POSTING = "/en-US/MedtronicCareers/job/Minneapolis/Engineering-Intern_R12345"


def submitter(*hosts: str) -> Company:
    return Company(
        name="Medtronic",
        platform="careers_page",
        careers_url="https://www.medtronic.com/en-us/our-company/careers.html",
        submit_hosts=hosts,
    )


@pytest.mark.parametrize(
    "url",
    [
        f"https://{MEDTRONIC_HOST}{POSTING}",
        f"https://MedTronic.WD1.myworkdayjobs.com{POSTING}",
        f"https://{MEDTRONIC_HOST}{POSTING}?source=LinkedIn",
    ],
)
def test_a_submission_url_on_an_allowed_host_is_accepted(url):
    assert submitter(MEDTRONIC_HOST, "www.medtronic.com").allows_submission_url(url)


@pytest.mark.parametrize(
    "url",
    [
        f"https://{MEDTRONIC_HOST}.evil.example{POSTING}",
        f"https://evil.myworkdayjobs.com{POSTING}",
        f"https://wd1.myworkdayjobs.com{POSTING}",
        f"https://jobs.{MEDTRONIC_HOST}{POSTING}",
        f"http://{MEDTRONIC_HOST}{POSTING}",
        f"https://x@{MEDTRONIC_HOST}{POSTING}",
        f"https://x:pw@{MEDTRONIC_HOST}{POSTING}",
        f"https://{MEDTRONIC_HOST}:443{POSTING}",
        f"https://{MEDTRONIC_HOST}:8443{POSTING}",
        f"https://{MEDTRONIC_HOST}.{POSTING}",
        f"//{MEDTRONIC_HOST}{POSTING}",
        f"{MEDTRONIC_HOST}{POSTING}",
        f"javascript://{MEDTRONIC_HOST}/%0aalert(1)",
        f" https://{MEDTRONIC_HOST}{POSTING}",
        f"https://{MEDTRONIC_HOST}\n{POSTING}",
        f"https://{MEDTRONIC_HOST}{POSTING}\t",
        f"https://{MEDTRONIC_HOST}/a b",
        "",
    ],
)
def test_a_submission_url_off_the_allowed_hosts_is_rejected(url):
    assert not submitter(MEDTRONIC_HOST).allows_submission_url(url)


def test_a_company_without_submit_hosts_allows_no_submission():
    assert not submitter().allows_submission_url(f"https://{MEDTRONIC_HOST}{POSTING}")


WORKDAY_HOSTS = {
    "Alcon": "alcon.wd5.myworkdayjobs.com",
    "Globus Medical": "globusmedical.wd5.myworkdayjobs.com",
    "Insulet": "insulet.wd5.myworkdayjobs.com",
    "Medtronic": "medtronic.wd1.myworkdayjobs.com",
    "ResMed": "resmed.wd3.myworkdayjobs.com",
    "Smith+Nephew": "smithnephew.wd5.myworkdayjobs.com",
    "Tandem": "tandemdiabetes.wd12.myworkdayjobs.com",
}


@pytest.mark.parametrize("name, workday_host", sorted(WORKDAY_HOSTS.items()))
def test_each_workday_only_company_accepts_submissions_from_its_workday_host(name, workday_host):
    companies = {company.name: company for company in load_settings(REGISTRY_PATH).companies}
    company = companies[name]

    assert workday_host in company.submit_hosts
    assert urlsplit(company.careers_url).hostname in company.submit_hosts
    assert company.allows_submission_url(f"https://{workday_host}/en-US/careers/job/Intern_R1")
