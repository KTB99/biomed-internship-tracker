"""Data passed between sources, screening and the catalog."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Lead:
    """One job posting as a source reports it, before screening.

    `description`, `department` and `term` are screening evidence only; they are
    never written to the catalog.
    """

    company: str
    platform: str
    external_id: str
    title: str
    url: str
    locations: list[str] = field(default_factory=list)
    country: str = ""
    posted_on: str | None = None
    department: str = ""
    term: str = ""
    description: str = ""
