"""Normalization tests.

These matter more than they look. Every threshold comparison downstream assumes its
operand is already in the canonical unit, so a normalization bug does not surface as a
crash — it surfaces as a wrong eligibility decision that looks perfectly reasonable.
"""

import pytest

from tn_schemematch.attributes import SchemaError


# ----------------------------------------------------------------- enum aliases


@pytest.mark.parametrize(
    "attr,surface,expected",
    [
        ("social_category", "SC", "SC"),
        ("social_category", "scheduled caste", "SC"),
        ("social_category", "ஆதிதிராவிடர்", "SC"),
        ("social_category", "adi dravidar", "SC"),
        ("social_category", "arunthathiyar", "SCA"),
        ("social_category", "most backward class", "MBC"),
        ("gender", "பெண்", "female"),
        ("gender", "ponnu", "female"),
        ("gender", "thirunangai", "transgender"),
        ("occupation", "vivasayi", "farmer"),
        ("occupation", "விவசாயி", "farmer"),
        ("occupation", "meenavar", "fisher"),
        ("occupation", "coolie", "daily_wage"),
        ("marital_status", "vidhavai", "widowed"),
        ("marital_status", "விதவை", "widowed"),
        ("district", "trichy", "Tiruchirappalli"),
        ("district", "kovai", "Coimbatore"),
        ("district", "madras", "Chennai"),
        ("state", "தமிழ்நாடு", "TN"),
        ("residence_type", "gramam", "rural"),
        ("traditional_trade", "kollan", "blacksmith"),
        ("course_mode", "ignou", "open_university"),
    ],
)
def test_enum_aliases_canonicalize(spec, attr, surface, expected):
    assert spec.canonicalize(attr, surface) == expected


def test_longest_alias_wins_over_substring(spec):
    """'sugar card' must not be swallowed by a shorter 'card' alias."""
    assert spec.canonicalize("ration_card_type", "sugar card irukku") == "nphh_sugar"
    assert spec.canonicalize("ration_card_type", "ration card irukku") == "phh_rice"


def test_unknown_enum_value_raises(spec):
    with pytest.raises(SchemaError):
        spec.canonicalize("social_category", "completely made up category")


# --------------------------------------------------------------- numeric parsing


@pytest.mark.parametrize(
    "surface,expected",
    [
        ("90000", 90000),
        ("1,00,000", 100000),
        ("2 lakh", 200000),
        ("2.5 lakh", 250000),
        ("2 லட்சம்", 200000),
        ("50 thousand", 50000),
        ("8000 per month", 96000),
        ("month-ku 8000", 96000),
        ("maasam 7000", 84000),
        ("மாசம் 5000", 60000),
    ],
)
def test_income_normalizes_to_annual_rupees(spec, surface, expected):
    assert spec.canonicalize("annual_family_income", surface) == pytest.approx(expected)


@pytest.mark.parametrize(
    "surface,expected",
    [
        ("2 acres", 2.0),
        ("rendu ekkar", None),      # word-number, not digits — must not silently parse
        ("2 ekkar", 2.0),
        ("2 ஏக்கர்", 2.0),
        ("1 hectare", 2.4710538),
        ("80 cent", 0.8),
        ("1 ground", 0.05509642),
    ],
)
def test_land_normalizes_to_acres(spec, surface, expected):
    if expected is None:
        with pytest.raises(SchemaError):
            spec.canonicalize("land_owned_acres", surface)
    else:
        assert spec.canonicalize("land_owned_acres", surface) == pytest.approx(expected, rel=1e-6)


def test_out_of_domain_number_rejected(spec):
    with pytest.raises(SchemaError):
        spec.canonicalize("age", 250)


# ------------------------------------------------------------------- booleans


@pytest.mark.parametrize(
    "surface,expected",
    [(True, True), ("yes", True), ("irukku", True), ("இருக்கு", True),
     (False, False), ("no", False), ("illa", False), ("இல்லை", False)],
)
def test_boolean_surface_forms(spec, surface, expected):
    assert spec.canonicalize("has_aadhaar", surface) is expected


def test_unreadable_boolean_raises(spec):
    with pytest.raises(SchemaError):
        spec.canonicalize("has_aadhaar", "maybe someday")


# ------------------------------------------------------------------ derivations


def test_derivations_fire(spec):
    profile = spec.normalize_profile(
        {"land_owned_acres": 0, "age": 67, "disability_percent": 45, "marital_status": "widowed"}
    )
    assert profile["is_landless"] is True
    assert profile["farmer_category"] == "landless"
    assert profile["is_senior_citizen"] is True
    assert profile["is_disabled"] is True
    assert profile["is_widow"] is True


@pytest.mark.parametrize(
    "acres,expected",
    [(0, "landless"), (1.0, "marginal"), (2.47, "marginal"), (3.0, "small"),
     (7.0, "semi_medium"), (15.0, "medium"), (40.0, "large")],
)
def test_farmer_category_bins(spec, acres, expected):
    assert spec.derive({"land_owned_acres": acres})["farmer_category"] == expected


def test_derived_attributes_are_not_elicitable(spec):
    for name in ("is_landless", "farmer_category", "is_disabled", "is_senior_citizen", "is_widow"):
        assert not spec[name].elicitable
        assert name not in spec.elicitable_names()


def test_derivation_rules_cannot_execute_code(spec):
    """The attribute spec is data. A data file must not be able to run arbitrary Python."""
    from tn_schemematch.attributes import _eval_derivation

    with pytest.raises(SchemaError):
        _eval_derivation("__import__('os').system('echo pwned')", 1)
    with pytest.raises(SchemaError):
        _eval_derivation("value > 0 and print('side effect')", 1)


# ---------------------------------------------------------------------- profile


def test_normalize_profile_rejects_unknown_attribute(spec):
    with pytest.raises(SchemaError):
        spec.normalize_profile({"favourite_colour": "blue"})


def test_normalize_profile_handles_mixed_surface_forms(spec):
    profile = spec.normalize_profile({
        "occupation": "விவசாயி",
        "land_owned_acres": "2 ekkar",
        "annual_family_income": "maasam 7500",
        "social_category": "adi dravidar",
        "district": "trichy",
    })
    assert profile["occupation"] == "farmer"
    assert profile["land_owned_acres"] == pytest.approx(2.0)
    assert profile["annual_family_income"] == pytest.approx(90000)
    assert profile["social_category"] == "SC"
    assert profile["district"] == "Tiruchirappalli"
