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


US = "US"
MAX_PLACES_SHOWN = 3

_PLACE_PARTS = re.compile(r"[,|]")
_ZIP = re.compile(r"\b\d{5}(?:-\d{4})?\b")  # "CA 94536", "34108", "02110-1234"
_CITY_THEN_STATE = re.compile(r"(?P<city>.+?)\s+US-(?P<state>[A-Z]{2})")  # "Maple Grove US-MN"
_STATE_CODES_BY_NAME = {name.casefold(): code for code, name in STATES.items()}
_MORE = re.compile(r"\s*\(\+(?P<count>\d+) more\)$")
_OUGH = re.compile(r"ough\b")  # "Marlborough" and "Marlboro" are one town


def tidy_place(place: str) -> str:
    """One place's text for display: each component once, no ZIP codes or board placeholders.

    A US place with a state reads "City, ST, US" ("Irvine, CA 92602"
    becomes "Irvine, CA, US"); one that names only its state reads
    "ST, US", and one that names only the country "US".
    Other places keep their components as given.
    """
    parts = [" ".join(_ZIP.sub(" ", part).split()) for part in _PLACE_PARTS.split(place)]
    parts = [part for part in parts if part and part.upper() != "N/A"]
    if is_us_location(place):
        us_place = _us_place(parts)
        if us_place is not None:
            return us_place
    return ", ".join(_unique(US if is_us_country(part) else part for part in parts))


def display_location(places: list[str], *, hidden: int = 0) -> str:
    """A listing's location text: its distinct places, US first, at most
    `MAX_PLACES_SHOWN` of them, then how many more there are. `hidden` counts
    places already left out of the text these came from."""
    tidied = _unique(place for place in (tidy_place(place) for place in places) if place)
    tidied = _drop_same_places(tidied)
    ordered = sorted(tidied, key=lambda place: not is_us_location(place))  # stable: US first
    shown = "; ".join(ordered[:MAX_PLACES_SHOWN])
    more = max(len(ordered) - MAX_PLACES_SHOWN, 0) + hidden
    if more:
        shown += f" (+{more} more)"
    return shown[:300]


def tidy_location(text: str) -> str:
    """Stored location text, as `display_location` would write it today.

    Rows keep the text written when their posting was last read, so this
    brings text written by older rules up to date without reading the board.
    """
    more = _MORE.search(text)
    hidden = int(more["count"]) if more else 0
    places = text[: more.start()] if more else text
    return display_location(places.split(";"), hidden=hidden)


def _us_place(parts: list[str]) -> str | None:
    """A US place as "City, ST, US", or None when it names no state.

    The last component that is a state is the place's state. Earlier copies of
    that state are dropped, except a leading full name before a state code,
    which is the city ("New York, NY").
    """
    pieces: list[str] = []
    for part in parts:
        if is_us_country(part):
            continue
        if match := _CITY_THEN_STATE.fullmatch(part):
            pieces += [match["city"], match["state"]]
        else:
            pieces.append(part)
    if not pieces:
        return US
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
    return ", ".join([*_unique(rest), code, US])


def _drop_same_places(places: list[str]) -> list[str]:
    """Places without repeats of one another: a second spelling of the same
    town ("Marlboro, MA" after "Marlborough, MA"), or a place that only
    restates the end of a more specific one ("US" beside
    "Boston, MA, US")."""
    keys = [_OUGH.sub("o", place.casefold()) for place in places]
    kept = []
    for index, (place, key) in enumerate(zip(places, keys, strict=True)):
        if key in keys[:index]:
            continue
        if any(other.endswith(", " + key) for other in keys):
            continue
        kept.append(place)
    return kept


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
