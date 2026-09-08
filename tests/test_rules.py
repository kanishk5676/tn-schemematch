"""Rule parsing and three-valued evaluation."""

import pytest

from tn_schemematch.rules import (
    RuleError,
    Verdict,
    evaluate,
    numeric_boundaries,
    parse_rule,
    referenced_attributes,
)

T, F, U = Verdict.TRUE, Verdict.FALSE, Verdict.UNKNOWN


# ------------------------------------------------------------------ Kleene laws


@pytest.mark.parametrize(
    "a,b,expected",
    [(T, T, T), (T, F, F), (F, F, F), (T, U, U), (F, U, F), (U, U, U)],
)
def test_conjunction(a, b, expected):
    assert (a & b) is expected


@pytest.mark.parametrize(
    "a,b,expected",
    [(T, T, T), (T, F, T), (F, F, F), (T, U, T), (F, U, U), (U, U, U)],
)
def test_disjunction(a, b, expected):
    assert (a | b) is expected


@pytest.mark.parametrize("a,expected", [(T, F), (F, T), (U, U)])
def test_negation(a, expected):
    assert (~a) is expected


def test_one_false_settles_a_conjunction_regardless_of_unknowns(spec):
    """The property that makes partial answers usable: a single disqualifier is enough."""
    rule = parse_rule(
        {"all": [
            {"attr": "gender", "op": "eq", "value": "female"},
            {"attr": "age", "op": "gte", "value": 21},
            {"attr": "annual_family_income", "op": "lte", "value": 250000},
        ]},
        spec,
    )
    # Male: ineligible immediately, without knowing age or income.
    assert evaluate(rule, {"gender": "male"}).verdict is F
    # Female with nothing else known: still an open question.
    assert evaluate(rule, {"gender": "female"}).verdict is U


# -------------------------------------------------------------------- boundaries


@pytest.mark.parametrize(
    "income,expected", [(249999, T), (250000, T), (250001, F)]
)
def test_lte_boundary_is_inclusive(spec, income, expected):
    rule = parse_rule({"attr": "annual_family_income", "op": "lte", "value": 250000}, spec)
    assert evaluate(rule, {"annual_family_income": income}).verdict is expected


@pytest.mark.parametrize("age,expected", [(29, F), (30, T), (59, T), (60, F)])
def test_between_is_inclusive_on_both_ends(spec, age, expected):
    rule = parse_rule({"attr": "age", "op": "between", "value": [30, 59]}, spec)
    assert evaluate(rule, {"age": age}).verdict is expected


# ------------------------------------------------------------- parser validation


def test_undeclared_attribute_rejected(spec):
    with pytest.raises(RuleError, match="undeclared attribute"):
        parse_rule({"attr": "vibes", "op": "eq", "value": 1}, spec)


def test_unknown_operator_rejected(spec):
    with pytest.raises(RuleError, match="unknown operator"):
        parse_rule({"attr": "age", "op": "approximately", "value": 30}, spec)


def test_ordering_operator_on_enum_rejected(spec):
    """`social_category > BC` is meaningless and must not silently compare strings."""
    with pytest.raises(RuleError, match="ordering operator"):
        parse_rule({"attr": "social_category", "op": "gt", "value": "BC"}, spec)


def test_enum_value_outside_domain_rejected(spec):
    with pytest.raises(RuleError):
        parse_rule({"attr": "gender", "op": "eq", "value": "nonbinary_unlisted"}, spec)


def test_inverted_between_rejected(spec):
    with pytest.raises(RuleError, match="inverted"):
        parse_rule({"attr": "age", "op": "between", "value": [60, 30]}, spec)


def test_empty_combinator_rejected(spec):
    with pytest.raises(RuleError, match="empty"):
        parse_rule({"all": []}, spec)


def test_rule_values_are_canonicalized_at_parse_time(spec):
    """A rule may be authored with surface forms; it is stored canonically."""
    rule = parse_rule({"attr": "social_category", "op": "in",
                       "value": ["scheduled caste", "ஆதிதிராவிடர்", "ST"]}, spec)
    assert set(rule.value) == {"SC", "ST"}
    assert evaluate(rule, {"social_category": "SC"}).verdict is T


# ------------------------------------------------------------------- exclusions


def test_not_block_expresses_an_exclusion(spec):
    rule = parse_rule({"not": {"attr": "is_income_tax_payer", "op": "eq", "value": True}}, spec)
    assert evaluate(rule, {"is_income_tax_payer": True}).verdict is F
    assert evaluate(rule, {"is_income_tax_payer": False}).verdict is T
    assert evaluate(rule, {}).verdict is U


def test_is_known_is_never_unknown(spec):
    rule = parse_rule({"attr": "age", "op": "is_known"}, spec)
    assert evaluate(rule, {}).verdict is F
    assert evaluate(rule, {"age": 30}).verdict is T


# ---------------------------------------------------------------------- analysis


def test_referenced_attributes_and_boundaries(spec):
    rule = parse_rule(
        {"all": [
            {"attr": "age", "op": "gte", "value": 21},
            {"attr": "age", "op": "lt", "value": 60},
            {"attr": "annual_family_income", "op": "lte", "value": 250000},
        ]},
        spec,
    )
    assert referenced_attributes(rule) == {"age", "annual_family_income"}
    assert numeric_boundaries(rule, "age") == [21.0, 60.0]
    assert numeric_boundaries(rule, "annual_family_income") == [250000.0]


def test_trace_explains_the_failing_clause(spec):
    rule = parse_rule(
        {"all": [
            {"attr": "state", "op": "eq", "value": "TN"},
            {"attr": "annual_family_income", "op": "lt", "value": 120000},
        ]},
        spec,
    )
    trace = evaluate(rule, {"state": "TN", "annual_family_income": 150000})
    assert trace.verdict is F
    failing = trace.failing_predicates()
    assert [p.attr for p in failing] == ["annual_family_income"]
    assert "annual_family_income" in trace.explain()


def test_trace_reports_what_is_still_unknown(spec):
    rule = parse_rule(
        {"all": [
            {"attr": "state", "op": "eq", "value": "TN"},
            {"attr": "is_destitute", "op": "eq", "value": True},
        ]},
        spec,
    )
    trace = evaluate(rule, {"state": "TN"})
    assert trace.verdict is U
    assert [p.attr for p in trace.unknown_predicates()] == ["is_destitute"]
