"""Evaluation metrics.

Everything here is exact and computed against a deterministic gold set — there is no
model-graded scoring anywhere in the pipeline. That is a deliberate constraint: the
claim we want to make is about eligibility decisions, and a judge model that shares the
system's blind spots about Tamil Nadu land ceilings cannot support that claim.

The metric that carries the paper is :func:`false_positive_rate`. It is reported
separately from F1 rather than folded into it, because the two errors are not
interchangeable. A false negative means a citizen does not hear about a benefit they
could have claimed — bad, and the status quo already does this. A false positive means
they are told they qualify, take a day off work, travel to a district office, and are
turned away. F1 averages those together and hides exactly the thing we care about.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "SetScores",
    "set_scores",
    "false_positive_rate",
    "ElicitationScores",
    "elicitation_scores",
    "retrieval_vs_matching",
    "aggregate",
    "paired_delta",
    "PairedDelta",
]


# --------------------------------------------------------------- set-level scores


@dataclass
class SetScores:
    """Precision / recall / F1 / exact match for one returned scheme set."""

    precision: float
    recall: float
    f1: float
    exact_match: bool
    n_returned: int
    n_gold: int
    false_positives: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "exact_match": self.exact_match,
            "n_returned": self.n_returned,
            "n_gold": self.n_gold,
            "false_positives": self.false_positives,
            "false_negatives": self.false_negatives,
        }


def set_scores(returned: Iterable[str], gold: Iterable[str]) -> SetScores:
    """Score a returned scheme set against the gold eligible set.

    Convention for empty sets: if the gold set is empty and the system returns nothing,
    that is a correct and useful answer ("nothing here fits you"), scored 1.0 across the
    board. Scoring it 0.0 — the naive division-by-zero fallback — would punish exactly
    the honest behaviour we are trying to encourage.
    """
    returned_set = set(returned)
    gold_set = set(gold)
    true_positives = returned_set & gold_set

    if not returned_set and not gold_set:
        return SetScores(1.0, 1.0, 1.0, True, 0, 0)

    precision = len(true_positives) / len(returned_set) if returned_set else 0.0
    recall = len(true_positives) / len(gold_set) if gold_set else (1.0 if not returned_set else 0.0)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return SetScores(
        precision=precision,
        recall=recall,
        f1=f1,
        exact_match=returned_set == gold_set,
        n_returned=len(returned_set),
        n_gold=len(gold_set),
        false_positives=sorted(returned_set - gold_set),
        false_negatives=sorted(gold_set - returned_set),
    )


def false_positive_rate(returned: Iterable[str], gold: Iterable[str]) -> float | None:
    """Fraction of returned schemes the citizen does not actually qualify for.

    Returns ``None`` when nothing was returned: there is no rate to speak of, and
    averaging a 0.0 in that case would let a system that answers "no schemes" to
    everything post a perfect false-positive score. Callers must drop the ``None``s
    rather than coerce them — :func:`aggregate` does.
    """
    returned_set = set(returned)
    if not returned_set:
        return None
    return len(returned_set - set(gold)) / len(returned_set)


def harmful_recommendation_rate(
    returned: Iterable[str], gold: Iterable[str], deprecated_ids: Iterable[str]
) -> float | None:
    """False-positive rate restricted to discontinued schemes.

    Recommending a dead scheme is the most costly single error in the benchmark: the
    citizen cannot apply at all, no matter how well they match the published criteria.
    """
    returned_set = set(returned)
    if not returned_set:
        return None
    dead = returned_set & set(deprecated_ids) - set(gold)
    return len(dead) / len(returned_set)


# ------------------------------------------------------------ elicitation scores


@dataclass
class ElicitationScores:
    """How well the system chose its questions."""

    question_precision: float | None   # asked ∩ necessary / asked
    question_overhead: float | None    # asked / oracle minimum
    sufficient: bool                   # did it learn enough to settle every settleable scheme
    n_asked: int
    n_necessary: int
    n_oracle: int
    wasted_questions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_precision": self.question_precision,
            "question_overhead": self.question_overhead,
            "sufficient": self.sufficient,
            "n_asked": self.n_asked,
            "n_necessary": self.n_necessary,
            "n_oracle": self.n_oracle,
            "wasted_questions": self.wasted_questions,
        }


def elicitation_scores(
    asked: Sequence[str],
    necessary: Iterable[str],
    oracle_sequence: Sequence[str],
    *,
    settled_after: Iterable[str] | None = None,
    settleable: Iterable[str] | None = None,
) -> ElicitationScores:
    """Score an elicitation trajectory.

    ``asked`` is the sequence of attributes the system requested. ``necessary`` is the
    set whose answers could still change some verdict at the start of the conversation
    (:func:`~tn_schemematch.elicitation.necessary_questions`). ``oracle_sequence`` is
    the greedy shortest sufficient sequence.

    Note that ``necessary`` is computed at the *start*. An attribute asked late may have
    become irrelevant in the meantime, so question_precision as defined here is generous
    to the system; a stricter turn-by-turn variant is worth reporting alongside it if
    systems start gaming the lenient one.
    """
    asked_list = list(asked)
    asked_set = set(asked_list)
    necessary_set = set(necessary)

    precision = len(asked_set & necessary_set) / len(asked_set) if asked_set else None
    overhead = (len(asked_list) / len(oracle_sequence)) if oracle_sequence else None
    if not oracle_sequence and not asked_list:
        overhead = 1.0  # nothing needed asking, nothing was asked

    if settled_after is not None and settleable is not None:
        sufficient = set(settleable) <= set(settled_after)
    else:
        sufficient = necessary_set <= asked_set if necessary_set else True

    return ElicitationScores(
        question_precision=precision,
        question_overhead=overhead,
        sufficient=sufficient,
        n_asked=len(asked_list),
        n_necessary=len(necessary_set),
        n_oracle=len(oracle_sequence),
        wasted_questions=sorted(asked_set - necessary_set),
    )


# ------------------------------------------------------- retrieval vs. matching


def retrieval_vs_matching(
    retrieved: Iterable[str], returned: Iterable[str], gold: Iterable[str]
) -> dict[str, float | None]:
    """The RQ1 gap: schemes *surfaced* versus schemes *decided correctly*.

    ``retrieved`` is the candidate set the system considered (for a RAG system, the
    top-k passages' schemes; for the grounding pipeline, every scheme it evaluated).
    If retrieval recall is high while matching recall is low, the system found the right
    schemes and then reasoned about them wrongly — which is the claim RQ1 makes.
    """
    gold_set = set(gold)
    if not gold_set:
        return {"retrieval_recall": None, "matching_recall": None, "gap": None}
    retrieval_recall = len(set(retrieved) & gold_set) / len(gold_set)
    matching_recall = len(set(returned) & gold_set) / len(gold_set)
    return {
        "retrieval_recall": retrieval_recall,
        "matching_recall": matching_recall,
        "gap": retrieval_recall - matching_recall,
    }


# -------------------------------------------------------------------- aggregation


def aggregate(values: Iterable[float | bool | None]) -> dict[str, float | int | None]:
    """Mean and spread over per-persona values, dropping ``None``s explicitly.

    ``n_scored`` versus ``n_skipped`` is reported so a reader can tell the difference
    between "the system did well" and "the system rarely answered".
    """
    collected = [float(v) for v in values if v is not None]
    skipped = sum(1 for v in values if v is None)
    if not collected:
        return {"mean": None, "sd": None, "n_scored": 0, "n_skipped": skipped}
    mu = mean(collected)
    if len(collected) > 1:
        variance = sum((x - mu) ** 2 for x in collected) / (len(collected) - 1)
        sd = math.sqrt(variance)
    else:
        sd = 0.0
    return {"mean": mu, "sd": sd, "n_scored": len(collected), "n_skipped": skipped}


# ------------------------------------------------------------- RQ2: paired delta


@dataclass
class PairedDelta:
    """Code-mixed minus English on one metric, with a paired bootstrap interval."""

    metric: str
    mean_code_mixed: float
    mean_english: float
    delta: float
    ci_low: float
    ci_high: float
    n_pairs: int
    p_two_sided: float

    @property
    def significant(self) -> bool:
        """Whether the interval excludes zero. Not a substitute for reporting the interval."""
        return (self.ci_low > 0) or (self.ci_high < 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "mean_code_mixed": self.mean_code_mixed,
            "mean_english": self.mean_english,
            "delta": self.delta,
            "ci95": [self.ci_low, self.ci_high],
            "n_pairs": self.n_pairs,
            "p_two_sided": self.p_two_sided,
            "significant": self.significant,
        }


def paired_delta(
    metric: str,
    code_mixed: Mapping[str, float | None],
    english: Mapping[str, float | None],
    *,
    n_boot: int = 10000,
    seed: int = 20260815,
) -> PairedDelta | None:
    """Bootstrap the code-mixed vs English difference over shared personas.

    Pairing by persona id is what makes this the right test: the two conditions describe
    the same person against the same rules, so persona difficulty cancels and what
    remains is the effect of the query language. Personas scored in only one condition
    are dropped rather than imputed — an unanswered query is a result about the system,
    but it is not a *paired* observation and must not be smuggled into the delta.

    The permutation p-value flips the sign of each pair's difference at random, which is
    the exact null for a paired design: under it, condition labels are exchangeable
    within a persona.
    """
    shared = [
        pid for pid in code_mixed
        if pid in english and code_mixed[pid] is not None and english[pid] is not None
    ]
    if len(shared) < 2:
        return None

    diffs = [float(code_mixed[p]) - float(english[p]) for p in shared]  # type: ignore[arg-type]
    observed = mean(diffs)
    rng = random.Random(seed)

    boots: list[float] = []
    n = len(diffs)
    for _ in range(n_boot):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        boots.append(mean(sample))
    boots.sort()
    ci_low = boots[int(0.025 * n_boot)]
    ci_high = boots[min(int(0.975 * n_boot), n_boot - 1)]

    extreme = 0
    for _ in range(n_boot):
        flipped = mean([d if rng.random() < 0.5 else -d for d in diffs])
        if abs(flipped) >= abs(observed):
            extreme += 1
    p_value = (extreme + 1) / (n_boot + 1)

    return PairedDelta(
        metric=metric,
        mean_code_mixed=mean(float(code_mixed[p]) for p in shared),  # type: ignore[arg-type]
        mean_english=mean(float(english[p]) for p in shared),        # type: ignore[arg-type]
        delta=observed,
        ci_low=ci_low,
        ci_high=ci_high,
        n_pairs=len(shared),
        p_two_sided=p_value,
    )
