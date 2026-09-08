#!/usr/bin/env python3
"""Generate the code-mixed persona benchmark.

    python scripts/generate_personas.py --n 200 --seed 20260904

What this is, stated before anything else: a *synthetic* persona set. The profiles are
sampled from hand-written archetype distributions, and the queries are assembled from the
paired lexicon in ``_persona_lexicon.py``. Every persona it writes carries
``NOT YET NATIVELY VALIDATED`` in its annotation notes, and a test enforces that. It is a
scaffold for the annotation effort described in ``docs/annotation-guide.md``, not a
substitute for it.

Three properties are guaranteed by construction rather than by inspection, which is the
reason for generating rather than hand-writing at this scale:

**The parallel is faithful.** Both query variants are rendered from one list of facts, so
they reveal the same attributes by construction. ``stated_in_query`` is that same list.
The annotation guide's central check — "could a careful reader extract exactly the same
attribute set from both?" — cannot fail here for reasons of *content*. It can still fail
for reasons of *phrasing*, which is what native validation is for.

**The profile is complete and internally consistent.** ``repair()`` enforces the
dependencies that make a person possible — a student is not fifty with three children, wet
plus dry land equals total land, a man is not pregnant, a destitute applicant does not
earn Rs 4 lakh — and the generator rejects any persona that ``validate_personas`` faults.

**The set is informative rather than comfortable.** Roughly half the personas are placed
deliberately within a few rupees, one year, or a tenth of an acre of a threshold that some
rule in the KB actually tests, using boundaries read out of the rules themselves. The rest
are drawn from the archetype distributions. Minimal pairs differing in exactly one
attribute, with identical queries, are emitted at the end.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import yaml  # noqa: E402

from _persona_lexicon import CLOSERS, EDUCATION, OPENERS, RENDERERS  # noqa: E402
from tn_schemematch import load_kb  # noqa: E402
from tn_schemematch.attributes import default_spec  # noqa: E402
from tn_schemematch.personas import load_personas, validate_personas  # noqa: E402
from tn_schemematch.rules import Predicate, Verdict  # noqa: E402

OUT_DIR = REPO_ROOT / "data" / "personas" / "generated"

COASTAL = ["Chennai", "Chengalpattu", "Cuddalore", "Kanyakumari", "Mayiladuthurai",
           "Nagapattinam", "Pudukkottai", "Ramanathapuram", "Thanjavur", "Thoothukudi",
           "Tiruvallur", "Tirunelveli", "Tiruvarur", "Villupuram"]
DISTRICTS = ["Ariyalur", "Chengalpattu", "Chennai", "Coimbatore", "Cuddalore", "Dharmapuri",
             "Dindigul", "Erode", "Kallakurichi", "Kancheepuram", "Kanyakumari", "Karur",
             "Krishnagiri", "Madurai", "Mayiladuthurai", "Nagapattinam", "Namakkal",
             "Nilgiris", "Perambalur", "Pudukkottai", "Ramanathapuram", "Ranipet", "Salem",
             "Sivaganga", "Tenkasi", "Thanjavur", "Theni", "Thoothukudi", "Tiruchirappalli",
             "Tirunelveli", "Tirupattur", "Tiruppur", "Tiruvallur", "Tiruvannamalai",
             "Tiruvarur", "Vellore", "Viluppuram", "Virudhunagar"]
CATEGORIES = ["SC", "SCA", "ST", "MBC", "DNC", "BC", "BCM", "FC"]
CATEGORY_WEIGHTS = [22, 4, 3, 26, 2, 30, 7, 6]

# The generator only ever reveals attributes a citizen would plausibly volunteer.
REVEALABLE = [
    "occupation", "age", "annual_family_income", "land_owned_acres", "ration_card_type",
    "marital_status", "social_category", "district", "residence_type", "house_ownership",
    "education_level", "disability_percent", "pregnancy_status", "is_destitute",
    "is_head_of_household", "enrolled_in_higher_education", "studied_in_government_school",
    "has_upcoming_marriage", "is_orphan", "is_daughter_of_widow", "has_lpg_connection",
    "is_member_of_fishermen_cooperative", "has_vending_certificate",
    "is_srilankan_tamil_refugee", "receives_other_pension", "owns_four_wheeler",
    "is_government_employee", "spouse_is_government_employee", "is_income_tax_payer",
    "has_mgnrega_job_card", "employment_exchange_registration_years",
    "years_since_desertion", "pregnancy_order", "_children",
]


# --------------------------------------------------------------------- archetypes

def base_profile(rng: random.Random) -> dict[str, Any]:
    """Every attribute at a neutral default. Archetypes overwrite what they care about."""
    return {
        "age": 35, "gender": "female", "marital_status": "married",
        "social_category": rng.choices(CATEGORIES, CATEGORY_WEIGHTS)[0],
        "religion": rng.choices(["hindu", "muslim", "christian"], [85, 8, 7])[0],
        "state": "TN", "district": rng.choice(DISTRICTS),
        "residence_type": rng.choices(["rural", "urban"], [55, 45])[0],
        "annual_family_income": 96000,
        "is_income_tax_payer": False, "family_has_income_tax_payer": False,
        "is_government_employee": False, "spouse_is_government_employee": False,
        "is_class_iv_employee": False, "monthly_pension_amount": 0,
        "is_registered_professional": False, "held_constitutional_post": False,
        "fixed_assets_value": 300000, "annual_electricity_units": 1200,
        "is_destitute": False, "is_head_of_household": False,
        "land_owned_acres": 0.0, "wetland_acres": 0.0, "dryland_acres": 0.0,
        "ration_card_type": "phh_rice", "house_ownership": "rented",
        "owns_four_wheeler": False, "family_size": 4,
        "occupation": "daily_wage", "education_level": "secondary",
        "studied_in_government_school": True, "is_first_generation_learner": False,
        "enrolled_in_higher_education": False, "course_mode": "not_applicable",
        "previous_exam_percent": 0, "traditional_trade": "none",
        "availed_govt_credit_scheme_last_5y": False,
        "disability_percent": 0, "pregnancy_status": "not_applicable",
        "receives_other_pension": False,
        "has_aadhaar": True, "has_bank_account": True, "has_community_certificate": True,
        # v0.2
        "is_bpl": False, "is_secc_deprived_household": False, "has_lpg_connection": True,
        "pregnancy_order": 0, "daughters_count": 0, "sons_count": 0,
        "has_undergone_family_planning": False, "is_orphan": False,
        "is_daughter_of_widow": False, "has_upcoming_marriage": False,
        "is_inter_caste_marriage": False, "years_since_desertion": 0,
        "is_covered_by_epfo_esic_nps": False, "is_registered_unorganised_worker": False,
        "has_mgnrega_job_card": False, "has_vending_certificate": False,
        "is_member_of_fishermen_cooperative": False, "is_srilankan_tamil_refugee": False,
        "is_inter_state_migrant": False, "spouse_is_differently_abled": False,
        "employment_exchange_registration_years": 0,
    }


def money(rng: random.Random, low: int, high: int) -> int:
    """A monthly figure rounded to the nearest 500, annualised — so both query
    registers ("maasam 8000", "varushathukku 96000") state the same number exactly."""
    monthly = rng.randrange(low // 12 // 500 * 500 or 500, max(high // 12, low // 12 + 500) + 1, 500)
    return monthly * 12


def arch_farmer(p, rng):
    p.update(gender=rng.choices(["male", "female"], [70, 30])[0], age=rng.randint(25, 70),
             occupation="farmer", residence_type="rural",
             land_owned_acres=round(rng.choice([0.5, 0.8, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 6.0, 12.0]), 2),
             annual_family_income=money(rng, 48000, 240000),
             ration_card_type=rng.choices(["phh_rice", "aay", "nphh_sugar"], [70, 15, 15])[0],
             house_ownership=rng.choice(["owns_kutcha", "owns_pucca", "owns_kutcha"]),
             education_level=rng.choice(["none", "primary", "middle", "secondary"]),
             has_mgnrega_job_card=rng.random() < 0.5,
             daughters_count=rng.randint(0, 2), sons_count=rng.randint(0, 2),
             family_size=rng.randint(3, 6))
    return p


def arch_agri_labourer(p, rng):
    p.update(gender=rng.choice(["male", "female"]), age=rng.randint(22, 65),
             occupation="agri_labourer", residence_type="rural", land_owned_acres=0.0,
             annual_family_income=money(rng, 36000, 120000),
             ration_card_type=rng.choices(["phh_rice", "aay"], [70, 30])[0],
             house_ownership=rng.choice(["owns_kutcha", "rented"]),
             education_level=rng.choice(["none", "primary", "middle"]),
             is_bpl=rng.random() < 0.7, has_mgnrega_job_card=rng.random() < 0.7,
             is_registered_unorganised_worker=rng.random() < 0.4,
             daughters_count=rng.randint(0, 2), sons_count=rng.randint(0, 2))
    return p


def arch_widow(p, rng):
    p.update(gender="female", marital_status="widowed", age=rng.randint(28, 72),
             occupation=rng.choice(["daily_wage", "homemaker", "agri_labourer", "unemployed"]),
             annual_family_income=money(rng, 0, 96000),
             is_destitute=rng.random() < 0.5, is_head_of_household=True,
             fixed_assets_value=rng.choice([0, 20000, 45000, 50000, 60000, 200000]),
             is_bpl=rng.random() < 0.6,
             daughters_count=rng.randint(0, 2), sons_count=rng.randint(0, 2),
             family_size=rng.randint(2, 5))
    return p


def arch_deserted(p, rng):
    p.update(gender="female", marital_status=rng.choices(["deserted", "divorced"], [70, 30])[0],
             age=rng.randint(26, 55), occupation=rng.choice(["daily_wage", "homemaker", "self_employed"]),
             annual_family_income=money(rng, 0, 84000), is_destitute=rng.random() < 0.6,
             is_head_of_household=True, years_since_desertion=rng.randint(0, 12),
             fixed_assets_value=rng.choice([0, 15000, 49000, 50000, 75000]),
             daughters_count=rng.randint(0, 2), sons_count=rng.randint(0, 1))
    return p


def arch_elderly(p, rng):
    p.update(age=rng.randint(58, 88), gender=rng.choice(["male", "female"]),
             marital_status=rng.choices(["widowed", "married"], [60, 40])[0],
             occupation=rng.choice(["retired", "unemployed", "agri_labourer", "homemaker"]),
             annual_family_income=money(rng, 0, 72000), is_destitute=rng.random() < 0.55,
             fixed_assets_value=rng.choice([0, 10000, 49000, 50000, 120000]),
             receives_other_pension=rng.random() < 0.3, is_bpl=rng.random() < 0.6,
             education_level=rng.choice(["none", "primary", "middle"]),
             daughters_count=rng.randint(0, 3), sons_count=rng.randint(0, 3),
             family_size=rng.randint(1, 4))
    return p


def arch_student(p, rng):
    p.update(age=rng.randint(17, 24), gender=rng.choice(["male", "female"]),
             marital_status="unmarried", occupation="student",
             education_level=rng.choices(["higher_secondary", "iti_diploma", "undergraduate"], [70, 15, 15])[0],
             enrolled_in_higher_education=True,
             course_mode=rng.choices(["regular", "distance", "correspondence"], [80, 12, 8])[0],
             previous_exam_percent=rng.randint(30, 95),
             studied_in_government_school=rng.random() < 0.65,
             is_first_generation_learner=rng.random() < 0.5,
             annual_family_income=money(rng, 36000, 360000),
             residence_type=rng.choices(["rural", "urban"], [50, 50])[0])
    return p


def arch_pregnant(p, rng):
    p.update(gender="female", marital_status="married", age=rng.randint(19, 38),
             pregnancy_status=rng.choices(["pregnant", "lactating"], [70, 30])[0],
             pregnancy_order=rng.choices([1, 2, 3], [45, 35, 20])[0],
             occupation=rng.choice(["homemaker", "daily_wage", "agri_labourer", "salaried_private"]),
             annual_family_income=money(rng, 36000, 900000),
             is_bpl=rng.random() < 0.45,
             is_registered_unorganised_worker=rng.random() < 0.35,
             has_mgnrega_job_card=rng.random() < 0.3)
    return p


def arch_artisan(p, rng):
    trade = rng.choice(["tailor", "carpenter", "blacksmith", "potter", "goldsmith", "cobbler",
                        "mason", "basket_weaver", "barber", "washerman", "garland_maker"])
    p.update(age=rng.randint(20, 62), gender=rng.choice(["male", "female"]),
             occupation=rng.choices(["artisan", "self_employed", "daily_wage"], [50, 35, 15])[0],
             traditional_trade=trade, annual_family_income=money(rng, 48000, 300000),
             residence_type=rng.choices(["rural", "urban"], [45, 55])[0],
             availed_govt_credit_scheme_last_5y=rng.random() < 0.25,
             education_level=rng.choice(["primary", "middle", "secondary", "higher_secondary"]))
    return p


def arch_fisher(p, rng):
    p.update(age=rng.randint(21, 60), gender=rng.choices(["male", "female"], [75, 25])[0],
             occupation="fisher", district=rng.choice(COASTAL),
             residence_type="rural", annual_family_income=money(rng, 48000, 180000),
             is_member_of_fishermen_cooperative=rng.random() < 0.7,
             is_bpl=rng.random() < 0.55, ration_card_type=rng.choice(["phh_rice", "aay"]),
             education_level=rng.choice(["none", "primary", "middle", "secondary"]))
    return p


def arch_vendor(p, rng):
    p.update(age=rng.randint(21, 58), gender=rng.choice(["male", "female"]),
             occupation="self_employed", residence_type="urban",
             has_vending_certificate=rng.random() < 0.6,
             annual_family_income=money(rng, 48000, 240000),
             is_registered_unorganised_worker=rng.random() < 0.5,
             education_level=rng.choice(["primary", "middle", "secondary"]))
    return p


def arch_disabled(p, rng):
    p.update(age=rng.randint(18, 60), gender=rng.choice(["male", "female"]),
             disability_percent=rng.choice([40, 45, 55, 60, 74, 75, 79, 80, 85, 90]),
             occupation=rng.choices(["unemployed", "self_employed", "daily_wage", "student"], [55, 20, 15, 10])[0],
             employment_exchange_registration_years=rng.choice([0, 0, 1, 2, 4]),
             annual_family_income=money(rng, 0, 144000),
             is_bpl=rng.random() < 0.5,
             marital_status=rng.choices(["unmarried", "married"], [60, 40])[0])
    return p


def arch_refugee(p, rng):
    p.update(is_srilankan_tamil_refugee=True, age=rng.randint(20, 70),
             gender=rng.choice(["male", "female"]),
             occupation=rng.choice(["daily_wage", "unemployed", "homemaker"]),
             annual_family_income=money(rng, 0, 84000),
             is_destitute=rng.random() < 0.6,
             ration_card_type=rng.choices(["none", "phh_rice"], [60, 40])[0],
             house_ownership=rng.choice(["rented", "owns_kutcha", "homeless"]),
             district=rng.choice(["Tiruchirappalli", "Erode", "Salem", "Madurai", "Villupuram"]))
    return p


def arch_salaried(p, rng):
    p.update(age=rng.randint(24, 58), gender=rng.choice(["male", "female"]),
             occupation=rng.choices(["salaried_private", "salaried_government"], [75, 25])[0],
             annual_family_income=money(rng, 240000, 1200000),
             residence_type="urban", house_ownership=rng.choice(["owns_pucca", "rented"]),
             education_level=rng.choice(["undergraduate", "postgraduate", "iti_diploma"]),
             owns_four_wheeler=rng.random() < 0.4,
             is_covered_by_epfo_esic_nps=rng.random() < 0.8,
             is_income_tax_payer=rng.random() < 0.5,
             fixed_assets_value=rng.choice([500000, 1500000, 4000000]),
             annual_electricity_units=rng.randint(1800, 5200))
    return p


def arch_bride(p, rng):
    p.update(gender="female", marital_status="unmarried", age=rng.randint(18, 32),
             has_upcoming_marriage=True,
             is_daughter_of_widow=rng.random() < 0.35, is_orphan=rng.random() < 0.15,
             is_inter_caste_marriage=rng.random() < 0.2,
             annual_family_income=money(rng, 24000, 180000),
             education_level=rng.choice(["secondary", "higher_secondary", "undergraduate", "middle"]),
             occupation=rng.choice(["homemaker", "daily_wage", "student", "salaried_private"]))
    return p


def arch_homemaker_head(p, rng):
    p.update(gender="female", age=rng.randint(21, 58), marital_status="married",
             occupation="homemaker", is_head_of_household=True,
             annual_family_income=money(rng, 36000, 360000),
             annual_electricity_units=rng.choice([900, 1800, 2400, 3500, 3600, 4200]),
             owns_four_wheeler=rng.random() < 0.15,
             land_owned_acres=round(rng.choice([0.0, 0.0, 1.0, 3.0, 5.0, 8.0]), 2),
             daughters_count=rng.randint(0, 3), sons_count=rng.randint(0, 2),
             has_undergone_family_planning=rng.random() < 0.5,
             spouse_is_government_employee=rng.random() < 0.12)
    return p


ARCHETYPES = [
    ("farmer", arch_farmer, 12),
    ("agri-labourer", arch_agri_labourer, 8),
    ("widow", arch_widow, 9),
    ("deserted-wife", arch_deserted, 6),
    ("elderly", arch_elderly, 9),
    ("student", arch_student, 11),
    ("expecting-mother", arch_pregnant, 8),
    ("artisan", arch_artisan, 8),
    ("fisher", arch_fisher, 5),
    ("street-vendor", arch_vendor, 5),
    ("differently-abled", arch_disabled, 7),
    ("refugee", arch_refugee, 3),
    ("salaried", arch_salaried, 6),
    ("bride", arch_bride, 7),
    ("woman-head-of-family", arch_homemaker_head, 9),
]


# --------------------------------------------------------------- targeted set
# (name, why it exists, profile overrides, the scheme it is meant to reach or None)
TARGETED: list[tuple[str, str, dict[str, Any], str | None]] = [
    ("mother of one daughter, Erode",
     "No sampled persona reached the single-girl-child deposit scheme: it needs one "
     "daughter, no sons, a family-planning procedure and an income under Rs 72,000 at once.",
     dict(gender="female", age=33, marital_status="married", occupation="homemaker",
          district="Erode", residence_type="rural", annual_family_income=60000,
          daughters_count=1, sons_count=0, has_undergone_family_planning=True,
          ration_card_type="phh_rice", house_ownership="owns_kutcha", family_size=3),
     "cm-girl-child-protection-i"),

    ("widow remarrying at 34, Theni",
     "The widow-remarriage scheme was unreachable: widows in the sampled set never had a "
     "marriage arranged, because the sampler treats widowhood and an upcoming wedding as "
     "belonging to different archetypes. They do not.",
     dict(gender="female", age=34, marital_status="widowed", has_upcoming_marriage=True,
          occupation="daily_wage", district="Theni", annual_family_income=84000,
          is_head_of_household=True, education_level="secondary"),
     "dharmambal-widow-remarriage"),

    ("woman cooking on firewood, Perambalur",
     "Nobody sampled lacked an LPG connection, so the Ujjwala rule was never satisfied — "
     "an attribute that never varies cannot distinguish a system that reads it from one "
     "that ignores it.",
     dict(gender="female", age=29, marital_status="married", occupation="agri_labourer",
          district="Perambalur", residence_type="rural", annual_family_income=60000,
          is_bpl=True, has_lpg_connection=False, ration_card_type="aay",
          house_ownership="owns_kutcha"),
     "pmuy"),

    ("state-topper SC student, Sivaganga",
     "The merit scholarship needs a 90 percent mark and an income under Rs 1 lakh together; "
     "the sampler produces each often and both rarely.",
     dict(gender="female", age=18, marital_status="unmarried", occupation="student",
          social_category="SC", district="Sivaganga", annual_family_income=84000,
          education_level="secondary", previous_exam_percent=96,
          studied_in_government_school=True, is_first_generation_learner=True,
          has_community_certificate=True),
     "tn-ambedkar-merit-scholarship"),

    ("differently abled man marrying, Karur",
     "Marriage assistance for the differently abled needs a certified disability and an "
     "arranged marriage at once — again two archetypes the sampler keeps apart.",
     dict(gender="male", age=27, marital_status="unmarried", disability_percent=60,
          has_upcoming_marriage=True, spouse_is_differently_abled=True,
          occupation="self_employed", district="Karur", annual_family_income=72000),
     "tn-da-marriage-assistance"),

    ("unmarried destitute woman of 56, Ariyalur",
     "The unmarried-women pension sits in the gap between the sampler's 'widow' and "
     "'elderly' archetypes, and no sampled persona was both never-married and over 50.",
     dict(gender="female", age=56, marital_status="unmarried", occupation="unemployed",
          district="Ariyalur", is_destitute=True, annual_family_income=12000,
          fixed_assets_value=20000, ration_card_type="phh_rice", house_ownership="rented"),
     "tn-unmarried-women-pension"),

    ("income-tax-paying landowner, Namakkal",
     "PM-KISAN's exclusions were never the reason anybody failed it: every sampled "
     "landholder was poor. Missed exclusions are the highest-cost error a system can make, "
     "so at least one persona must be blocked by one and by nothing else.",
     dict(gender="male", age=48, marital_status="married", occupation="farmer",
          district="Namakkal", residence_type="rural", land_owned_acres=6.0,
          annual_family_income=960000, is_income_tax_payer=True,
          family_has_income_tax_payer=True, house_ownership="owns_pucca",
          owns_four_wheeler=True, fixed_assets_value=4000000,
          annual_electricity_units=4800, education_level="undergraduate"),
     None),

    ("woman head of family whose husband is a clerk, Ranipet",
     "The KMUT exclusions were likewise untested. This persona satisfies every positive "
     "condition — age, headship, income, land, electricity — and fails only because the "
     "2026-09-04 verification pass moved the government-employment test to family scope. "
     "She was eligible under v0.1 and is not now, which is exactly the change worth having "
     "a persona witness.",
     dict(gender="female", age=39, marital_status="married", occupation="homemaker",
          district="Ranipet", is_head_of_household=True, annual_family_income=204000,
          spouse_is_government_employee=True, land_owned_acres=1.0,
          annual_electricity_units=2400, ration_card_type="phh_rice",
          house_ownership="owns_pucca", daughters_count=2, sons_count=0),
     None),

    ("Group D employee who also farms, Dindigul",
     "PM-KISAN carves Class IV and Group D staff out of its government-employment "
     "exclusion. No sampled persona was ever a Class IV employee, so the carve-out — a "
     "clause that only ever matters for the poorest government workers — was dead code in "
     "the benchmark.",
     dict(gender="male", age=44, marital_status="married", occupation="farmer",
          district="Dindigul", residence_type="rural", land_owned_acres=1.5,
          annual_family_income=228000, is_government_employee=True,
          is_class_iv_employee=True, education_level="higher_secondary"),
     "pm-kisan"),

    ("inter-state migrant worker in Tiruppur",
     "CMCHIS's migrant route, added at the 2026-09-04 verification pass, had no persona "
     "exercising it. Her income is above the resident ceiling, so she can only be eligible "
     "through that branch — which is what makes her a test of it rather than of the branch "
     "beside it.",
     dict(gender="female", age=31, marital_status="married", occupation="salaried_private",
          district="Tiruppur", residence_type="urban", annual_family_income=180000,
          is_inter_state_migrant=True, ration_card_type="none",
          house_ownership="rented", is_covered_by_epfo_esic_nps=True),
     "cmchis"),

    ("Sri Lankan Tamil refugee, Tiruchirappalli",
     "The refugee route into CMCHIS and the refugee pension both became encodable only in "
     "v0.2. Without a persona they would be rules nothing ever evaluates to true.",
     dict(gender="male", age=52, marital_status="married", occupation="daily_wage",
          district="Tiruchirappalli", is_srilankan_tamil_refugee=True, is_destitute=True,
          annual_family_income=24000, ration_card_type="none", house_ownership="rented",
          fixed_assets_value=0, has_bank_account=True),
     "tn-srilankan-refugee-pension"),

    ("labourer in Bengaluru with family in Hosur",
     "Every sampled persona lives in Tamil Nadu, so nothing tested whether a system "
     "applies the residence condition that every state scheme carries. This persona's "
     "profile is otherwise that of someone who would qualify for several of them.",
     dict(state="other", gender="male", age=41, marital_status="married",
          occupation="daily_wage", district="Krishnagiri", residence_type="urban",
          annual_family_income=96000, ration_card_type="none", house_ownership="rented",
          is_bpl=True),
     None),

    ("elderly widow with no bank account, Nilgiris",
     "has_aadhaar and has_bank_account were true for every persona, which made the "
     "documentary preconditions of the direct-benefit schemes untestable — and unbanked "
     "elderly women are precisely the population those preconditions exclude in practice.",
     dict(gender="female", age=71, marital_status="widowed", occupation="unemployed",
          district="Nilgiris", residence_type="rural", is_destitute=True,
          annual_family_income=0, fixed_assets_value=15000, has_bank_account=False,
          has_aadhaar=False, is_bpl=True, ration_card_type="aay",
          house_ownership="owns_kutcha", receives_other_pension=False),
     "tn-old-age-pension"),

    ("practising doctor with ancestral land, Vellore",
     "PM-KISAN excludes practising registered professionals and constitutional post "
     "holders by name. Neither attribute ever varied in the sampled set, so both clauses "
     "were invisible to the benchmark.",
     dict(gender="female", age=45, marital_status="married", occupation="self_employed",
          district="Vellore", residence_type="urban", land_owned_acres=3.0,
          annual_family_income=1800000, is_registered_professional=True,
          is_income_tax_payer=True, family_has_income_tax_payer=True,
          owns_four_wheeler=True, house_ownership="owns_pucca",
          fixed_assets_value=8000000, annual_electricity_units=6000,
          education_level="postgraduate"),
     None),

    ("mother of two daughters, Pudukkottai",
     "Scheme II of the girl-child deposit needs exactly two daughters, no sons, a "
     "family-planning procedure and an income under Rs 72,000. Its sibling Scheme I is "
     "reachable by accident; this one is not, and the two are a minimal pair on a single "
     "integer.",
     dict(gender="female", age=36, marital_status="married", occupation="daily_wage",
          district="Pudukkottai", residence_type="rural", annual_family_income=66000,
          daughters_count=2, sons_count=0, has_undergone_family_planning=True,
          ration_card_type="phh_rice", house_ownership="owns_kutcha", family_size=4),
     "cm-girl-child-protection-ii"),

    ("former panchayat chairperson, Tirunelveli",
     "held_constitutional_post was true for nobody, so PM-KISAN's constitutional-post "
     "exclusion — one of the few clauses in the KB that exists purely to keep the "
     "well-connected out of a poverty programme — was never exercised.",
     dict(gender="male", age=57, marital_status="married", occupation="farmer",
          district="Tirunelveli", residence_type="rural", land_owned_acres=8.0,
          annual_family_income=420000, held_constitutional_post=True,
          house_ownership="owns_pucca", owns_four_wheeler=True,
          fixed_assets_value=3000000, annual_electricity_units=3800,
          education_level="undergraduate"),
     None),

    ("SC student without a community certificate, Salem",
     "Every persona held a community certificate, so the documentary precondition on the "
     "category-reserved scholarships never bit. It bites often in practice: the "
     "certificate, not the community, is what the scholarship checks.",
     dict(gender="male", age=20, marital_status="unmarried", occupation="student",
          social_category="SC", district="Salem", annual_family_income=96000,
          education_level="higher_secondary", enrolled_in_higher_education=True,
          course_mode="regular", previous_exam_percent=68,
          studied_in_government_school=True, has_community_certificate=False,
          is_first_generation_learner=True),
     None),

    ("expecting her third child, Kallakurichi",
     "The two-pregnancy limits in MRMBS and PMMVY became encodable at the 2026-09-04 pass. "
     "A third pregnancy satisfies every surface cue for both schemes and fails both, which "
     "is the trap shape the benchmark was short of.",
     dict(gender="female", age=30, marital_status="married", occupation="homemaker",
          district="Kallakurichi", residence_type="rural", pregnancy_status="pregnant",
          pregnancy_order=3, daughters_count=2, sons_count=0, is_bpl=True,
          annual_family_income=72000, ration_card_type="phh_rice"),
     None),
]


# ------------------------------------------------------------------ consistency

def repair(p: dict[str, Any]) -> dict[str, Any]:
    """Make the profile describe a person who could exist.

    Ground truth computed from an impossible profile is still internally consistent and
    still worthless, so this runs after every sampling step *and* after the threshold
    nudge, which is the step most likely to break something.
    """
    # Preserve an explicitly non-TN state: the benchmark needs a few out-of-state
    # personas, or nothing ever tests that the state schemes check residence at all.
    p["state"] = p.get("state", "TN")

    land = max(0.0, round(float(p["land_owned_acres"]), 2))
    p["land_owned_acres"] = land
    if land == 0:
        p["wetland_acres"] = p["dryland_acres"] = 0.0
    else:
        wet = round(land * (0.0 if land < 0.5 else 0.4), 2)
        p["wetland_acres"] = wet
        p["dryland_acres"] = round(land - wet, 2)

    if p["gender"] != "female":
        p["pregnancy_status"] = "not_applicable"
        p["pregnancy_order"] = 0
        p["is_daughter_of_widow"] = False
        p["spouse_is_government_employee"] = False
    if p["pregnancy_status"] == "not_applicable":
        p["pregnancy_order"] = 0
    else:
        p["pregnancy_order"] = max(1, int(p["pregnancy_order"]))
        p["age"] = min(max(int(p["age"]), 18), 45)

    if p["marital_status"] != "deserted":
        p["years_since_desertion"] = 0
    if p["marital_status"] in {"unmarried", "widowed", "divorced", "deserted"}:
        p["spouse_is_government_employee"] = False
        p["spouse_is_differently_abled"] = False

    if p["occupation"] == "student":
        p["age"] = min(max(int(p["age"]), 16), 27)
        p["marital_status"] = "unmarried"
        p["enrolled_in_higher_education"] = True
        p["pregnancy_status"] = "not_applicable"
        p["pregnancy_order"] = 0
    if p["enrolled_in_higher_education"]:
        if p["course_mode"] == "not_applicable":
            p["course_mode"] = "regular"
        p["previous_exam_percent"] = max(30, int(p["previous_exam_percent"]))
    else:
        p["course_mode"] = "not_applicable"

    if int(p["age"]) < 21:
        p["daughters_count"] = p["sons_count"] = 0
        p["has_undergone_family_planning"] = False
        p["is_head_of_household"] = False
        p["marital_status"] = "unmarried" if p["marital_status"] != "unmarried" else p["marital_status"]
        p["pregnancy_status"] = "not_applicable" if int(p["age"]) < 18 else p["pregnancy_status"]
        p["pregnancy_order"] = 0 if int(p["age"]) < 18 else p["pregnancy_order"]
    if p["marital_status"] == "unmarried" and not p["has_upcoming_marriage"]:
        p["daughters_count"] = p["sons_count"] = 0

    # Class IV / Group D staff are exempted from the coercion on purpose: a Group D
    # employee who also farms is a real person, and PM-KISAN's carve-out is written for
    # exactly them. Collapsing their occupation to salaried_government would make the
    # carve-out untestable.
    if (p["is_government_employee"] and not p["is_class_iv_employee"]
            and p["occupation"] not in {"salaried_government", "retired"}):
        p["occupation"] = "salaried_government"
    p["is_government_employee"] = p["occupation"] == "salaried_government" or p["is_government_employee"]

    if p["is_income_tax_payer"]:
        p["family_has_income_tax_payer"] = True
        p["annual_family_income"] = max(int(p["annual_family_income"]), 480000)
    if p["annual_family_income"] > 700000:
        p["family_has_income_tax_payer"] = True

    if p["is_destitute"]:
        p["annual_family_income"] = min(int(p["annual_family_income"]), 36000)
        p["fixed_assets_value"] = min(float(p["fixed_assets_value"]), 50000.0)
        p["receives_other_pension"] = False
        p["is_income_tax_payer"] = False
        p["family_has_income_tax_payer"] = False

    if p["is_bpl"]:
        p["annual_family_income"] = min(int(p["annual_family_income"]), 120000)
        if p["ration_card_type"] not in {"aay", "phh_rice"}:
            p["ration_card_type"] = "phh_rice"
        p["is_income_tax_payer"] = False
        p["family_has_income_tax_payer"] = False
    if p["annual_family_income"] > 150000:
        p["is_bpl"] = False
        p["is_secc_deprived_household"] = False

    if p["is_member_of_fishermen_cooperative"] and p["occupation"] != "fisher":
        p["is_member_of_fishermen_cooperative"] = False
    if p["has_vending_certificate"] and not (
            p["occupation"] in {"self_employed", "daily_wage"} and p["residence_type"] == "urban"):
        p["has_vending_certificate"] = False
    if p["employment_exchange_registration_years"] and p["occupation"] != "unemployed":
        p["employment_exchange_registration_years"] = 0
    if p["traditional_trade"] != "none" and p["occupation"] not in {
            "artisan", "weaver", "self_employed", "daily_wage"}:
        p["traditional_trade"] = "none"
    if p["is_orphan"]:
        p["is_daughter_of_widow"] = False
    if p["occupation"] == "fisher":
        p["district"] = p["district"] if p["district"] in COASTAL else "Nagapattinam"
    if p["is_srilankan_tamil_refugee"]:
        p["is_inter_state_migrant"] = False

    # money and counts must stay in their declared domains
    p["annual_family_income"] = int(max(0, min(int(p["annual_family_income"]), 100000000)))
    p["age"] = int(max(0, min(int(p["age"]), 120)))
    p["daughters_count"] = int(max(0, min(int(p["daughters_count"]), 15)))
    p["sons_count"] = int(max(0, min(int(p["sons_count"]), 15)))
    p["family_size"] = int(max(1, min(int(p["family_size"]),
                                      2 + p["daughters_count"] + p["sons_count"] + 2)))
    p["disability_percent"] = int(max(0, min(int(p["disability_percent"]), 100)))
    p["previous_exam_percent"] = int(max(0, min(int(p["previous_exam_percent"]), 100)))
    return p


# ------------------------------------------------------------- threshold nudging

def numeric_thresholds(kb) -> dict[str, list[float]]:
    """Every numeric boundary any rule in the KB tests, by attribute.

    Read out of the rules rather than written down here, so that adding a scheme
    automatically puts its thresholds into the near-miss pool.
    """
    out: dict[str, set[float]] = {}
    for scheme in kb:
        for node in scheme.eligibility.walk():
            if isinstance(node, Predicate) and kb.spec[node.attr].type == "number":
                values = node.value if isinstance(node.value, (list, tuple)) else [node.value]
                for v in values:
                    if isinstance(v, (int, float)) and not isinstance(v, bool):
                        out.setdefault(node.attr, set()).add(float(v))
    return {k: sorted(v) for k, v in out.items()}


def nudge_to_threshold(p: dict[str, Any], thresholds: dict[str, list[float]],
                       rng: random.Random) -> str | None:
    """Move one numeric attribute to just inside or just outside a real rule boundary."""
    attr = rng.choice([a for a in thresholds if a in p])
    bound = rng.choice(thresholds[attr])
    if attr == "annual_family_income":
        step = rng.choice([12, 120, 1200, 6000])
        value = bound + rng.choice([-step, -12, 0, 12, step])
        value = max(0, int(round(value / 12)) * 12)
    elif attr in {"age", "daughters_count", "sons_count", "pregnancy_order",
                  "years_since_desertion", "employment_exchange_registration_years",
                  "disability_percent", "previous_exam_percent"}:
        value = max(0, int(bound) + rng.choice([-1, 0, 0, 1]))
    elif attr in {"land_owned_acres", "wetland_acres", "dryland_acres"}:
        value = max(0.0, round(bound + rng.choice([-0.1, -0.01, 0.0, 0.01, 0.1]), 2))
        attr = "land_owned_acres"
    else:
        value = max(0.0, round(bound + rng.choice([-1000, -1, 0, 1, 1000]), 2))
    p[attr] = value
    return f"{attr}={value} against a rule boundary of {bound:g}"


# ------------------------------------------------------------------ query making

# Facts a person would only state when they are true, or which read as nonsense
# otherwise ("I have zero percent disability"). Filtering here rather than in the
# renderers keeps the lexicon a pure surface-form table.
_ONLY_IF_TRUE = {
    "has_upcoming_marriage", "is_orphan", "is_daughter_of_widow", "is_destitute",
    "is_srilankan_tamil_refugee", "is_head_of_household", "receives_other_pension",
    "owns_four_wheeler", "is_government_employee", "is_income_tax_payer",
    "has_mgnrega_job_card", "has_vending_certificate",
    "is_member_of_fishermen_cooperative", "employment_exchange_registration_years",
}


def _is_sayable(p: dict[str, Any], attr: str) -> bool:
    """Would this person say this, and does the lexicon have words for it?"""
    if attr in _ONLY_IF_TRUE:
        return bool(p.get(attr))
    if attr == "pregnancy_status":
        return p["pregnancy_status"] != "not_applicable"
    if attr == "pregnancy_order":
        return p["pregnancy_status"] != "not_applicable" and p["pregnancy_order"] > 0
    if attr == "years_since_desertion":
        return p["marital_status"] == "deserted"
    if attr == "disability_percent":
        return p["disability_percent"] >= 40
    if attr == "education_level":
        return p["education_level"] in EDUCATION
    if attr == "spouse_is_government_employee":
        return p["marital_status"] == "married"
    if attr == "enrolled_in_higher_education":
        return bool(p["enrolled_in_higher_education"])
    if attr == "studied_in_government_school":
        return p["occupation"] == "student" or p["enrolled_in_higher_education"]
    if attr == "has_lpg_connection":
        return not p["has_lpg_connection"]
    return True


def choose_facts(p: dict[str, Any], rng: random.Random) -> list[str]:
    """Two to five attributes the person would actually volunteer, archetype-aware."""
    salient: list[str] = ["occupation"]
    if p["marital_status"] in {"widowed", "deserted", "divorced"}:
        salient.append("marital_status")
    if p["pregnancy_status"] != "not_applicable":
        salient.append("pregnancy_status")
    if p["disability_percent"] >= 40:
        salient.append("disability_percent")
    if p["has_upcoming_marriage"]:
        salient.append("has_upcoming_marriage")
    if p["is_srilankan_tamil_refugee"]:
        salient.append("is_srilankan_tamil_refugee")
    if p["land_owned_acres"] > 0:
        salient.append("land_owned_acres")
    if p["occupation"] == "student":
        salient.append("enrolled_in_higher_education")

    optional = [a for a in REVEALABLE
                if a not in salient and a != "_children" and _is_sayable(p, a)]
    rng.shuffle(optional)
    facts = salient[:3] + optional[: rng.randint(1, 3)]
    if p["daughters_count"] + p["sons_count"] > 0 and rng.random() < 0.25:
        facts.append("_children")
    seen: list[str] = []
    for f in facts:
        if f not in seen:
            seen.append(f)
    return seen[:5]


def build_query(p: dict[str, Any], facts: list[str], rng: random.Random) -> tuple[str, str, list[str]]:
    """Render one fact list into both conditions. Returns (code_mixed, english, stated)."""
    cm_parts: list[str] = []
    en_parts: list[str] = []
    stated: list[str] = []
    for fact in facts:
        value = (p["daughters_count"], p["sons_count"]) if fact == "_children" else p[fact]
        cm, en = RENDERERS[fact](value, rng)
        cm_parts.append(cm)
        en_parts.append(en)
        stated.extend(["daughters_count", "sons_count"] if fact == "_children" else [fact])

    open_cm, open_en = rng.choice(OPENERS)
    close_cm, close_en = rng.choice(CLOSERS)
    cm = ", ".join(([open_cm] if open_cm else []) + cm_parts) + ". " + close_cm
    en = ". ".join(([open_en] if open_en else []) + [s[0].upper() + s[1:] for s in en_parts]) + ". " + close_en
    return cm, en, stated


# ---------------------------------------------------------------------- writing

def persona_document(pid: str, sketch: str, profile: dict[str, Any], cm: str, en: str,
                     stated: list[str], design_note: str) -> str:
    doc = {
        "id": pid,
        "persona_sketch": sketch,
        "profile": profile,
        "queries": {"code_mixed": cm, "english": en},
        "stated_in_query": stated,
        "annotation": {
            "author": "generated by scripts/generate_personas.py",
            "validated_by": "",
            "validated_on": "",
            "codemix_naturalness": None,
            "profile_plausibility": None,
            "parallel_faithful": None,
            "notes": (
                "SYNTHETIC PERSONA — NOT YET NATIVELY VALIDATED. Profile sampled from an "
                "archetype distribution; both query variants rendered from one fact list, so "
                "they reveal the same attributes by construction. What construction cannot "
                "certify is whether the code-mixed variant reads like something a person "
                "would type — that is what the native pass is for, and until it is done this "
                "persona must not be counted in any reported result. "
                + design_note
            ),
        },
    }
    return yaml.safe_dump(doc, allow_unicode=True, sort_keys=False, width=100)


def write(path: Path, text: str, written_files: set[Path]) -> None:
    path.write_text(text, encoding="utf-8")
    written_files.add(path)


def retire(paths: list[Path]) -> None:
    """Remove personas from a previous, larger run so their ids cannot reappear.

    Falls back to moving them aside when the filesystem refuses deletion — some
    sandboxed and network mounts do — because leaving them in place would silently
    reintroduce duplicate ids on the next load, which fails loudly but confusingly.
    """
    trash = REPO_ROOT / ".trash"
    for path in paths:
        try:
            path.unlink()
        except OSError:
            trash.mkdir(exist_ok=True)
            path.rename(trash / path.name)
            print(f"could not delete {path.name}; moved it to {trash}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--n", type=int, default=200, help="how many sampled personas")
    parser.add_argument("--seed", type=int, default=20260904)
    parser.add_argument("--pairs", type=int, default=12, help="minimal pairs to append")
    parser.add_argument("--out", default=str(OUT_DIR))
    parser.add_argument("--keep", action="store_true", help="do not clear the output directory first")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    kb = load_kb()
    spec = default_spec()
    thresholds = numeric_thresholds(kb)
    active = kb.active()

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stale = sorted(out_dir.glob("*.yaml")) if not args.keep else []

    names = [a[0] for a in ARCHETYPES]
    weights = [a[2] for a in ARCHETYPES]
    builders = {a[0]: a[1] for a in ARCHETYPES}

    written_files: set[Path] = set()
    written = 0
    attempts = 0
    rejected = 0
    empty_gold = 0
    while written < args.n and attempts < args.n * 40:
        attempts += 1
        arch = rng.choices(names, weights)[0]
        profile = repair(builders[arch](base_profile(rng), rng))
        design = f"Archetype: {arch}."
        if rng.random() < 0.5:
            note = nudge_to_threshold(profile, thresholds, rng)
            profile = repair(profile)
            design += f" Placed at a rule boundary: {note}."

        try:
            normalized = spec.normalize_profile(profile)
        except Exception:
            rejected += 1
            continue
        if active.match(normalized)[Verdict.UNKNOWN]:
            rejected += 1
            continue

        facts = choose_facts(profile, rng)
        cm, en, stated = build_query(profile, facts, rng)
        gold = active.eligible_ids(normalized)
        if not gold:
            empty_gold += 1
        pid = f"g{written + 1:03d}"
        sketch = f"{arch.replace('-', ' ')}, {int(profile['age'])}, {profile['district']}"
        design += f" Gold set at generation time: {gold or 'empty'}."
        # Filenames are the id alone, and therefore stable across regenerations: a rerun
        # with the same --n overwrites in place rather than leaving a shadow set behind
        # with duplicate ids.
        write(out_dir / f"{pid}.yaml",
              persona_document(pid, sketch, profile, cm, en, stated, design), written_files)
        written += 1

    # ---- targeted personas: close the benchmark's own coverage gaps ------------
    # coverage_gaps() reports three things a benchmark can be blind to: schemes nobody is
    # eligible for, exclusion clauses that are never the reason anybody fails, and
    # attributes that never vary. Sampling from archetype distributions does not reach the
    # rare corners — nobody random is a Sri Lankan refugee remarrying at 38 — so these are
    # specified by hand, each with the gap it exists to close, and each verified below to
    # actually close it.
    targeted = 0
    for name, why, overrides, expect in TARGETED:
        profile = repair({**base_profile(rng), **overrides})
        try:
            normalized = spec.normalize_profile(profile)
        except Exception as exc:
            print(f"targeted persona {name} does not normalize: {exc}")
            continue
        if active.match(normalized)[Verdict.UNKNOWN]:
            print(f"targeted persona {name} leaves schemes undetermined")
            continue
        gold = set(active.eligible_ids(normalized))
        if expect and expect not in gold:
            print(f"targeted persona {name} was meant to reach {expect} and did not "
                  f"(gold: {sorted(gold) or 'empty'})")
        facts = choose_facts(profile, rng)
        cm, en, stated = build_query(profile, facts, rng)
        targeted += 1
        pid = f"t{targeted:03d}"
        note = (f"TARGETED PERSONA — written by hand to close a coverage gap, not sampled. "
                f"{why} Gold set at generation time: {sorted(gold) or 'empty'}.")
        write(out_dir / f"{pid}.yaml",
              persona_document(pid, name, profile, cm, en, stated, note), written_files)

    # ---- minimal pairs: identical queries, one attribute apart -----------------
    pair_specs = [
        ("gender", "female", "male"),
        ("social_category", "SC", "FC"),
        ("studied_in_government_school", True, False),
        ("course_mode", "regular", "distance"),
        ("is_destitute", True, False),
        ("owns_four_wheeler", False, True),
        ("has_undergone_family_planning", True, False),
        ("is_covered_by_epfo_esic_nps", False, True),
        ("spouse_is_government_employee", False, True),
        ("receives_other_pension", False, True),
        ("has_vending_certificate", True, False),
        ("is_member_of_fishermen_cooperative", True, False),
    ]
    made = 0
    guard = 0
    while made < args.pairs and guard < args.pairs * 200:
        guard += 1
        attr, va, vb = pair_specs[made % len(pair_specs)]
        arch = rng.choices(names, weights)[0]
        profile = repair(builders[arch](base_profile(rng), rng))
        a = repair({**profile, attr: va})
        b = repair({**profile, attr: vb})
        diff = {k for k in a if a[k] != b[k]}
        if diff != {attr}:
            continue
        try:
            na, nb = spec.normalize_profile(a), spec.normalize_profile(b)
        except Exception:
            continue
        if active.match(na)[Verdict.UNKNOWN] or active.match(nb)[Verdict.UNKNOWN]:
            continue
        if active.eligible_ids(na) == active.eligible_ids(nb):
            continue  # the flip changes nothing, so the pair tests nothing
        facts = choose_facts(a, rng)
        if attr in facts:
            continue  # the query would give the difference away
        cm, en, stated = build_query(a, facts, rng)
        made += 1
        for suffix, prof in (("a", a), ("b", b)):
            pid = f"m{made:03d}{suffix}"
            note = (f"MINIMAL PAIR m{made:03d}: this persona and its twin differ in exactly "
                    f"one attribute, {attr}, which the query does not state. Archetype: {arch}. "
                    f"The two gold sets differ, so the pair isolates that one constraint from "
                    f"every other source of difficulty.")
            write(out_dir / f"{pid}.yaml",
                  persona_document(pid, f"minimal pair on {attr} ({suffix})", prof, cm, en, stated, note),
                  written_files)

    left_behind = [f for f in stale if f not in written_files]
    if left_behind:
        # Retiring is how ids from a larger previous run are stopped from reappearing.
        # But if this run under-produced — because base_profile() is missing a key the
        # spec now declares, so every candidate is rejected — then retiring deletes the
        # personas the short run failed to replace, and the benchmark silently shrinks.
        # A short run is a bug in the generator, never a licence to delete.
        if written < args.n:
            print(f"REFUSING TO RETIRE: wrote {written} of {args.n} requested sampled "
                  f"personas, so {len(left_behind)} existing file(s) were left in place.\n"
                  f"         A short run usually means base_profile() does not cover the "
                  f"attribute spec. Fix that before regenerating.")
            return 1
        retire(left_behind)

    personas = load_personas()
    problems = validate_personas(personas, kb)
    print(f"wrote {written} sampled personas ({rejected} candidates rejected, "
          f"{empty_gold} with an empty gold set), {targeted} targeted personas and "
          f"{made} minimal pairs into {out_dir}")
    print(f"persona set now {len(personas)} personas over {len(kb)} schemes")
    if problems:
        print(f"\nVALIDATION FAILED with {len(problems)} problem(s):")
        for problem in problems[:20]:
            print(f"  - {problem}")
        return 1
    print("validate_personas: no problems")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
