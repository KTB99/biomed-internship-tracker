"""Load the company registry and target season from companies.toml."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = ROOT / "companies.toml"
SEASON_PATTERN = re.compile(r"^summer-(\d{4})$")


@dataclass(frozen=True)
class Company:
    name: str
    platform: str
    careers_url: str
    params: dict = field(default_factory=dict)


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
        )
        if not company.name:
            raise ValueError("company name must not be empty")
        if company.name.lower() in seen:
            raise ValueError(f"company listed twice: {company.name}")
        if company.platform not in PLATFORMS:
            raise ValueError(f"{company.name}: unknown platform {company.platform!r}")
        if not company.careers_url.startswith("https://"):
            raise ValueError(f"{company.name}: careers_url must be https")
        seen.add(company.name.lower())
        companies.append(company)
    return Settings(season=season, companies=tuple(companies))
