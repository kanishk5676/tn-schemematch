"""JSON projections of the rule engine's objects, for the HTTP API and the browser.

Everything here is a pure function from a library object to a JSON-safe dict. No Flask, no
model, no I/O — so every shape can be tested offline and reused by anything.

Two projections exist because the library deliberately does not provide them:

- ``Trace`` has no ``to_dict``. It has ``explain()``, which returns indented text for a
  terminal. A browser needs the same information as a tree it can collapse and colour,
  which means a recursor carrying the per-node verdict and the observed value. This module
  owns that recursor, and it mirrors ``Trace.explain`` deliberately: what the page renders
  and what ``schemematch explain`` prints must not be able to drift.
- ``SchemeKB.match()`` returns a dict keyed by the ``Verdict`` *enum*. ``jsonify`` raises
  ``TypeError: keys must be str`` on it, so every response path goes through ``board()``.

Each predicate row carries the clause twice: ``machine`` is ``Predicate.describe()``, the
same string the terminal prints, and ``human`` is a sentence a citizen can read. Showing
both side by side is the audit story — a reviewer can check the sentence against the rule
without leaving the page.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .attributes import Attribute, AttributeSpec
from .benefits import value_text
from .kb import Scheme, SchemeKB, jurisdiction_name
from .rules import All, AnyOf, Const, Not, Predicate, Trace, Verdict

VERDICT_KEYS = ("eligible", "ineligible", "undetermined")

# Trace.explain uses this same label map (rules.py). Keep them in step.
_KINDS: dict[type, str] = {All: "all", AnyOf: "any", Not: "not"}
_LABELS: dict[type, str] = {All: "ALL of", AnyOf: "ANY of", Not: "NOT"}

# (plain, negated) — the negated column is used for clauses under a NOT, so an exclusion
# reads "must not be an income-tax payer" rather than making the reader invert it.
_PHRASES: dict[str, tuple[str, str]] = {
    "eq": ("must be", "must not be"),
    "ne": ("must not be", "must be"),
    "lt": ("must be under", "must be at least"),
    "lte": ("must be at most", "must be more than"),
    "gt": ("must be more than", "must be at most"),
    "gte": ("must be at least", "must be under"),
    "in": ("must be one of", "must not be one of"),
    "not_in": ("must not be one of", "must be one of"),
    "between": ("must be between", "must not be between"),
    "is_known": ("must be stated", "must not be stated"),
    "is_unknown": ("must not be stated", "must be stated"),
}

_UNITS: dict[str, str] = {
    "INR_per_year": "rupees a year",
    "INR_per_month": "rupees a month",
    "INR": "rupees",
    "acres": "acres",
    "years": "years",
    "percent": "percent",
    "persons": "people",
    "units_per_year": "units a year",
}


# ------------------------------------------------------------------ small helpers


def first_sentence(text: str) -> str:
    """The first sentence of an attribute description.

    Descriptions carry maintainer notes after sentence one — unit conversion factors, why
    a domain is drawn where it is. Those belong in the vocabulary file, not on screen in
    front of the person being interviewed.
    """
    if not text:
        return ""
    first = text.strip().splitlines()[0].strip()
    for stop in (". ", "; "):
        if stop in first:
            first = first.split(stop)[0]
            break
    return first.rstrip(".")


def question_text(attr: Attribute) -> str:
    """The citizen-facing question for an attribute."""
    first = first_sentence(attr.description) or attr.name.replace("_", " ")
    lead = first.lower()
    mark = "?" if lead.startswith(
        ("is ", "are ", "does ", "do ", "has ", "have ", "whether ")
    ) else "."
    return first + mark


def describe_attr(attr: Attribute) -> str:
    """The type/domain hint shown under a question."""
    if attr.type == "enum":
        return f"one of: {', '.join(str(v) for v in attr.domain or ())}"
    if attr.type == "bool":
        return "yes / no"
    if attr.type == "number":
        span = f", {attr.domain[0]}–{attr.domain[1]}" if attr.domain else ""
        return f"a number in {attr.unit or 'units'}{span}"
    return attr.type


# "Total agricultural land owned by the family, in acres" -> drop the unit tail. The unit
# is already rendered on the value, so keeping it makes clauses read "…, in acres must be
# more than 0 acres".
_UNIT_TAIL = re.compile(r",\s+in\s+[^,]+$", re.IGNORECASE)


def label_for(spec: AttributeSpec, attr: str) -> str:
    """A short human label for an attribute, for use inside a clause sentence.

    Falls back to the attribute name when the description's first sentence is too long to
    sit inside "X must be at least Y" — a clause has to stay readable as one line.
    """
    fallback = attr.replace("_", " ")
    if attr not in spec:
        return fallback
    label = _UNIT_TAIL.sub("", first_sentence(spec[attr].description)).strip()
    if not label or len(label) > 45:
        return fallback
    return label


def format_value(spec: AttributeSpec, attr: str, value: Any) -> str:
    """Render a canonical value the way a person would say it."""
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if attr in spec and spec[attr].type == "number" and isinstance(value, (int, float)):
        pretty = int(value) if float(value).is_integer() else round(float(value), 2)
        unit = _UNITS.get(spec[attr].unit or "", "")
        return f"{pretty:,} {unit}".strip() if abs(float(value)) >= 10000 else \
               f"{pretty} {unit}".strip()
    return str(value).replace("_", " ")


def _render_operand(spec: AttributeSpec, attr: str, value: Any,
                    *, max_items: int = 5) -> str:
    """Render a clause's right-hand side.

    Long enum lists are truncated here but never in ``machine`` — the prose line is for
    reading and the machine line is for auditing, and one of those needs every value.
    """
    if isinstance(value, (list, tuple)):
        items = [format_value(spec, attr, v) for v in value]
        if len(items) > max_items:
            shown = ", ".join(items[:max_items])
            return f"{shown} or {len(items) - max_items} others"
        return " or ".join(items)
    return format_value(spec, attr, value)


def describe_clause(pred: Predicate, spec: AttributeSpec, *, negated: bool = False) -> str:
    """One rule clause as an English sentence."""
    label = label_for(spec, pred.attr)
    phrase = _PHRASES.get(pred.op, ("must satisfy", "must not satisfy"))[1 if negated else 0]
    if pred.op in {"is_known", "is_unknown"}:
        return f"{label} {phrase}"
    if pred.op == "between" and isinstance(pred.value, (list, tuple)) and len(pred.value) == 2:
        lo = format_value(spec, pred.attr, pred.value[0])
        hi = format_value(spec, pred.attr, pred.value[1])
        return f"{label} {phrase} {lo} and {hi}"
    return f"{label} {phrase} {_render_operand(spec, pred.attr, pred.value)}"


# ------------------------------------------------------------------ the trace recursor


def trace_to_dict(trace: Trace, spec: AttributeSpec, *, negated: bool = False) -> dict[str, Any]:
    """A rule evaluation as a JSON tree, one node per clause.

    Dispatch order is load-bearing. ``Const`` is a ``Node`` that is *not* in the label map
    — ``personas.py`` builds them through ``transform`` for ablations — so a naive
    ``_LABELS[type(node)]`` raises ``KeyError`` on a tree that is otherwise fine. The final
    ``else`` exists so an unrecognised node degrades to a visible row instead of a 500.

    ``negated`` is threaded through ``Not`` so a clause underneath one reads as an
    exclusion in its own right rather than making the reader invert it mentally.
    """
    node = trace.node
    verdict = trace.verdict.value

    if isinstance(node, Predicate):
        row: dict[str, Any] = {
            "kind": "predicate",
            "verdict": verdict,
            "attr": node.attr,
            "op": node.op,
            "label": label_for(spec, node.attr),
            "machine": node.describe(),
            "human": describe_clause(node, spec, negated=negated),
            "observed": trace.actual,
            "observed_text": format_value(spec, node.attr, trace.actual)
            if trace.actual is not None else None,
            "unit": spec[node.attr].unit if node.attr in spec else None,
            "note": node.note or None,
            "children": [],
        }
        if node.op not in {"is_known", "is_unknown"}:
            row["value"] = list(node.value) if isinstance(node.value, tuple) else node.value
        return row

    if isinstance(node, Const):
        return {
            "kind": "const",
            "verdict": verdict,
            "label": "clause disabled by ablation",
            "machine": f"const({verdict})",
            "human": "This clause was replaced by a constant for an ablation.",
            "children": [],
        }

    kind = _KINDS.get(type(node))
    if kind is not None:
        inner_negated = not negated if kind == "not" else negated
        children = [trace_to_dict(c, spec, negated=inner_negated) for c in trace.children]
        return {
            "kind": kind,
            "verdict": verdict,
            "label": _LABELS[type(node)],
            "n_children": len(children),
            "n_satisfied": sum(1 for c in children if c["verdict"] == "eligible"),
            "n_failed": sum(1 for c in children if c["verdict"] == "ineligible"),
            "n_open": sum(1 for c in children if c["verdict"] == "undetermined"),
            "children": children,
        }

    return {
        "kind": "unknown",
        "verdict": verdict,
        "label": type(node).__name__,
        "machine": type(node).__name__,
        "human": "",
        "children": [trace_to_dict(c, spec, negated=negated) for c in trace.children],
    }


# ------------------------------------------------------------------ board and schemes


def match_to_dict(buckets: Mapping[Verdict, list[str]]) -> dict[str, list[str]]:
    """``SchemeKB.match`` with string keys, so it can cross the wire."""
    return {verdict.value: list(buckets.get(verdict, [])) for verdict in Verdict}


def board(active: SchemeKB, profile: Mapping[str, Any]) -> dict[str, Any]:
    """The live scoreboard: which schemes are settled, and how."""
    buckets = match_to_dict(active.match(profile))
    return {
        "counts": {key: len(buckets[key]) for key in VERDICT_KEYS},
        **buckets,
        "total": len(active),
    }


def scheme_summary(scheme: Scheme) -> dict[str, Any]:
    """Card fields — everything the browser needs without the rule tree."""
    return {
        "id": scheme.id,
        "name": scheme.name,
        "name_ta": scheme.name_ta,
        "level": scheme.level,
        "jurisdiction": scheme.jurisdiction,
        "jurisdiction_name": jurisdiction_name(scheme.jurisdiction) if scheme.jurisdiction else "",
        "authority": scheme.authority,
        "sectors": list(scheme.sectors),
        "benefit_type": scheme.benefit_type,
        "summary": scheme.summary,
        "benefit_prose": scheme.benefit_prose,
        "apply_url": scheme.apply_url,
        "status": scheme.status,
        "is_verified": scheme.is_verified,
        "n_attributes": len(scheme.attributes),
        "name_ml": scheme.name_ml,
        "value": scheme.value.to_dict() if scheme.value else None,
        "value_text": value_text(scheme),
        "cover": scheme.cover,
        "cannot_combine_with": [other for other, _ in scheme.cannot_combine],
    }


def scheme_detail(scheme: Scheme, spec: AttributeSpec,
                  profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """A scheme with its rule tree, evaluated against ``profile`` (``{}`` if omitted).

    Against an empty profile every node comes back ``undetermined``, which still shows the
    rule's *structure* — so the schemes browser is useful before an interview starts, and
    lights up once there is one.
    """
    trace = scheme.decide(profile or {})
    detail = scheme.to_dict()
    detail.update({
        "verdict": trace.verdict.value,
        "rule_tree": trace_to_dict(trace, spec),
        "documents": list(scheme.documents),
        "n_attributes": len(scheme.attributes),
        "attributes": sorted(scheme.attributes),
    })
    return detail


def near_misses(active: SchemeKB, profile: Mapping[str, Any], spec: AttributeSpec,
                *, limit: int = 8) -> list[dict[str, Any]]:
    """Schemes ruled out by exactly one clause.

    The most citizen-useful thing on the results page: not "no", but "no, and here is the
    single condition standing between you and it".
    """
    out: list[dict[str, Any]] = []
    for scheme_id in active.match(profile)[Verdict.FALSE]:
        scheme = active[scheme_id]
        failing = scheme.decide(profile).failing_predicates()
        if len(failing) != 1:
            continue
        pred = failing[0]
        observed = profile.get(pred.attr)
        out.append({
            "id": scheme.id,
            "name": scheme.name,
            "name_ta": scheme.name_ta,
            "benefit_prose": scheme.benefit_prose,
            "value_text": value_text(scheme),
            "apply_url": scheme.apply_url,
            "missing": {
                "attr": pred.attr,
                "machine": pred.describe(),
                "human": describe_clause(pred, spec),
                "label": label_for(spec, pred.attr),
                "observed": observed,
                "observed_text": format_value(spec, pred.attr, observed),
                "note": pred.note or None,
            },
        })
    return out[:limit]


# ------------------------------------------------------------------ forms and profile


def attribute_form(spec: AttributeSpec, name: str) -> dict[str, Any]:
    """An attribute as an HTML control contract.

    The frontend picks a widget from ``control`` alone and never needs a per-attribute
    switch. Enums split at six options because chips stop being scannable past that.
    """
    attr = spec[name]
    if attr.type == "bool":
        control = "buttons"
    elif attr.type == "enum":
        control = "chips" if len(attr.domain or ()) <= 6 else "select"
    elif attr.type == "number":
        control = "number"
    else:
        control = "text"

    options = [{"value": v, "label": str(v).replace("_", " ")} for v in (attr.domain or ())] \
        if attr.type == "enum" else []

    return {
        "name": name,
        "type": attr.type,
        "control": control,
        "question": question_text(attr),
        "hint": describe_attr(attr),
        "options": options,
        "unit": attr.unit,
        "unit_text": _UNITS.get(attr.unit or "", attr.unit or ""),
        "min": attr.domain[0] if attr.type == "number" and attr.domain else None,
        "max": attr.domain[1] if attr.type == "number" and attr.domain else None,
        "sensitivity": attr.sensitivity,
        "elicitable": attr.elicitable,
        "derived": attr.is_derived,
    }


def profile_rows(spec: AttributeSpec, profile: Mapping[str, Any],
                 sources: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """The collected profile as display rows, derived attributes marked as such."""
    sources = sources or {}
    rows = []
    for name in sorted(profile):
        if name not in spec:
            continue
        rows.append({
            "attr": name,
            "label": label_for(spec, name),
            "value": profile[name],
            "display": format_value(spec, name, profile[name]),
            "derived": spec[name].is_derived,
            "source": sources.get(name, "derived" if spec[name].is_derived else "unknown"),
        })
    return rows


def filter_cards(cards: list[dict[str, Any]], *, level: str | None = None,
                 sector: str | None = None, query: str | None = None) -> list[dict[str, Any]]:
    """The schemes browser's filter, shared with the assistant's ``search_schemes`` tool.

    Every word of the query must appear somewhere in the card (English or Tamil), so
    "fisher relief" narrows rather than widens.
    """
    if level:
        cards = [c for c in cards if c["level"] == level]
    if sector:
        cards = [c for c in cards if sector in c["sectors"]]
    words = [w for w in (query or "").casefold().split() if w]
    if words:
        cards = [c for c in cards
                 if all(w in json.dumps(c, ensure_ascii=False).casefold() for w in words)]
    return cards


def grounding_lines(trace: Trace, spec: AttributeSpec) -> list[str]:
    """The satisfied clauses of a decision, as sentences.

    This is the entire evidence a model is given when it phrases an explanation — the
    explain endpoint and the assistant's ``explain_scheme`` tool both use it — so a
    condition the person does not meet can never reach the prompt.
    """
    lines: list[str] = []
    for node in _walk(trace):
        if not isinstance(node.node, Predicate) or node.verdict is not Verdict.TRUE:
            continue
        sentence = describe_clause(node.node, spec)
        if node.actual is not None:
            sentence += f" — you said {format_value(spec, node.node.attr, node.actual)}"
        lines.append(sentence)
    return lines


def _walk(trace: Trace):
    yield trace
    for child in trace.children:
        yield from _walk(child)


def decisive_clauses(tree: Mapping[str, Any], *, said: str = "you said") -> list[str]:
    """The clauses that decided a verdict, as sentences, from a ``trace_to_dict`` tree.

    Only children that agree with their parent's verdict are followed: for an eligible
    scheme, the alternatives of an ANY that were not needed are left out; for an
    ineligible one, only the clauses that actually failed. Under a NOT the child is always
    followed, and its sentence is already phrased as an exclusion ("must not be"), so the
    list reads correctly without the reader inverting anything.
    """
    if tree["kind"] == "predicate":
        line = tree["human"]
        if tree.get("observed_text"):
            line += f" — {said} {tree['observed_text']}" if said else f" ({tree['observed_text']})"
        return [line]
    children = tree.get("children", [])
    if tree["kind"] != "not":
        children = [c for c in children if c["verdict"] == tree["verdict"]]
    return [line for child in children for line in decisive_clauses(child, said=said)]
