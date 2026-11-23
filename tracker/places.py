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
_ZIP = re.compile(r"\d{5}(?:-\d{4})?")
_STATE_THEN_ZIP = re.compile(r"(?P<state>[A-Z]{2})\s+\d{5}(?:-\d{4})?")  # "CA 94536"
_CITY_THEN_STATE = re.compile(r"(?P<city>.+?)\s+US-(?P<state>[A-Z]{2})")  # "Maple Grove US-MN"
_STATE_CODES_BY_NAME = {name.casefold(): code for code, name in STATES.items()}


def tidy_place(place: str) -> str:
    """One place's text for display, each component once and without board placeholders.

    A US place with a state reads "City, ST" ("Irvine, CA 92602, United States"
    becomes "Irvine, CA"); one that names only its state reads as the state's
    full name. Other places keep their components as given.
    """
    parts = [part.strip() for part in _PLACE_PARTS.split(place)]
    parts = [part for part in parts if part and part.upper() != "N/A"]
    if is_us_location(place):
        us_place = _us_place(parts)
        if us_place is not None:
            return us_place
    return ", ".join(_unique("United States" if is_us_country(part) else part for part in parts))


def _us_place(parts: list[str]) -> str | None:
    """A US place as "City, ST", or None when it names no state.

    The last component that is a state is the place's state. Earlier copies of
    that state are dropped, except a leading full name before a state code,
    which is the city ("New York, NY").
    """
    pieces: list[str] = []
    for part in parts:
        if is_us_country(part) or _ZIP.fullmatch(part):
            continue
        if match := _CITY_THEN_STATE.fullmatch(part):
            pieces += [match["city"], match["state"]]
        elif match := _STATE_THEN_ZIP.fullmatch(part):
            pieces.append(match["state"])
        else:
            pieces.append(part)
    if not pieces:
        return "United States"
    states = [index for index, piece in enumerate(pieces) if _state_code(piece)]
    if not states:
        return None
    last = states[-1]
    code = _state_code(pieces[last])
    named_city = pieces[last] == code and pieces[0].casefold() == STATES[code].casefold()
    rest = [
        piece
        for index, piece in enumerate(pieces)
        if index != last and (_state_code(piece) != code or (index == 0 and named_city))
    ]
    rest = _unique(rest)
    return ", ".join(rest + [code]) if rest else STATES[code]


def _state_code(piece: str) -> str | None:
    if piece in STATES:
        return piece
    return _STATE_CODES_BY_NAME.get(piece.casefold())


def _unique(parts) -> list[str]:
    """Parts in order, each once, ignoring case."""
    unique: dict[str, str] = {}
    for part in parts:
        unique.setdefault(part.casefold(), part)
    return list(unique.values())
