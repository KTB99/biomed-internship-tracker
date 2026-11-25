"""Decide whether a lead is a US STEM summer internship for the target year.

These are deterministic keyword rules, deliberately conservative: a lead must
show positive evidence for every check. Rejections carry reasons so they can be
reviewed in logs/screening.json after a refresh.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from tracker.models import Lead
from tracker.places import is_us_country, is_us_location, names_us

# Order matters: the first family whose pattern matches the title wins.
FAMILY_RULES: tuple[tuple[str, re.Pattern], ...] = (
    (
        "Data & AI",
        re.compile(
            r"\bdata\b|(?:machine|deep|reinforcement) learning|\bml\b|\bai\b|"
            r"artificial intelligence|analytics|business intelligence|computer vision|statistic|"
            r"\bnlp\b",
            re.IGNORECASE,
        ),
    ),
    (
        "Software & IT",
        re.compile(
            r"software|developer|programm|information technology|cyber|cloud|devops|\bweb\b|"
            r"full[- ]stack",
            re.IGNORECASE,
        ),
    ),
    (
        "Electrical & Firmware",
        re.compile(
            r"electrical|firmware|embedded|hardware|electronic|\bsignal|\brf\b|\bfpga\b|circuit",
            re.IGNORECASE,
        ),
    ),
    (
        "Mechanical & Robotics",
        re.compile(r"mechanical|robotic|mechatronic|\bcad\b|thermal|fluid", re.IGNORECASE),
    ),
    (
        "Clinical & Regulatory",
        re.compile(r"clinical|regulatory|medical affairs|\bpharmacovigilance", re.IGNORECASE),
    ),
    (
        "Quality & Manufacturing",
        re.compile(
            r"quality|manufactur|process (?:engineer|development)|operations engineer|"
            r"reliability|supplier|supply chain|validation|sterili",
            re.IGNORECASE,
        ),
    ),
    (
        "R&D & Biomedical",
        re.compile(
            r"r\s?&\s?d|research|biomedical|bioengineer|biolog|chemi|scien|laborator|\blab\b|"
            r"material|optic|imaging|product development|systems engineer|test engineer|"
            r"design engineer|translational|informatics|toxicolog|pharmaco|pharmaceutic|"
            r"patholog|genom|\bgene(?:s|tic)?\b|immunolog|oncolog|inflammation|antibod|"
            r"protein|\bcells?\b|in vivo|in vitro|spectromet|computational|discovery|"
            r"\bdrug\b|formulation|analytical|bioprocess|biologics|vaccine",
            re.IGNORECASE,
        ),
    ),
)
SOFTWARE_FAMILY = "Software & IT"
OTHER_FAMILY = "Other STEM"
FAMILIES = tuple(name for name, _ in FAMILY_RULES) + (OTHER_FAMILY,)

_GENERAL_STEM = re.compile(r"engineer|technical|technolog|\bstem\b|physics|mathemat", re.I)
# "IT" only counts in capitals, so the word "it" in prose is not evidence.
_IT = re.compile(r"\bIT\b")
_NON_STEM = re.compile(
    r"financ|accounting|accountant|\baudit|\btax\b|treasury|marketing|\bsales\b|commercial|"
    r"business development|\bbrand|human resources|\bhr\b|\bpeople\b|"
    r"talent (?:acquisition|management)|recruit|"
    r"communications|public relations|\blegal\b|\blaw\b|paralegal|procurement|purchasing|"
    r"customer (?:service|experience)|graphic design|social media",
    re.IGNORECASE,
)
_NON_STEM_EXCEPTIONS = re.compile(r"business (?:intelligence|analytics|systems)", re.IGNORECASE)

_INTERN = re.compile(r"\bintern(?:s|ship|ships)?\b", re.IGNORECASE)
_CO_OP = re.compile(r"\bco-?op\b", re.IGNORECASE)
_NOT_A_PLACEMENT = re.compile(
    r"new grad|graduate program|full[- ]time|"
    r"\b(?:intern(?:ship)?|program)s?\s+(?:manager|coordinator|director|specialist|lead)\b",
    re.IGNORECASE,
)
# DoD SkillBridge places service members leaving the military; it isn't a student internship.
_SKILLBRIDGE = re.compile(r"\bskill[- ]?bridge\b", re.IGNORECASE)
_YEAR = re.compile(r"\b20\d{2}\b")
_OFF_SEASON = re.compile(
    r"\b(?:fall|autumn|spring|winter|semester)\b|\b(?:6|six|8|eight)[- ]month", re.IGNORECASE
)
_SUMMER = re.compile(r"\bsummer\b", re.IGNORECASE)
_PHD = re.compile(r"\bph\.?\s?d\b|doctoral|post-?doc", re.IGNORECASE)
_REQUIRED = re.compile(
    r"\b(?:must|requires?|required|currently (?:pursuing|enrolled)|enrolled in)\b", re.IGNORECASE
)
_OTHER_DEGREE_WORDS = re.compile(r"bachelor|master|undergrad", re.IGNORECASE)
_OTHER_DEGREE_CODES = re.compile(r"\b(?:B\.?S|M\.?S|B\.?A|M\.?Eng)\b")
_SENTENCE_BREAK = re.compile(r"(?<=[.;!?])\s+|\n+")

# Degree level, read from the title only: descriptions list "BS, MS or PhD" too
# often to say who a posting is for.
UNDERGRAD, GRAD, ANY_LEVEL = "undergrad", "grad", "any"
_UNDERGRAD_LEVEL = re.compile(
    r"\bunder-?grad(?:uate)?s?\b|\bbachelor|\bcommunity college\b", re.IGNORECASE
)
_UNDERGRAD_CODES = re.compile(r"\bB\.?S\b")
_GRAD_LEVEL = re.compile(
    r"\bgrad(?:uate)?s?\b|\bmaster(?:['’]?s\b| of\b)|\bmba\b|\bph\.?\s?d\b|doctoral",
    re.IGNORECASE,
)
_GRAD_CODES = re.compile(r"\bM\.?S\b|\bM\.?Eng\b")


@dataclass(frozen=True)
class Verdict:
    accepted: bool
    family: str
    reasons: tuple[str, ...] = ()


def screen(lead: Lead, *, year: int) -> Verdict:
    reasons = [
        reason
        for reason in (
            _placement_problem(lead),
            _location_problem(lead),
            _stem_problem(lead),
            _season_problem(lead, year),
            _degree_problem(lead),
        )
        if reason
    ]
    return Verdict(accepted=not reasons, family=family_for(lead), reasons=tuple(reasons))


def family_for(lead: Lead) -> str:
    for text in (lead.title, lead.department):
        for name, pattern in FAMILY_RULES:
            if pattern.search(text) or (name == SOFTWARE_FAMILY and _IT.search(text)):
                return name
    return OTHER_FAMILY


def level_for(title: str) -> str:
    """Who a posting's title says it is for: undergrad, grad, or any when it
    names neither or both ("BS/MS Intern")."""
    undergrad = bool(_UNDERGRAD_LEVEL.search(title) or _UNDERGRAD_CODES.search(title))
    # "Under-graduate" would otherwise also read as "graduate".
    rest = _UNDERGRAD_LEVEL.sub(" ", title)
    grad = bool(_GRAD_LEVEL.search(rest) or _GRAD_CODES.search(rest))
    if undergrad == grad:
        return ANY_LEVEL
    return UNDERGRAD if undergrad else GRAD


def _placement_problem(lead: Lead) -> str | None:
    if not (_INTERN.search(lead.title) or _CO_OP.search(lead.title)):
        return "title is not an internship or co-op"
    if _NOT_A_PLACEMENT.search(lead.title):
        return "title is a full-time or program-staff role"
    if _SKILLBRIDGE.search(lead.title):
        return "title is a SkillBridge placement"
    return None


def _location_problem(lead: Lead) -> str | None:
    if is_us_country(lead.country):
        return None
    if any(is_us_location(place) for place in lead.locations):
        # A non-US country field outweighs a bare state-like code ("Pune, IN").
        if lead.country and not any(names_us(place) for place in lead.locations):
            return f"country is {lead.country}"
        return None
    return "no US location"


def _stem_problem(lead: Lead) -> str | None:
    for text in (lead.title, lead.department):
        if not text:
            continue
        if _NON_STEM.search(text) and not _NON_STEM_EXCEPTIONS.search(text):
            return "non-STEM role"
        if _is_stem(text):
            return None
    return "no STEM evidence in title or department"


def _is_stem(text: str) -> bool:
    return bool(
        _IT.search(text)
        or _GENERAL_STEM.search(text)
        or any(pattern.search(text) for _, pattern in FAMILY_RULES)
    )


def _season_problem(lead: Lead, year: int) -> str | None:
    # Only the title and the platform's term field are trusted for dates;
    # descriptions mention graduation years and past programs too often.
    text = f"{lead.title} {lead.term}"
    years = {int(found) for found in _YEAR.findall(text)}
    if years and year not in years:
        return f"term year {', '.join(str(y) for y in sorted(years))} is not {year}"
    # "Spring and Summer" or "Summer/Fall" still covers the summer.
    if _OFF_SEASON.search(text) and not _SUMMER.search(text):
        return "not a summer term"
    if (
        _CO_OP.search(lead.title)
        and not _INTERN.search(lead.title)
        and not _SUMMER.search(f"{text} {lead.description}")
    ):
        return "co-op with no summer term"
    return None


def _degree_problem(lead: Lead) -> str | None:
    if _PHD.search(lead.title) and not _names_other_degree(lead.title):
        return "PhD-only title"
    for sentence in _SENTENCE_BREAK.split(lead.description):
        if (
            _PHD.search(sentence)
            and _REQUIRED.search(sentence)
            and not _names_other_degree(sentence)
        ):
            return "PhD required"
    return None


def _names_other_degree(text: str) -> bool:
    return bool(_OTHER_DEGREE_WORDS.search(text) or _OTHER_DEGREE_CODES.search(text))
