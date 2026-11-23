"""Read free-text job locations: whether a place is in the United States, and its display text."""

from __future__ import annotations

import re

STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
    "PR": "Puerto Rico",
}  # fmt: skip

_COUNTRY_WORDS = re.compile(r"\bunited states(?: of america)?\b|\bu\.s\.(?:a\.)?", re.IGNORECASE)
_COUNTRY_CODES = re.compile(r"\b(?:US|USA)\b")
_STATE_CODE = re.compile(r"(?:,\s*|\bUS-)(?:" + "|".join(STATES) + r")\b")
_STATE_NAME = re.compile(
    r"\b(?:" + "|".join(re.escape(name) for name in STATES.values()) + r")\b", re.IGNORECASE
)
# Places whose names contain a US state name ("Baja California", "Georgia" the country).
_FOREIGN = re.compile(
    r"\b(?:canada|mexico|méxico|costa rica|ireland|united kingdom|england|germany|"
    r"netherlands|switzerland|france|india|china|japan|singapore|malaysia|australia|"
    r"israel|poland|brazil|tbilisi)\b",
    re.IGNORECASE,
)
_TWO_LETTERS = re.compile(r"[A-Za-z]{2}")


def names_us(location: str) -> bool:
    """True when the text names the country itself, not just a state."""
    return bool(_COUNTRY_WORDS.search(location) or _COUNTRY_CODES.search(location))


def is_us_location(location: str) -> bool:
    if not location:
        return False
    country = _trailing_country_code(location)
    if country:
        return country == "US"
    if names_us(location):
        return True
    if _FOREIGN.search(location):
        return False
    return bool(_STATE_CODE.search(location) or _STATE_NAME.search(location))


def _trailing_country_code(location: str) -> str | None:
    """The country code ending a "City, Region, CC" place, if it has one.

    Two-part places ("Pune, IN") are left alone: there the code could be a
    state or a country, and the lead's country field decides. A trailing US
    state code is a state ("Cleveland, Bolivar, MS") unless the part before it
    is itself a two-letter region code ("Quebec, QC, CA").
    """
    parts = [part.strip() for part in location.split(",")]
    if len(parts) < 3 or not _TWO_LETTERS.fullmatch(parts[-1]):
        return None
    code = parts[-1].upper()
    if code in STATES and not _TWO_LETTERS.fullmatch(parts[-2]):
        return None
    return code


def is_us_country(country: str) -> bool:
    return country.strip().upper() in {"US", "USA", "UNITED STATES", "UNITED STATES OF AMERICA"}


_PLACE_PARTS = re.compile(r"[,|]")


def tidy_place(place: str) -> str:
    """One place's text for display: each component once, without board placeholders."""
    parts: list[str] = []
    seen: set[str] = set()
    for part in _PLACE_PARTS.split(place):
        part = part.strip()
        if not part or part.upper() == "N/A":
            continue
        if is_us_country(part):
            part = "United States"
        if part.casefold() in seen:
            continue
        seen.add(part.casefold())
        parts.append(part)
    return ", ".join(parts)
