"""Help to apply: the application sheet for one scheme, and what opens up with age.

Eligibility is half the job; the other half is walking into the right office with the
right papers. The application sheet is one printable page per eligible scheme: what it
gives in plain words, the papers to bring with have/missing marks, the office to go to,
the facts the officer is likely to check (the clauses that decided the rule, with the
person's own answers), and the sources an officer can look up. It is built only for a
scheme the rule engine says the person is eligible for — a sheet for anything else would
send someone to an office to be turned away.

:func:`coming_up` answers a different question: "what will I be able to get later?". It
re-runs the rules with the person older by one to five years, everything else unchanged,
and lists the schemes that open — an old-age pension at sixty, a scheme at eighteen.
:func:`closing` is the other half: schemes the person has now that stop at an age, so
they can apply before then. Both also advance the other facts that count up by themselves
(``grows_with_time`` in the vocabulary, such as years registered at the employment
exchange).
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .attributes import AttributeSpec
from .benefits import value_text
from .documents import DocumentVocabulary, checklist
from .guided import QuestionBook, answer_text
from .kb import Scheme, SchemeKB
from .rules import Verdict
from .serialize import trace_to_dict
from .spoken import spoken_name, spoken_what

FORECAST_YEARS = 5

_T = {
    "or": {"ta": " அல்லது ", "en": " or "},
    "have": {"ta": "உள்ளது", "en": "have"},
    "missing": {"ta": "கொண்டு வர வேண்டும்", "en": "to bring"},
    "action": {"ta": "அலுவலகத்தில்", "en": "at the office"},
    "confirm": {
        "ta": "இந்த விதி இன்னும் அரசு ஆணையுடன் சரிபார்க்கப்படவில்லை. விண்ணப்பிக்கும் முன் அலுவலகத்தில் உறுதி செய்யுங்கள்.",
        "en": "This rule is not yet checked against the government order. Confirm at the office before you apply.",
    },
    "bring": {"ta": "கொண்டு செல்ல வேண்டியவை: {items}.", "en": "Bring: {items}."},
    "where": {"ta": "எங்கே: {place}", "en": "Where: {place}"},
    "later": {
        "ta": "{years} வருடத்தில், {age} வயதில்: {names}.",
        "en": "In {years} years, at {age}: {names}.",
    },
    "later_one": {
        "ta": "அடுத்த வருடம், {age} வயதில்: {names}.",
        "en": "Next year, at {age}: {names}.",
    },
    "later_lead": {
        "ta": "மற்ற எதுவும் மாறாவிட்டால், பின்னால் கிடைக்கக்கூடியவை:",
        "en": "If nothing else changes, you may also get later:",
    },
}


class NotEligible(ValueError):
    """An application sheet was asked for a scheme the person is not eligible for."""


def _t(key: str, lang: str, **values: Any) -> str:
    text = _T[key].get(lang) or _T[key]["en"]
    return text.format(**values) if values else text


def _decisive_attrs(tree: Mapping[str, Any]) -> list[str]:
    """The attributes of the clauses that made a scheme eligible, in rule order.

    Follows only children that agree with their parent, so the unused alternatives of an
    ANY are left out — the officer checks what made it true, not what might have.
    """
    if tree["kind"] == "predicate":
        return [tree["attr"]]
    children = tree.get("children", [])
    if tree["kind"] != "not":
        children = [c for c in children if c["verdict"] == tree["verdict"]]
    seen: list[str] = []
    for child in children:
        for attr in _decisive_attrs(child):
            if attr not in seen:
                seen.append(attr)
    return seen


def application_pack(scheme: Scheme, profile: Mapping[str, Any], spec: AttributeSpec,
                     documents: DocumentVocabulary, book: QuestionBook, lang: str, *,
                     active: SchemeKB, held: Iterable[str] = (),
                     person: str = "") -> dict[str, Any]:
    """Everything one printed page needs. Raises :class:`NotEligible` unless the rule
    engine says this person is eligible for this scheme."""
    lang = "ta" if lang == "ta" else "en"
    trace = scheme.decide(profile)
    if trace.verdict is not Verdict.TRUE:
        raise NotEligible(f"{scheme.id}: the rules say {trace.verdict.value}, not eligible")

    plan = checklist(documents, active, [scheme.id], held, state=profile.get("state"))
    items = []
    for item in plan["schemes"][0]["items"] if plan["schemes"] else []:
        labels = [(t.get("label_ta") if lang == "ta" else None) or t["label"]
                  for t in item["types"]]
        # How to get a missing paper, in the person's state (kb/spec/document_guides.yaml).
        guide = next((g for t in item["types"]
                      if (g := documents.guide(t["id"], profile.get("state"))) is not None),
                     None) if item["status"] == "missing" else None
        items.append({
            "label": _t("or", lang).join(labels) if labels else item["requirement"],
            "requirement": item["requirement"],
            "status": item["status"],
            "status_text": _t(item["status"], lang),
            "guide": guide,
        })

    tree = trace_to_dict(trace, spec)
    facts = []
    for attr in _decisive_attrs(tree):
        if attr in spec and spec[attr].elicitable and profile.get(attr) is not None:
            facts.append({"attr": attr, "label": book.label(attr, lang),
                          "answer": answer_text(book, spec, attr, profile[attr], lang)})

    name = spoken_name(scheme, lang)
    what = spoken_what(scheme, lang) or (scheme.summary if lang == "en" else "")
    where = scheme.plain_text(lang, "where")
    missing = [i["label"] for i in items if i["status"] == "missing"]
    said = [name + ".", what]
    if missing:
        said.append(_t("bring", lang, items=", ".join(missing)))
    if where:
        said.append(_t("where", lang, place=where))
    if not scheme.is_verified:
        said.append(_t("confirm", lang))

    return {
        "id": scheme.id,
        "lang": lang,
        "person": person,
        "name": name,
        "official_name": scheme.name,
        "official_name_ta": scheme.name_ta,
        "what": what,
        "who": scheme.plain_text(lang, "who"),
        "where": where,
        "authority": scheme.authority,
        "value_text": value_text(scheme),
        "apply_url": scheme.apply_url,
        "verified": scheme.is_verified,
        "documents": items,
        "n_missing": len(missing),
        "facts": facts,
        "sources": [{"title": s.title, "url": s.url, "retrieved": s.retrieved.isoformat()
                     if hasattr(s.retrieved, "isoformat") else str(s.retrieved)}
                    for s in scheme.sources],
        "caveat": "" if scheme.is_verified else _t("confirm", lang),
        "spoken": " ".join(part for part in said if part),
    }


def share_text(pack: Mapping[str, Any]) -> str:
    """The sheet as a WhatsApp message: plain words and the checklist, nothing personal
    beyond what the person chose to put on it."""
    lines = [f"*{pack['name']}*"]
    if pack["what"]:
        lines.append(pack["what"])
    if pack["where"]:
        lines.append(_t("where", pack["lang"], place=pack["where"]))
    lines.append("")
    for item in pack["documents"]:
        mark = "✅" if item["status"] == "have" else "⬜" if item["status"] == "missing" else "➡️"
        lines.append(f"{mark} {item['label']}")
    if pack["caveat"]:
        lines += ["", pack["caveat"]]
    return "\n".join(lines)


# --------------------------------------------------------------------- forecast


def coming_up(active: SchemeKB, profile: Mapping[str, Any], spec: AttributeSpec, *,
              years: int = FORECAST_YEARS) -> list[dict[str, Any]]:
    """Schemes that open as the person gets older, everything else held the same.

    Each scheme is listed once, at the first year it opens. Nothing is said without an
    age: a forecast from a guessed age would be invented.
    """
    age = profile.get("age")
    if age is None:
        return []
    now = set(active.eligible_ids(profile))
    found: dict[str, dict[str, Any]] = {}
    for step, older in _older(profile, spec, years):
        for scheme_id in active.eligible_ids(older):
            if scheme_id not in now and scheme_id not in found:
                found[scheme_id] = {"id": scheme_id, "in_years": step,
                                    "at_age": int(float(age) + step)}
    return sorted(found.values(), key=lambda row: (row["in_years"], row["id"]))


def closing(active: SchemeKB, profile: Mapping[str, Any], spec: AttributeSpec, *,
            years: int = FORECAST_YEARS) -> list[dict[str, Any]]:
    """Schemes the person can get now that stop as they get older — apply before then.

    Each is listed once, at the first year it no longer holds; like :func:`coming_up`,
    nothing is said without an age.
    """
    age = profile.get("age")
    if age is None:
        return []
    now = set(active.eligible_ids(profile))
    gone: dict[str, dict[str, Any]] = {}
    for step, older in _older(profile, spec, years):
        for scheme_id in now - set(active.eligible_ids(older)):
            gone.setdefault(scheme_id, {"id": scheme_id, "in_years": step,
                                        "at_age": int(float(age) + step)})
    return sorted(gone.values(), key=lambda row: (row["in_years"], row["id"]))


def _older(profile: Mapping[str, Any], spec: AttributeSpec, years: int):
    """(step, profile) for each year ahead, with every fact that counts up by itself moved
    on. A count still at zero — registered this year, or never — is left alone; only age
    always moves."""
    base = {k: v for k, v in profile.items() if not spec[k].is_derived} if spec else dict(profile)
    growing = [name for name, attr in spec.attributes.items()
               if attr.grows_with_time and isinstance(base.get(name), (int, float))
               and (name == "age" or base[name] > 0)] if spec else ["age"]
    for step in range(1, years + 1):
        older = dict(base)
        for name in growing:
            ceiling = spec[name].domain[1] if spec[name].domain else float("inf")
            older[name] = min(float(base[name]) + step, ceiling)
        older.update(spec.derive(older))
        yield step, older


def coming_up_text(active: SchemeKB, later: list[dict[str, Any]], lang: str) -> str:
    """One spoken paragraph for :func:`coming_up`, grouped by year."""
    if not later:
        return ""
    by_year: dict[int, list[dict[str, Any]]] = {}
    for row in later:
        by_year.setdefault(row["in_years"], []).append(row)
    parts = [_t("later_lead", lang)]
    for step in sorted(by_year):
        rows = by_year[step]
        names = ", ".join(spoken_name(active[r["id"]], lang) for r in rows)
        key = "later_one" if step == 1 else "later"
        parts.append(_t(key, lang, years=step, age=rows[0]["at_age"], names=names))
    return " ".join(parts)
