"""The JSON projections that cross the wire to the browser.

These exist to catch the two things that only fail at serialization time — a tuple, a
``date``, or a ``Verdict`` enum reaching ``jsonify`` — and the one structural trap in the
trace recursor, which is that ``Const`` is a node the label map does not contain.
"""

import json

import pytest

from tn_schemematch.rules import All, Const, Predicate, Verdict, evaluate, transform
from tn_schemematch.serialize import (
    VERDICT_KEYS,
    attribute_form,
    board,
    describe_clause,
    label_for,
    match_to_dict,
    near_misses,
    profile_rows,
    question_text,
    scheme_detail,
    trace_to_dict,
)

SATURATED = {
    "age": 45.0, "gender": "female", "state": "TN", "occupation": "farmer",
    "land_owned_acres": 2.0, "annual_family_income": 60000.0,
    "marital_status": "widowed", "residence_type": "rural",
}


def test_trace_to_dict_is_json_serializable_for_every_scheme(kb, spec):
    """Every scheme, empty and populated. This is the check that catches tuples and dates."""
    for scheme in kb.active():
        for profile in ({}, SATURATED):
            payload = trace_to_dict(scheme.decide(profile), spec)
            json.dumps(payload)  # raises on anything non-JSON


def test_trace_to_dict_preserves_every_node_in_the_ast(kb, spec):
    """A recursor that silently drops Not's child would still look fine by eye."""
    def count(node):
        return 1 + sum(count(c) for c in node["children"])

    for scheme in kb.active():
        payload = trace_to_dict(scheme.decide(SATURATED), spec)
        assert count(payload) == sum(1 for _ in scheme.eligibility.walk())


def test_trace_verdicts_agree_with_explain(kb, spec):
    """The page and `schemematch explain` must not be able to disagree."""
    trace = kb["pm-kisan"].decide(SATURATED)
    payload = trace_to_dict(trace, spec)
    text = trace.explain()
    assert payload["verdict"] == trace.verdict.value
    assert f"[{payload['verdict']}]" in text.splitlines()[0]


def test_trace_to_dict_handles_const_nodes(spec):
    """Const is a Node that is not in the label map; a naive dispatch raises KeyError."""
    rule = All((Predicate("age", "gte", 18.0), Const(Verdict.TRUE)))
    payload = trace_to_dict(evaluate(rule, {"age": 30.0}), spec)
    kinds = [c["kind"] for c in payload["children"]]
    assert "const" in kinds


def test_trace_to_dict_survives_an_ablated_rule(kb, spec):
    """Ablations replace whole clauses with constants, the way personas.py does."""
    ablated = transform(kb["pm-kisan"].eligibility,
                        lambda n: Const(Verdict.TRUE) if isinstance(n, Predicate) else n)
    json.dumps(trace_to_dict(evaluate(ablated, {}), spec))


def test_negation_flips_the_clause_wording(kb, spec):
    """A clause under NOT should read as an exclusion, not make the reader invert it."""
    pred = Predicate("filed_income_tax", "eq", True)
    plain = describe_clause(pred, spec)
    negated = describe_clause(pred, spec, negated=True)
    assert plain != negated
    assert "must not be" in negated


def test_match_to_dict_uses_string_keys(kb):
    """jsonify raises TypeError on the Verdict-keyed dict SchemeKB.match returns."""
    payload = match_to_dict(kb.active().match(SATURATED))
    assert set(payload) == set(VERDICT_KEYS)
    json.dumps(payload)


def test_board_counts_every_active_scheme(kb):
    data = board(kb.active(), SATURATED)
    assert sum(data["counts"].values()) == data["total"] == len(kb.active())


def test_attribute_form_covers_every_elicitable_attribute(spec):
    for name in spec.elicitable_names():
        form = attribute_form(spec, name)
        assert form["control"] in {"buttons", "chips", "select", "number", "text"}
        assert form["question"]
        if form["type"] == "enum":
            assert form["options"], f"{name} is an enum with no options"
        if form["type"] == "number":
            assert form["min"] is not None and form["max"] is not None


def test_near_misses_have_exactly_one_failing_condition(kb, spec):
    for miss in near_misses(kb.active(), SATURATED, spec):
        scheme = kb[miss["id"]]
        assert len(scheme.decide(SATURATED).failing_predicates()) == 1
        assert miss["missing"]["human"]


def test_clause_labels_stay_short_enough_to_read(spec):
    """Long descriptions fall back to the attribute name, or clauses become unreadable."""
    for name in spec.elicitable_names():
        assert len(label_for(spec, name)) <= 45


def test_question_text_never_leaks_maintainer_notes(spec):
    """Descriptions carry conversion factors after sentence one; citizens must not see them."""
    assert "Normalizer converts" not in question_text(spec["land_owned_acres"])
    assert question_text(spec["age"]).endswith((".", "?"))


def test_profile_rows_mark_derived_attributes(spec):
    profile = dict(SATURATED)
    profile.update(spec.derive(profile))
    rows = {r["attr"]: r for r in profile_rows(spec, profile)}
    assert rows["is_widow"]["derived"] is True
    assert rows["age"]["derived"] is False


def test_scheme_detail_without_a_profile_is_all_undetermined(kb, spec):
    """The schemes browser shows rule structure before an interview exists."""
    detail = scheme_detail(kb["pm-kisan"], spec)
    assert detail["verdict"] == "undetermined"
    assert detail["rule_tree"]["children"]
    json.dumps(detail)
