"""What the person hears about their result, built from the rule engine and nothing else.

Every chat reply carries a ``spoken`` field next to the model's ``reply``. The page reads
the reply aloud and then this. Because it is assembled here — from the verdicts, the
plain-language text in each scheme file, and the document checklist — what a person hears
about eligibility never depends on what a model chose to say. A model that called someone
eligible for a scheme the rules rule out is contradicted out loud, in their language.

Two kinds of "yes" are kept apart. A scheme whose rule a person has checked against the
Government Order is said as "you can apply"; every other one as "you may be able to —
confirm at the office". Today most rules are still drafts, so most people hear the second.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .documents import DocumentVocabulary, checklist
from .kb import Scheme, SchemeKB
from .rules import Verdict

MAX_SPOKEN_SCHEMES = 5
MAX_SPOKEN_DOCUMENTS = 4
MAX_SPOKEN_SUMMARY = 140

_T: dict[str, dict[str, str]] = {
    "found_verified": {
        "ta": "நீங்கள் {n} திட்டங்களுக்கு விண்ணப்பிக்கலாம்.",
        "en": "You can apply for {n} schemes.",
    },
    "found_verified_one": {
        "ta": "நீங்கள் ஒரு திட்டத்துக்கு விண்ணப்பிக்கலாம்.",
        "en": "You can apply for 1 scheme.",
    },
    "found_draft": {
        "ta": "உங்களுக்கு {n} திட்டங்கள் கிடைக்க வாய்ப்பு உள்ளது.",
        "en": "You may be able to get {n} schemes.",
    },
    "found_draft_one": {
        "ta": "உங்களுக்கு ஒரு திட்டம் கிடைக்க வாய்ப்பு உள்ளது.",
        "en": "You may be able to get 1 scheme.",
    },
    "more": {
        "ta": "இன்னும் {n} திட்டங்கள் திரையில் உள்ளன.",
        "en": "{n} more are on the screen.",
    },
    "documents": {
        "ta": "கொண்டு செல்ல வேண்டியவை: {items}.",
        "en": "Bring: {items}.",
    },
    "documents_ready": {
        "ta": "தேவையான ஆவணங்கள் எல்லாம் உங்களிடம் உள்ளன.",
        "en": "You already have all the documents these need.",
    },
    "where": {"ta": "எங்கே: {places}.", "en": "Where: {places}."},
    "confirm": {
        "ta": "இவை இன்னும் அரசு ஆணையுடன் சரிபார்க்கப்படவில்லை. விண்ணப்பிக்கும் முன் இ-சேவை மையத்திலோ துறை அலுவலகத்திலோ உறுதி செய்யுங்கள்.",
        "en": "These rules are not yet checked against the government order. Confirm at an e-Sevai centre or the department office before you apply.",
    },
    "near": {
        "ta": "{name}: ஒரே ஒரு நிபந்தனை மட்டும் பொருந்தவில்லை.",
        "en": "{name}: you miss it by just one condition.",
    },
    "none": {
        "ta": "நீங்கள் சொன்னவற்றை வைத்து, இப்போது எந்தத் திட்டமும் உறுதியாகவில்லை.",
        "en": "From what you have told me, no scheme is confirmed yet.",
    },
    "open": {
        "ta": "இன்னும் சில கேள்விகளுக்குப் பதில் சொன்னால் மேலும் திட்டங்கள் தெரியவரலாம்.",
        "en": "Answering a few more questions may find more.",
    },
    "or": {"ta": " அல்லது ", "en": " or "},
}


def _t(key: str, lang: str, **values: Any) -> str:
    text = _T[key].get(lang) or _T[key]["en"]
    return text.format(**values) if values else text


def spoken_name(scheme: Scheme, lang: str) -> str:
    return scheme.plain_text(lang, "name")


def spoken_what(scheme: Scheme, lang: str) -> str:
    """What the scheme gives, in ``lang`` only. An English summary read out by a Tamil
    voice is worse than silence, so Tamil falls back to nothing, not to English."""
    own = (scheme.plain.get(lang) or {}).get("what")
    if own:
        return own
    # The official summary is written to be read, not heard; past a sentence it is noise.
    if lang == "en" and len(scheme.summary) <= MAX_SPOKEN_SUMMARY:
        return scheme.summary
    return ""


def _join(items: list[str], lang: str) -> str:
    return ", ".join(item for item in items if item)


def scheme_line(scheme: Scheme, lang: str) -> dict[str, Any]:
    """One eligible scheme as the citizen sees and hears it."""
    return {
        "id": scheme.id,
        "name": spoken_name(scheme, lang),
        "official_name": scheme.name,
        "what": spoken_what(scheme, lang),
        "who": scheme.plain_text(lang, "who"),
        "where": scheme.plain_text(lang, "where"),
        "verified": scheme.is_verified,
        "sectors": list(scheme.sectors),
        "apply_url": scheme.apply_url,
    }


def spoken_result(active: SchemeKB, profile: Mapping[str, Any], lang: str, *,
                  documents: DocumentVocabulary | None = None,
                  held: Iterable[str] = (), near_ids: Iterable[str] = ()) -> dict[str, Any]:
    """The result, as one paragraph to read aloud and the lines it was built from.

    ``near_ids`` are schemes missed by a single condition (from
    :func:`~tn_schemematch.serialize.near_misses`), named after the eligible ones.
    """
    lang = "ta" if lang == "ta" else "en"
    buckets = active.match(profile)
    eligible = [active[i] for i in buckets[Verdict.TRUE]]
    # Verified first: the schemes a person can act on with the most confidence.
    eligible.sort(key=lambda s: (not s.is_verified, spoken_name(s, lang)))
    lines = [scheme_line(s, lang) for s in eligible]

    sentences: list[str] = []
    bring: list[dict[str, Any]] = []
    if eligible:
        all_verified = all(s.is_verified for s in eligible)
        key = "found_verified" if all_verified else "found_draft"
        sentences.append(_t(key + ("_one" if len(eligible) == 1 else ""), lang, n=len(eligible)))
        for line in lines[:MAX_SPOKEN_SCHEMES]:
            sentence = line["name"].rstrip(".")
            if line["what"]:
                sentence += " — " + line["what"].rstrip(".")
            sentences.append(sentence + ".")
        if len(lines) > MAX_SPOKEN_SCHEMES:
            sentences.append(_t("more", lang, n=len(lines) - MAX_SPOKEN_SCHEMES))

        if documents is not None:
            plan = checklist(documents, active, [s.id for s in eligible], held)
            # "Aadhaar" and "Aadhaar or ration card" are one trip, not two: an alternative
            # already covered by a document that must be brought anyway is not listed.
            needed = {e["types"][0]["id"] for e in plan["to_collect"] if len(e["types"]) == 1}
            for entry in plan["to_collect"]:
                ids = {t["id"] for t in entry["types"]}
                if len(ids) > 1 and ids & needed:
                    continue
                label = (entry.get("label_ta") if lang == "ta" else None) or entry["label"]
                bring.append({"label": label.replace(" / ", _t("or", lang))
                                       .replace(" or ", _t("or", lang)),
                              "n_schemes": entry["n_schemes"],
                              "types": [t["id"] for t in entry["types"]]})
            wanted = [item["label"] for item in bring[:MAX_SPOKEN_DOCUMENTS]]
            if wanted:
                sentences.append(_t("documents", lang, items=_join(wanted, lang)))
            elif plan["schemes"]:
                sentences.append(_t("documents_ready", lang))

        places = []
        for line in lines[:MAX_SPOKEN_SCHEMES]:
            if line["where"] and line["where"] not in places:
                places.append(line["where"].rstrip("."))
        if places:
            sentences.append(_t("where", lang, places=_join(places[:3], lang)))
        if not all_verified:
            sentences.append(_t("confirm", lang))
    else:
        sentences.append(_t("none", lang))

    near = [active[i] for i in near_ids if i in active][:2]
    for scheme in near:
        sentences.append(_t("near", lang, name=spoken_name(scheme, lang)))
    if buckets[Verdict.UNKNOWN] and not eligible:
        sentences.append(_t("open", lang))

    return {
        "text": " ".join(sentences),
        "eligible": lines,
        "near": [scheme_line(s, lang) for s in near],
        "bring": bring,
        "n_open": len(buckets[Verdict.UNKNOWN]),
        "lang": lang,
    }
