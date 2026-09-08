"""Experiment runner: execute systems over personas and score the results.

The unit of work is (system, persona, condition). Every run is written out in full —
including the transcript and the final profile — because the error analysis in Week 5 is
where the paper's contribution actually lives, and post-hoc "why did it say that?"
questions cannot be answered from aggregate scores.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from ..kb import SchemeKB
from ..personas import PersonaSet
from ..systems.base import MatchResult, MatchSystem
from .metrics import (
    PairedDelta,
    aggregate,
    elicitation_scores,
    false_positive_rate,
    harmful_recommendation_rate,
    paired_delta,
    retrieval_vs_matching,
    set_scores,
)

CONDITIONS = ("code_mixed", "english")


# ------------------------------------------------------------------------ running


def run_experiment(
    systems: Sequence[MatchSystem],
    personas: PersonaSet,
    kb: SchemeKB,
    *,
    conditions: Sequence[str] = CONDITIONS,
    progress: bool = False,
) -> list[MatchResult]:
    """Run every (system, persona, condition) combination."""
    results: list[MatchResult] = []
    total = len(systems) * len(personas) * len(conditions)
    done = 0
    for system in systems:
        for persona in personas:
            for condition in conditions:
                results.append(system.run(persona, condition, kb))
                done += 1
                if progress:
                    print(f"  [{done}/{total}] {system.name} / {persona.id} / {condition}",
                          flush=True)
    return results


# ------------------------------------------------------------------------ scoring


@dataclass
class PersonaScore:
    """All metrics for one (system, persona, condition)."""

    system: str
    persona_id: str
    condition: str
    precision: float
    recall: float
    f1: float
    exact_match: bool
    fpr: float | None
    harmful_fpr: float | None
    retrieval_recall: float | None
    matching_recall: float | None
    retrieval_gap: float | None
    question_precision: float | None
    question_overhead: float | None        # asked / minimal set needed to give the right answer
    question_overhead_exhaustive: float | None  # asked / questions needed to settle every scheme
    elicitation_sufficient: bool
    n_questions: int
    false_positives: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def score_results(
    results: Iterable[MatchResult], personas: PersonaSet, kb: SchemeKB
) -> list[PersonaScore]:
    """Score every run against ground truth."""
    active = kb.active()
    deprecated = kb.deprecated_ids()
    # Materialise first: `results` is an Iterable, and we need to know which personas
    # were actually run before deciding whose ground truth to compute.
    results = list(results)
    # One elicitation ground costs a full oracle question sequence — O(questions x
    # schemes x attributes). Computing it for all 247 personas in order to score two
    # results was ~7s a call, and it scales with the KB, so it gets worse exactly as
    # the KB grows.
    wanted = {r.persona_id for r in results}
    grounds = {p.id: p.elicitation_ground(kb) for p in personas if p.id in wanted}
    gold = personas.gold(kb)

    scored: list[PersonaScore] = []
    for result in results:
        persona = personas[result.persona_id]
        gold_ids = gold[result.persona_id]
        ground = grounds[result.persona_id]

        sets = set_scores(result.returned, gold_ids)
        gap = retrieval_vs_matching(result.retrieved, result.returned, gold_ids)
        # Overhead is scored against the minimal set that yields the right answer, not
        # against the exhaustive interview — see minimal_confirming_questions() for why.
        elicit = elicitation_scores(
            result.questions_asked,
            ground.necessary,
            ground.minimal_confirming,
            settled_after=_settled(result, active),
            settleable=ground.undetermined_at_start + ground.resolvable_without_asking,
        )
        exhaustive = elicitation_scores(
            result.questions_asked, ground.necessary, ground.oracle_sequence
        )

        scored.append(
            PersonaScore(
                system=result.system,
                persona_id=result.persona_id,
                condition=result.condition,
                precision=sets.precision,
                recall=sets.recall,
                f1=sets.f1,
                exact_match=sets.exact_match,
                fpr=false_positive_rate(result.returned, gold_ids),
                harmful_fpr=harmful_recommendation_rate(result.returned, gold_ids, deprecated),
                retrieval_recall=gap["retrieval_recall"],
                matching_recall=gap["matching_recall"],
                retrieval_gap=gap["gap"],
                question_precision=elicit.question_precision,
                question_overhead=elicit.question_overhead,
                question_overhead_exhaustive=exhaustive.question_overhead,
                elicitation_sufficient=elicit.sufficient,
                n_questions=elicit.n_asked,
                false_positives=sets.false_positives,
                false_negatives=sets.false_negatives,
                error=result.error,
            )
        )
    return scored


def _settled(result: MatchResult, active: SchemeKB) -> list[str]:
    """Schemes the run's final profile actually settles (empty for systems without one)."""
    if not result.final_profile:
        return []
    buckets = active.match(result.final_profile)
    from ..rules import Verdict  # local import keeps the module import graph acyclic

    return sorted(buckets[Verdict.TRUE] + buckets[Verdict.FALSE])


# --------------------------------------------------------------------- reporting


_NUMERIC_METRICS = (
    "precision", "recall", "f1", "exact_match", "fpr", "harmful_fpr",
    "retrieval_recall", "matching_recall", "retrieval_gap",
    "question_precision", "question_overhead", "question_overhead_exhaustive", "n_questions",
)


def summarize(scores: Sequence[PersonaScore]) -> dict[str, Any]:
    """Aggregate by (system, condition)."""
    out: dict[str, Any] = {}
    keys = sorted({(s.system, s.condition) for s in scores})
    for system, condition in keys:
        subset = [s for s in scores if s.system == system and s.condition == condition]
        block: dict[str, Any] = {
            "n_runs": len(subset),
            "n_errors": sum(1 for s in subset if s.error),
        }
        for metric in _NUMERIC_METRICS:
            block[metric] = aggregate(getattr(s, metric) for s in subset)
        block["elicitation_sufficient_rate"] = aggregate(
            s.elicitation_sufficient for s in subset
        )
        out[f"{system}|{condition}"] = block
    return out


def rq2_report(
    scores: Sequence[PersonaScore],
    *,
    metrics: Sequence[str] = ("f1", "fpr", "exact_match", "recall", "retrieval_recall"),
    n_boot: int = 10000,
) -> dict[str, list[dict[str, Any]]]:
    """Per-system code-mixed vs English deltas — the RQ2 table.

    Reported per system rather than pooled: "code-mixing hurts" is not one finding but
    several, and a pipeline whose only multilingual component is an extraction step can
    fail very differently from an agent reasoning over retrieved English prose.
    """
    report: dict[str, list[dict[str, Any]]] = {}
    for system in sorted({s.system for s in scores}):
        rows: list[dict[str, Any]] = []
        for metric in metrics:
            code_mixed = {
                s.persona_id: _as_float(getattr(s, metric))
                for s in scores if s.system == system and s.condition == "code_mixed"
            }
            english = {
                s.persona_id: _as_float(getattr(s, metric))
                for s in scores if s.system == system and s.condition == "english"
            }
            delta: PairedDelta | None = paired_delta(
                metric, code_mixed, english, n_boot=n_boot
            )
            if delta is not None:
                rows.append(delta.to_dict())
        report[system] = rows
    return report


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    return float(value)


# ------------------------------------------------------------------- persistence


def save_run(
    directory: str | Path,
    results: Sequence[MatchResult],
    scores: Sequence[PersonaScore],
    *,
    metadata: dict[str, Any] | None = None,
) -> Path:
    """Write raw results, per-persona scores, and summaries to a timestamped folder."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    (directory / "results.jsonl").write_text(
        "\n".join(json.dumps(r.to_dict(), ensure_ascii=False) for r in results),
        encoding="utf-8",
    )
    (directory / "scores.jsonl").write_text(
        "\n".join(json.dumps(s.to_dict(), ensure_ascii=False) for s in scores),
        encoding="utf-8",
    )
    report = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "metadata": metadata or {},
        "summary": summarize(scores),
        "rq2_codemix_delta": rq2_report(scores),
    }
    (directory / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return directory
