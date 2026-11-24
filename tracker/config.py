"""Load the company registry and target season from companies.toml."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "companies.toml"
SEASON_PATTERN = re.compile(r"^summer-(\d{4})$")
# A bare lowercase hostname: dot-separated labels, no scheme, port, path or wildcard.
HOST_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")


# A company with this platform has no automated reader; only its program page is shown.
LINK_ONLY = "link"
# Platforms that don't read a company's job board: `link` reads nothing and
# `careers_page` reads only the schema.org markup a company page happens to
# carry. A submitted listing at such a company never appears in a read.
NO_JOB_BOARD_READ = frozenset({LINK_ONLY, "careers_page"})


@dataclass(frozen=True)
class Program:
    """A company's own internship page, shown when it has no open postings we can read."""

    label: str
    url: str
    location: str


@dataclass(frozen=True)
class Company:
    name: str
    platform: str
    careers_url: str
    params: dict = field(default_factory=dict)
    program: Program | None = None
    submit_hosts: tuple[str, ...] = ()
    # A short line shown under the company's role and program titles in the README.
    note: str = ""

    @property
    def link_only(self) -> bool:
        return self.platform == LINK_ONLY

    @property
    def reads_job_board(self) -> bool:
        return self.platform not in NO_JOB_BOARD_READ

    def allows_submission_url(self, url: str) -> bool:
        """True when `url` is https on one of `submit_hosts` exactly, with no userinfo or port."""
        # urlsplit silently drops some whitespace, so refuse it rather than check a different URL.
        if any(char.isspace() or not char.isprintable() for char in url):
            return False
        parts = urlsplit(url)
        if parts.scheme != "https" or "@" in parts.netloc or ":" in parts.netloc:
            return False
        return (parts.hostname or "") in self.submit_hosts


@dataclass(frozen=True)
class Settings:
    season: str
    companies: tuple[Company, ...]

    @property
    def year(self) -> int:
        return season_year(self.season)

    @property
    def season_label(self) -> str:
        return f"Summer {self.year}"


def season_year(season: str) -> int:
    match = SEASON_PATTERN.match(season)
    if not match:
        raise ValueError(f"season must look like 'summer-2027', got {season!r}")
    return int(match.group(1))


def load_settings(path: Path = REGISTRY_PATH) -> Settings:
    from tracker.sources import PLATFORMS

    raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    season = str(raw.get("season", ""))
    season_year(season)
    companies = []
    seen = set()
    for entry in raw.get("companies", []):
        company = Company(
            name=str(entry["name"]).strip(),
            platform=str(entry["platform"]).strip(),
            careers_url=str(entry["careers_url"]).strip(),
            params=dict(entry.get("params", {})),
            program=_program(entry),
            submit_hosts=_submit_hosts(entry),
            note=_note(entry),
        )
        if not company.name:
            raise ValueError("company name must not be empty")
        if company.name.lower() in seen:
            raise ValueError(f"company listed twice: {company.name}")
        if company.platform not in PLATFORMS and not company.link_only:
            raise ValueError(f"{company.name}: unknown platform {company.platform!r}")
        urls = [company.careers_url] + ([company.program.url] if company.program else [])
        if not all(url.startswith("https://") for url in urls):
            raise ValueError(f"{company.name}: careers_url and program url must be https")
        seen.add(company.name.lower())
        companies.append(company)
    return Settings(season=season, companies=tuple(companies))


def _submit_hosts(entry: dict) -> tuple[str, ...]:
    raw = entry.get("submit_hosts", [])
    name = str(entry["name"]).strip()
    if not isinstance(raw, list):
        raise ValueError(f"{name}: submit_hosts must be a list of hostnames")
    for host in raw:
        if not isinstance(host, str) or not HOST_PATTERN.fullmatch(host):
            raise ValueError(
                f"{name}: submit_hosts entry {host!r} must be a bare lowercase hostname"
            )
    return tuple(raw)


def _note(entry: dict) -> str:
    raw = entry.get("note", "")
    if not isinstance(raw, str):
        raise ValueError(f"{str(entry['name']).strip()}: note must be text")
    return raw.strip()


def _program(entry: dict) -> Program | None:
    raw = entry.get("program")
    if raw is None:
        return None
    return Program(
        label=str(raw["label"]).strip(),
        url=str(raw["url"]).strip(),
        location=str(raw.get("location", "")).strip(),
    )
