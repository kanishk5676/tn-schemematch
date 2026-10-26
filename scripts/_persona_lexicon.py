"""Surface renderings of a fact, in code-mixed Tamil-English and in clean English.

Every test profile carries its opening sentence in two registers, and both must reveal
*exactly* the same facts. Rather than
authoring two texts and hoping they match, this module renders each fact once into both
registers from a single entry, and the query builder emits the same fact list to both.
Faithfulness of the parallel is then a property of the construction, not a judgement an
annotator has to make persona by persona.

That is a weaker guarantee than it sounds, and the weakness is the point of the native
validation the generated set still needs: the two variants provably carry the same
*facts*, but only a native speaker can say whether the Tamil-English one carries them the
way a person would actually type them. Template naturalness is exactly what a template
cannot certify about itself.

Registers used, deliberately mixed within a single query, as real messages are:
  * romanised Tamil with English content words  — "enkitta rendu ekkar nilam irukku"
  * Tamil script                                — "எனக்கு ரேஷன் கார்டு இருக்கு"
  * bare English nouns inside Tamil syntax      — "ration card irukku"
"""

from __future__ import annotations

import random
from typing import Any, Callable

# A renderer maps (value, rng) -> (code_mixed, english).
Renderer = Callable[[Any, random.Random], tuple[str, str]]


def _pick(rng: random.Random, options: list[tuple[str, str]]) -> tuple[str, str]:
    return rng.choice(options)


def _inr(value: float) -> str:
    """Indian digit grouping, e.g. 1,20,000."""
    n = int(round(value))
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def _num(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


# --------------------------------------------------------------------- renderers

OCCUPATION: dict[str, list[tuple[str, str]]] = {
    "farmer": [
        ("naan oru vivasayi", "I am a farmer"),
        ("naan vivasayam thaan pannuren", "I do farming"),
        ("நான் விவசாயி", "I am a farmer"),
    ],
    "agri_labourer": [
        ("naan vivasaya cooli velai paakuren", "I work as an agricultural labourer"),
        ("innoruthar nilathula cooli velai thaan", "I do farm labour on someone else's land"),
    ],
    "daily_wage": [
        ("naan kooli velai paakuren", "I do daily wage work"),
        ("naan construction velaikku poren", "I work as a construction labourer"),
        ("தினக்கூலி வேலை தான் பாக்குறேன்", "I work as a daily wage labourer"),
    ],
    "fisher": [
        ("naan meenavar, kadalukku poren", "I am a fisherman and I go out to sea"),
        ("naan meen pidikkira velai thaan", "I work in fishing"),
    ],
    "weaver": [
        ("naan kaithari nesavalar", "I am a handloom weaver"),
        ("naan thari velai paakuren", "I work at a loom"),
    ],
    "artisan": [
        ("naan kai velai seyyra thozhilali", "I am a craftsman working with my hands"),
        ("naan thachu velai paakuren", "I do carpentry work"),
    ],
    "self_employed": [
        ("enakku oru chinna kadai irukku", "I run a small shop"),
        ("naan sontha thozhil pannuren", "I am self-employed"),
        ("enakku oru petti kadai irukku", "I have a small roadside stall"),
    ],
    "salaried_private": [
        ("naan oru private company la velai paakuren", "I work in a private company"),
        ("private job thaan pannuren", "I have a private sector job"),
    ],
    "salaried_government": [
        ("naan arasu velaila iruken", "I work in a government job"),
        ("அரசு வேலையில் இருக்கேன்", "I am a government employee"),
    ],
    "student": [
        ("naan padikkiren", "I am a student"),
        ("naan college la padikkiren", "I am studying in college"),
        ("நான் இப்போ படிக்கிறேன்", "I am studying at the moment"),
    ],
    "homemaker": [
        ("naan veetla thaan iruken, velai edhuvum illa", "I am a homemaker and do not work outside"),
        ("naan illatharasi", "I am a housewife"),
    ],
    "unemployed": [
        ("enakku ippo velai illa", "I do not have a job right now"),
        ("velai thedittu iruken", "I am looking for work"),
    ],
    "retired": [
        ("naan ooivu petruttén", "I have retired"),
        ("retire aayiduchu", "I am retired now"),
    ],
}

MARITAL: dict[str, list[tuple[str, str]]] = {
    "widowed": [
        ("en kanavar iranthu poitaru", "my husband passed away"),
        ("naan vidhavai", "I am a widow"),
        ("என் கணவர் இறந்துட்டாரு", "my husband has died"),
    ],
    "deserted": [
        ("en kanavan enna vittutu poitaru", "my husband left me"),
        ("kanavar kaividitaru", "I was abandoned by my husband"),
    ],
    "divorced": [
        ("naan divorce aayiten", "I am divorced"),
        ("court la vivagarathu aayiduchu", "my divorce came through in court"),
    ],
    "unmarried": [
        ("enakku innum kalyanam aagala", "I am not married yet"),
        ("naan thanila thaan iruken, kalyanam aagala", "I live alone and am unmarried"),
    ],
    "married": [
        ("enakku kalyanam aachu", "I am married"),
        ("naan kalyanam aana pombala", "I am a married woman"),
    ],
}

CATEGORY: dict[str, list[tuple[str, str]]] = {
    "SC": [("naan SC community", "I belong to the SC community"),
           ("naan adi dravidar", "I am from a Scheduled Caste")],
    "SCA": [("naan arunthathiyar", "I belong to the Arunthathiyar community")],
    "ST": [("naan pazhangudi makkal", "I belong to a Scheduled Tribe"),
           ("naan ST community", "I am from a Scheduled Tribe")],
    "MBC": [("naan MBC", "I belong to the MBC category")],
    "BC": [("naan BC", "I belong to the BC category")],
    "BCM": [("naan BC Muslim", "I belong to the BC Muslim category")],
    "DNC": [("naan denotified community", "I belong to a denotified community")],
    "FC": [("naan OC community", "I am from the general category")],
}

HOUSE: dict[str, list[tuple[str, str]]] = {
    "owns_kutcha": [("naanga kudisai veetla thaan iruko", "we live in a thatched hut"),
                    ("veedu kudisai maadhiri thaan", "our house is only a hut")],
    "owns_pucca": [("enga sontha veedu irukku", "we own our house")],
    "rented": [("naanga vaadagai veetla iruko", "we live in a rented house")],
    "homeless": [("enga kitta veedu illa", "we have no house of our own")],
}

RATION: dict[str, list[tuple[str, str]]] = {
    "phh_rice": [("enkitta arisi ration card irukku", "I have a rice ration card"),
                 ("எனக்கு ரேஷன் கார்டு இருக்கு", "I have a ration card")],
    "aay": [("enkitta antyodaya card irukku", "I have an Antyodaya ration card")],
    "nphh_sugar": [("enkitta sakkarai card thaan irukku", "I only have a sugar ration card")],
    "nphh_no_commodity": [("enkitta no-commodity card thaan", "I have a no-commodity card")],
    "none": [("enkitta ration card e illa", "I do not have a ration card")],
}

RESIDENCE: dict[str, list[tuple[str, str]]] = {
    "rural": [("naan kirama pakkam iruken", "I live in a village"),
              ("enga ooru panchayat thaan", "my place comes under a village panchayat")],
    "urban": [("naan city la iruken", "I live in the city"),
              ("naanga corporation area la iruko", "we live inside the municipal area")],
}

EDUCATION: dict[str, list[tuple[str, str]]] = {
    "none": [("naan padikkala", "I never went to school")],
    "primary": [("5th varaikum thaan padichen", "I studied up to class 5")],
    "middle": [("8th varaikum padichen", "I studied up to class 8")],
    "secondary": [("naan 10th padichirukken", "I have passed class 10")],
    "higher_secondary": [("naan 12th mudichiruken", "I have completed class 12"),
                         ("+2 mudichachu", "I finished plus two")],
    "iti_diploma": [("naan ITI mudichen", "I completed ITI")],
    "undergraduate": [("naan degree mudichiruken", "I have a degree")],
    "postgraduate": [("naan PG mudichiruken", "I have a postgraduate degree")],
}

PREGNANCY: dict[str, list[tuple[str, str]]] = {
    "pregnant": [("naan ippo karpiniya iruken", "I am pregnant at the moment"),
                 ("நான் கர்ப்பிணி", "I am pregnant")],
    "lactating": [("kozhandhaikku paal koduthuttu iruken", "I am breastfeeding my baby")],
}


def _render_map(table: dict[str, list[tuple[str, str]]]) -> Renderer:
    def render(value: Any, rng: random.Random) -> tuple[str, str]:
        return _pick(rng, table[value])
    return render


def _age(value: Any, rng: random.Random) -> tuple[str, str]:
    n = int(value)
    return _pick(rng, [
        (f"enakku {n} vayasu", f"I am {n} years old"),
        (f"vayasu {n} aaguthu", f"my age is {n}"),
        (f"எனக்கு {n} வயசு", f"I am {n} years old"),
    ])


def _income(value: Any, rng: random.Random) -> tuple[str, str]:
    annual = float(value)
    monthly = annual / 12
    options = [(f"varushathukku {_inr(annual)} rupaa varum", f"my family earns about {_inr(annual)} rupees a year")]
    if abs(monthly - round(monthly)) < 1e-6:
        m = _inr(monthly)
        options += [
            (f"maasam {m} rupaa thaan varum", f"we earn around {m} rupees a month"),
            (f"month-ku {m} kedaikum", f"the monthly income is about {m} rupees"),
        ]
    if annual >= 100000 and abs(annual / 100000 - round(annual / 100000, 2)) < 1e-9:
        options.append((f"varushathukku {_num(round(annual / 100000, 2))} laksham varum",
                        f"our annual income is about {_num(round(annual / 100000, 2))} lakh rupees"))
    return _pick(rng, options)


def _land(value: Any, rng: random.Random) -> tuple[str, str]:
    acres = float(value)
    if acres == 0:
        return _pick(rng, [("enkitta nilam edhuvum illa", "I do not own any land"),
                           ("sontha nilam illa", "I have no land of my own")])
    if abs(acres * 100 - round(acres * 100)) < 1e-9 and acres < 1:
        cents = int(round(acres * 100))
        return _pick(rng, [(f"enkitta {cents} cent nilam irukku", f"I own {cents} cents of land")])
    word = {1: "oru", 2: "rendu", 3: "moonu", 4: "naalu", 5: "anju"}.get(
        int(acres) if float(acres).is_integer() else 0)
    options = [(f"enkitta {_num(acres)} ekkar nilam irukku", f"I have {_num(acres)} acres of land")]
    if word:
        options.append((f"enkitta {word} ekkar nilam irukku", f"I own {_num(acres)} acres of land"))
    return _pick(rng, options)


def _disability(value: Any, rng: random.Random) -> tuple[str, str]:
    p = int(value)
    return _pick(rng, [
        (f"enakku {p}% maatru thiranali certificate irukku", f"I have a disability certificate for {p} percent"),
        (f"enakku {p} percent ooname irukku", f"I have a certified disability of {p} percent"),
    ])


def _children(value: Any, rng: random.Random) -> tuple[str, str]:
    """Rendered from the (daughters, sons) pair, which is passed as a tuple."""
    girls, boys = value
    tam = {0: "", 1: "oru", 2: "rendu", 3: "moonu"}
    eng = {0: "no", 1: "one", 2: "two", 3: "three"}
    g, b = int(girls), int(boys)
    if g and not b:
        return (f"enakku {tam.get(g, g)} ponnu, paiyan kidaiyaadhu",
                f"I have {eng.get(g, g)} daughter{'s' if g > 1 else ''} and no sons")
    if b and not g:
        return (f"enakku {tam.get(b, b)} paiyan, ponnu kidaiyaadhu",
                f"I have {eng.get(b, b)} son{'s' if b > 1 else ''} and no daughters")
    if g and b:
        return (f"enakku {tam.get(g, g)} ponnu {tam.get(b, b)} paiyan",
                f"I have {eng.get(g, g)} daughter{'s' if g > 1 else ''} and {eng.get(b, b)} son{'s' if b > 1 else ''}")
    return ("enakku kozhandhaigal illa", "I have no children")


def _bool_fact(true_forms: list[tuple[str, str]], false_forms: list[tuple[str, str]]) -> Renderer:
    def render(value: Any, rng: random.Random) -> tuple[str, str]:
        return _pick(rng, true_forms if value else false_forms)
    return render


RENDERERS: dict[str, Renderer] = {
    "age": _age,
    "annual_family_income": _income,
    "land_owned_acres": _land,
    "disability_percent": _disability,
    "occupation": _render_map(OCCUPATION),
    "marital_status": _render_map(MARITAL),
    "social_category": _render_map(CATEGORY),
    "house_ownership": _render_map(HOUSE),
    "ration_card_type": _render_map(RATION),
    "residence_type": _render_map(RESIDENCE),
    "education_level": _render_map(EDUCATION),
    "pregnancy_status": _render_map(PREGNANCY),
    "_children": _children,
    "is_destitute": _bool_fact(
        [("enakku yaarum thunai illa, varumanam edhuvum illa", "I have no one to support me and no income"),
         ("naan aadharavatra nilamaila iruken", "I am destitute")],
        [("enakku konjam varumanam irukku", "I do have some income")]),
    "is_head_of_household": _bool_fact(
        [("ration card la naan thaan kudumba thalaivi", "I am the head of the family on the ration card")],
        [("card la en peru thalaivara illa", "I am not the head of the family on the card")]),
    "enrolled_in_higher_education": _bool_fact(
        [("ippo naan degree padichittu iruken", "I am currently doing a degree course"),
         ("college first year padikkiren", "I am in the first year of college")],
        [("ippo naan padikkala", "I am not studying now")]),
    "studied_in_government_school": _bool_fact(
        [("naan arasu palliyila thaan padichen", "I studied in a government school")],
        [("naan private school la padichen", "I studied in a private school")]),
    "has_upcoming_marriage": _bool_fact(
        [("adutha maasam en kalyanam nadakuthu", "my marriage is fixed for next month"),
         ("kalyanam fix aayiduchu", "my wedding has been arranged")],
        [("kalyanam edhuvum fix aagala", "no marriage is arranged")]),
    "is_orphan": _bool_fact(
        [("en amma appa rendu perum illa", "both my parents have died")],
        [("en appa amma irukanga", "my parents are alive")]),
    "is_daughter_of_widow": _bool_fact(
        [("en amma vidhavai", "my mother is a widow")],
        [("en appa amma rendu perum irukanga", "both my parents are living")]),
    "has_lpg_connection": _bool_fact(
        [("veetla gas connection irukku", "we have an LPG connection at home")],
        [("veetla gas connection illa, viragu thaan", "we have no gas connection and cook on firewood")]),
    "is_member_of_fishermen_cooperative": _bool_fact(
        [("naan meenavar sangathula member", "I am a member of the fishermen cooperative society")],
        [("naan endha sangathulayum member illa", "I am not a member of any society")]),
    "has_vending_certificate": _bool_fact(
        [("enakku vending certificate irukku", "I have a vending certificate from the corporation")],
        [("enakku vending certificate illa", "I do not have a vending certificate")]),
    "is_srilankan_tamil_refugee": _bool_fact(
        [("naan ilangai thamizh agathi, muhamaila iruken", "I am a Sri Lankan Tamil refugee living in a camp")],
        [("naan ingayé porandhavan", "I was born here")]),
    "receives_other_pension": _bool_fact(
        [("enakku ippove oru pension varuthu", "I already receive a government pension")],
        [("enakku endha pension-um varala", "I do not receive any pension")]),
    "owns_four_wheeler": _bool_fact(
        [("enga veetla car irukku", "we own a car")],
        [("enga kitta four wheeler edhuvum illa", "we do not own any four wheeler")]),
    "is_government_employee": _bool_fact(
        [("naan arasu ooziyar", "I am a government employee")],
        [("naan arasu velaila illa", "I am not a government employee")]),
    "spouse_is_government_employee": _bool_fact(
        [("en kanavar arasu velaila iruvaru", "my husband works in a government job")],
        [("en kanavarukku arasu velai illa", "my husband is not a government employee")]),
    "is_income_tax_payer": _bool_fact(
        [("naan income tax kattren", "I pay income tax")],
        [("naan income tax kattradhu illa", "I do not pay income tax")]),
    "has_mgnrega_job_card": _bool_fact(
        [("enkitta nooru naal velai job card irukku", "I have an MGNREGA job card")],
        [("job card edhuvum illa", "I have no job card")]),
    "employment_exchange_registration_years": lambda v, rng: (
        (f"employment exchange la {int(v)} varusham munnadi peru koduthiruken",
         f"I registered at the employment exchange {int(v)} years ago")
        if v else ("employment exchange la peru kodukala", "I have not registered at the employment exchange")),
    "years_since_desertion": lambda v, rng: (
        (f"anju varushathukku mela aachu avaru vittu poi" if int(v) >= 5 else f"{int(v)} varusham aachu avaru vittu poi",
         f"it has been more than five years since he left" if int(v) >= 5 else f"it has been {int(v)} years since he left")),
    "pregnancy_order": lambda v, rng: (
        (f"idhu en {int(v)}-vadhu prasavam", f"this is my {['', 'first', 'second', 'third', 'fourth'][int(v)] if int(v) < 5 else str(int(v))} pregnancy")),
    "district": lambda v, rng: _pick(rng, [
        (f"naan {v} district la iruken", f"I live in {v} district"),
        (f"naan {v} pakkam thaan iruken", f"I am from {v}"),
    ]),
}

OPENERS = [
    ("vanakkam", "Hello"),
    ("vanakkam sir", "Hello sir"),
    ("namaskaram", "Good morning"),
    ("", ""),
    ("", ""),
]

CLOSERS = [
    ("enakku enna scheme laam kedaikum?", "Which schemes can I get?"),
    ("naan endha thittathukku apply panna mudiyum?", "Which schemes am I able to apply for?"),
    ("government kitta irundhu enna help kedaikum?", "What help can I get from the government?"),
    ("enakku edhachum scheme irukka?", "Is there any scheme for me?"),
    ("இதுக்கு ஏதாவது திட்டம் இருக்கா?", "Is there any government scheme for this?"),
]
