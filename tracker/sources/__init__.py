"""Platform readers. Each exposes `fetch(client, company) -> list[Lead]`.

Adding a platform: write a module here, register it in PLATFORMS, add it to the
`platform` enum in tracker/listing.schema.json, and test it with mocked HTTP.
The record-only platform `submitted` is in the schema enum but not in PLATFORMS,
since no reader fetches it (docs/adr/0002-submitted-listings.md).
"""

from __future__ import annotations

from collections.abc import Callable

from tracker.sources import (
    algolia,
    careers_page,
    eightfold,
    greenhouse,
    jobs2web,
    kentico,
    lever,
    oracle,
    paradox,
    phenom,
    pinpoint,
    smartrecruiters,
    talentbrew,
)

PLATFORMS: dict[str, Callable] = {
    "algolia": algolia.fetch,
    "careers_page": careers_page.fetch,
    "eightfold": eightfold.fetch,
    "greenhouse": greenhouse.fetch,
    "jobs2web": jobs2web.fetch,
    "kentico": kentico.fetch,
    "lever": lever.fetch,
    "oracle": oracle.fetch,
    "paradox": paradox.fetch,
    "phenom": phenom.fetch,
    "pinpoint": pinpoint.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "talentbrew": talentbrew.fetch,
}


def fetch_leads(client, company) -> list:
    return PLATFORMS[company.platform](client, company)
