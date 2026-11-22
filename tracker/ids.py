"""Stable listing IDs.

An ID is a UUIDv5 of the company, platform and the platform's own job ID (or the
job URL when a platform gives none). Changing this scheme changes every ID, so
existing listings would look closed and then reappear as new ones.
"""

from __future__ import annotations

import uuid

NAMESPACE = uuid.UUID("b7e3c1a2-5d64-4f8e-9c3b-2a1d0e9f7c65")


def listing_id(company: str, platform: str, external_id: str, url: str) -> str:
    company_key = " ".join(company.lower().split())
    if external_id.strip():
        key = f"{company_key}|{platform}|{external_id.strip()}"
    else:
        key = f"{company_key}|url|{url.strip()}"
    return str(uuid.uuid5(NAMESPACE, key))
