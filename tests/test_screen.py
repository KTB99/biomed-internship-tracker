import pytest

from tracker.models import Lead
from tracker.places import is_us_location
from tracker.screen import FAMILIES, family_for, level_for, screen


def lead(title, *, locations=("Irvine, CA",), **fields) -> Lead:
    return Lead(
        company="Acme Medical",
        platform="greenhouse",
        external_id="1",
        title=title,
        url="https://acme.example/jobs/1",
        locations=list(locations),
        **fields,
    )


def reasons(item: Lead) -> tuple[str, ...]:
    return screen(item, year=2027).reasons


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Irvine, CA", True),
        ("Minneapolis, Minnesota, United States", True),
        ("Remote - USA", True),
        ("US-MN", True),
        ("Boston, Massachusetts", True),
        ("Remote", False),
        ("Toronto, Ontario, Canada", False),
        ("Mexicali, Baja California, Mexico", False),
        ("Galway, Ireland", False),
        ("Utrecht, UT, NL", False),
        ("Quebec, QC, CA", False),
        ("Bogota, DC, CO", False),
        ("Fellbach, BW, DE", False),
        ("Pune, MH, IN", False),
        ("Marlboro, MA, US", True),
        ("Cleveland, Bolivar, MS", True),
        ("Juncos, Juncos, PR", True),
        ("Washington, District of Columbia, DC", True),
        ("1 Edwards Way, Irvine, CA", True),
        ("", False),
    ],
)
def test_us_location(location, expected):
    assert is_us_location(location) is expected


@pytest.mark.parametrize(
    "title",
    [
        "Software Engineering Intern",
        "R&D Intern, Catheter Design",
        "Quality Engineering Intern - Summer 2027",
        "Data Science Internship",
        "IT Intern",
        "Summer Co-op, Mechanical Engineering",
        "BS/MS/PhD Research Intern",
        # Title shapes from Neuralink, Axogen and AtriCure's boards.
        "Neuroengineer Intern",
        "Mechanical Engineering Intern, Brain Interfaces",
        "Intern, New Product Development (R&D)",
        "Sourcing Project Engineer Co-op (Summer 2027)",
        # Pharma title shapes from Genentech, Amgen, Takeda and Merck.
        "2027 Summer Intern - Translational Safety (Computational Toxicology)",
        "Grad Intern - Inflammation (Summer 2027)",
        "Grad Intern – Mass Spectrometry (Summer 2027)",
        "2027 Summer Internship Program: Population PK Pharmacometrics Intern",
        "2027 Future Talent Program - Discovery Chemistry & Process Research - Intern",
        # A co-op spanning spring and summer still covers the summer.
        "2027 Spring and Summer Co-Op, Packaging Engineering",
    ],
)
def test_accepts_stem_summer_internships(title):
    assert reasons(lead(title)) == ()


@pytest.mark.parametrize(
    "item, reason",
    [
        (lead("Senior Software Engineer"), "title is not an internship or co-op"),
        (lead("Internship Program Coordinator"), "title is a full-time or program-staff role"),
        (
            lead("SkillBridge Intern – Medical Imaging Service Engineer, Nationwide Opportunities"),
            "title is a SkillBridge placement",
        ),
        (lead("Marketing Intern"), "non-STEM role"),
        (lead("Talent Acquisition Intern"), "non-STEM role"),
        (lead("2027 Summer Law Intern - Data Privacy"), "non-STEM role"),
        (lead("Finance Data Intern"), "non-STEM role"),
        (lead("Summer Intern"), "no STEM evidence in title or department"),
        (lead("Engineering Intern", locations=["Remote"]), "no US location"),
        (lead("Engineering Intern - Summer 2026"), "term year 2026 is not 2027"),
        (lead("Fall 2027 Engineering Intern"), "not a summer term"),
        (lead("Engineering Co-op Spring 2027"), "not a summer term"),
        (lead("Engineering Co-op"), "co-op with no summer term"),
        (lead("PhD Research Intern"), "PhD-only title"),
        (
            lead(
                "Research Intern",
                description="Responsibilities include assays. Must be currently pursuing a PhD.",
            ),
            "PhD required",
        ),
    ],
)
def test_rejects_with_reason(item, reason):
    assert reason in reasons(item)


def test_lowercase_it_in_prose_is_not_stem_evidence():
    item = lead("Summer Intern", department="Make it count")
    assert "no STEM evidence in title or department" in reasons(item)


def test_department_can_supply_stem_evidence():
    assert reasons(lead("Summer Intern", department="Engineering")) == ()


def test_business_intelligence_is_stem():
    assert reasons(lead("Business Intelligence Intern")) == ()


def test_non_us_country_overrides_state_like_code():
    item = lead("Engineering Intern", locations=["Pune, IN"], country="IN")
    assert "country is IN" in reasons(item)


def test_foreign_country_code_places_have_no_us_location():
    item = lead("Engineering Intern", locations=["Utrecht, UT, NL", "Utrecht, Netherlands | N/A"])
    assert "no US location" in reasons(item)


def test_one_us_place_is_enough_beside_a_foreign_country_code_place():
    item = lead("Engineering Intern", locations=["Utrecht, UT, NL", "Marlboro, MA, US"])
    assert reasons(item) == ()


def test_us_country_field_is_enough():
    assert reasons(lead("Engineering Intern", locations=["Sunnyvale"], country="us")) == ()


def test_co_op_with_summer_in_description_is_accepted():
    item = lead("Engineering Co-op", description="This is a 12-week summer program.")
    assert reasons(item) == ()


def test_phd_alongside_other_degrees_is_accepted():
    item = lead("Research Intern", description="Must be pursuing a BS, MS or PhD in biology.")
    assert reasons(item) == ()


@pytest.mark.parametrize(
    "title, family",
    [
        ("Machine Learning Intern", "Data & AI"),
        ("Reinforcement Learning Intern", "Data & AI"),
        ("Software Engineering Intern", "Software & IT"),
        ("IT Intern", "Software & IT"),
        ("Firmware Intern", "Electrical & Firmware"),
        ("Robotics Intern", "Mechanical & Robotics"),
        ("Clinical Research Intern", "Clinical & Regulatory"),
        ("Quality Engineering Intern", "Quality & Manufacturing"),
        ("Supply Chain Material Management Intern", "Quality & Manufacturing"),
        ("Biomedical Engineering Intern", "R&D & Biomedical"),
        ("Engineering Intern", "Other STEM"),
    ],
)
def test_family(title, family):
    assert family in FAMILIES
    assert family_for(lead(title)) == family


@pytest.mark.parametrize(
    "title, level",
    [
        ("Undergrad Intern – Clinical Immunology (Summer 2027)", "undergrad"),
        ("Discovery Chemistry Undergraduate Internship", "undergrad"),
        ("Global Engineering Capital Projects Intern, Undergraduate", "undergrad"),
        ("Under-graduate Research Intern", "undergrad"),
        ("Summer 2027 - Genentech Community College Internship Program - Laboratory", "undergrad"),
        ("Bachelor's Engineering Intern", "undergrad"),
        ("BS Chemistry Intern", "undergrad"),
        ("Grad Intern – Protein Engineering (Summer 2027)", "grad"),
        ("Graduate Intern – R&D Execution, Operations & Strategy", "grad"),
        ("Master's Data Science Intern", "grad"),
        ("Masters Intern, Biostatistics", "grad"),
        ("MS/PhD Research Intern", "grad"),
        ("MBA Intern - Strategy", "grad"),
        ("Undergraduate or Graduate Research Intern", "any"),
        ("BS/MS Quality Engineering Intern", "any"),
        ("Master Data Management Intern", "any"),
        ("Research Intern - Graduating seniors welcome", "any"),
        ("Software Engineering Intern", "any"),
    ],
)
def test_level(title, level):
    assert level_for(title) == level
