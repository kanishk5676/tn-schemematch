"""Metric semantics — especially the edge cases that decide what a headline number means."""

import pytest

from tn_schemematch.eval.metrics import (
    aggregate,
    elicitation_scores,
    false_positive_rate,
    harmful_recommendation_rate,
    paired_delta,
    retrieval_vs_matching,
    set_scores,
)


# ------------------------------------------------------------------ set scoring


def test_perfect_match():
    scores = set_scores(["a", "b"], ["a", "b"])
    assert (scores.precision, scores.recall, scores.f1) == (1.0, 1.0, 1.0)
    assert scores.exact_match


def test_partial_match_splits_the_two_error_types():
    scores = set_scores(["a", "c"], ["a", "b"])
    assert scores.precision == 0.5
    assert scores.recall == 0.5
    assert scores.false_positives == ["c"]
    assert scores.false_negatives == ["b"]
    assert not scores.exact_match


def test_correctly_returning_nothing_scores_perfectly():
    """"Nothing here fits you" is a useful, correct answer and must not be punished."""
    scores = set_scores([], [])
    assert (scores.precision, scores.recall, scores.f1) == (1.0, 1.0, 1.0)
    assert scores.exact_match


def test_returning_nothing_when_something_was_due_scores_zero():
    scores = set_scores([], ["a"])
    assert scores.recall == 0.0
    assert scores.false_negatives == ["a"]


# ---------------------------------------------------------- false positive rate


def test_false_positive_rate_counts_only_returned_schemes():
    assert false_positive_rate(["a", "b", "c"], ["a"]) == pytest.approx(2 / 3)
    assert false_positive_rate(["a"], ["a", "b"]) == 0.0


def test_false_positive_rate_is_none_when_nothing_returned():
    """Abstaining is not a perfect score; it is no score. Otherwise silence wins the metric."""
    assert false_positive_rate([], ["a"]) is None


def test_aggregate_reports_skipped_separately():
    summary = aggregate([1.0, 0.0, None])
    assert summary["mean"] == 0.5
    assert summary["n_scored"] == 2
    assert summary["n_skipped"] == 1


def test_a_system_that_always_abstains_scores_no_fpr_at_all():
    values = [false_positive_rate([], ["a"]) for _ in range(10)]
    summary = aggregate(values)
    assert summary["mean"] is None
    assert summary["n_scored"] == 0
    assert summary["n_skipped"] == 10


def test_harmful_recommendation_rate_isolates_discontinued_schemes():
    rate = harmful_recommendation_rate(
        ["live-scheme", "dead-scheme"], ["live-scheme"], ["dead-scheme"]
    )
    assert rate == 0.5


# ------------------------------------------------------ retrieval vs. matching


def test_retrieval_vs_matching_gap():
    gap = retrieval_vs_matching(retrieved=["a", "b", "c"], returned=["a"], gold=["a", "b"])
    assert gap["retrieval_recall"] == 1.0
    assert gap["matching_recall"] == 0.5
    assert gap["gap"] == 0.5


def test_gap_is_none_without_a_gold_set():
    assert retrieval_vs_matching(["a"], ["a"], [])["gap"] is None


# ------------------------------------------------------------------ elicitation


def test_wasted_questions_are_named():
    scores = elicitation_scores(
        asked=["age", "religion"], necessary={"age", "gender"}, oracle_sequence=["age"]
    )
    assert scores.question_precision == 0.5
    assert scores.wasted_questions == ["religion"]
    assert scores.question_overhead == 2.0


def test_asking_nothing_when_nothing_was_needed_is_ideal():
    scores = elicitation_scores(asked=[], necessary=set(), oracle_sequence=[])
    assert scores.question_overhead == 1.0
    assert scores.sufficient


# ------------------------------------------------------------------- RQ2 delta


def test_paired_delta_detects_a_consistent_drop():
    english = {f"p{i}": 0.9 for i in range(20)}
    code_mixed = {f"p{i}": 0.6 for i in range(20)}
    delta = paired_delta("f1", code_mixed, english, n_boot=2000)
    assert delta is not None
    assert delta.delta == pytest.approx(-0.3)
    assert delta.significant
    assert delta.ci_high < 0


def test_paired_delta_finds_nothing_when_there_is_nothing():
    values = {f"p{i}": 0.5 for i in range(20)}
    delta = paired_delta("f1", values, dict(values), n_boot=2000)
    assert delta is not None
    assert delta.delta == 0.0
    assert not delta.significant
    assert delta.p_two_sided > 0.05


def test_paired_delta_drops_unpaired_personas():
    """A persona scored in only one condition is not a paired observation."""
    code_mixed = {"p1": 0.5, "p2": 0.5, "p3": None}
    english = {"p1": 1.0, "p2": 1.0, "p3": 1.0}
    delta = paired_delta("f1", code_mixed, english, n_boot=500)
    assert delta is not None
    assert delta.n_pairs == 2


def test_paired_delta_needs_at_least_two_pairs():
    assert paired_delta("f1", {"p1": 0.5}, {"p1": 1.0}) is None


def test_paired_delta_is_reproducible():
    code_mixed = {f"p{i}": i / 20 for i in range(20)}
    english = {f"p{i}": (i + 3) / 20 for i in range(20)}
    a = paired_delta("f1", code_mixed, english, n_boot=1000, seed=7)
    b = paired_delta("f1", code_mixed, english, n_boot=1000, seed=7)
    assert a.to_dict() == b.to_dict()
