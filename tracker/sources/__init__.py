"""Platform readers. Each exposes `fetch(client, company) -> list[Lead]`.

Adding a platform: write a module here, register it in PLATFORMS, add it to the
`platform` enum in tracker/listing.schema.json, and test it with mocked HTTP.
"""

from __future__ import annotations

from collections.abc import Callable

from tracker.sources import eightfold, greenhouse, lever, phenom, smartrecruiters

PLATFORMS: dict[str, Callable] = {
    "eightfold": eightfold.fetch,
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "phenom": phenom.fetch,
    "smartrecruiters": smartrecruiters.fetch,
}


def fetch_leads(client, company) -> list:
    return PLATFORMS[company.platform](client, company)
