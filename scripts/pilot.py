#!/usr/bin/env python3
"""Pilot run: check the metrics discriminate, then (optionally) run real models.

    python scripts/pilot.py                                   # model-free reference suite
    python scripts/pilot.py --backend anthropic --model ...   # adds the model arms

The model-free pass runs six systems whose failure modes are known exactly, and asserts
that the metrics separate them. If those assertions fail, the metric suite is broken and a
paid run would only produce numbers that cannot be interpreted. Run this first, every time
the metrics change.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tn_schemematch import load_kb, validate_kb                        # noqa: E402
from tn_schemematch.eval.report import markdown_report                 # noqa: E402
from tn_schemematch.eval.runner import (                               # noqa: E402
    run_experiment,
    save_run,
    score_results,
    summarize,
)
from tn_schemematch.personas import load_personas, validate_personas   # noqa: E402
from tn_schemematch.systems.grounding import (                          # noqa: E402
    GroundingPipeline,
    OracleExtractionPipeline,
)
from tn_schemematch.systems.rag_baseline import DirectSystem, RAGBaseline  # noqa: E402
from tn_schemematch.systems.retrieval import BM25Retriever, OracleRetriever  # noqa: E402
from tn_schemematch.systems.synthetic import reference_suite           # noqa: E402

NOTES = [
    "`probe:*` rows are not models. They are reasoners with a known, named defect, "
    "included so a real model's numbers can be read against reference points rather "
    "than in the abstract.",
    "`ablation:no_elicitation` is the grounding pipeline forbidden to ask questions. "
    "Its gap from the full pipeline is what elicitation is worth.",
    "The FP-rate column shows `(scored/total)` whenever a system returned nothing for "
    "some personas — a rate over an empty answer is undefined, not zero.",
    "Retrieval recall is reported beside matching recall because lexical retrieval is "
    "not language-neutral: part of any code-mix gap is retrieval, not reasoning. The "
    "`rag[oracle_all]` arm removes retrieval error entirely.",
    "`grounding[oracle_extraction]` reads the persona's annotated facts instead of the "
    "query text, so its answer cannot depend on the language of the query. A non-zero "
    "RQ2 delta on that row would mean the harness is leaking the condition somewhere; a "
    "zero delta there, beside a non-zero one on `probe:topical`, localises the whole "
    "measured code-mix effect in this run to retrieval.",
]


def check_metrics_discriminate(scores) -> list[str]:
    """Assert the metric suite separates known-good from known-broken behaviour.

    These are not unit tests of a function; they are checks that the *evaluation design*
    can see what it was built to see. Each failure below would invalidate a specific claim
    the paper intends to make.
    """
    summary = summarize(scores)

    def stat(system: str, metric: str, condition: str = "english"):
        block = summary.get(f"{system}|{condition}")
        return (block or {}).get(metric, {}).get("mean")

    failures: list[str] = []

    oracle_f1 = stat("probe:oracle", "f1")
    if oracle_f1 != 1.0:
        failures.append(
            f"A perfectly correct system scores F1={oracle_f1}, not 1.0. The metric "
            "punishes correct behaviour — most likely the empty-gold-set convention."
        )

    oracle_fpr = stat("probe:oracle", "fpr")
    if oracle_fpr not in (0.0, None):
        failures.append(f"A correct system shows a non-zero false-positive rate ({oracle_fpr}).")

    blind_fpr = stat("probe:threshold_blind", "fpr")
    if blind_fpr is None or (oracle_fpr is not None and blind_fpr <= oracle_fpr):
        failures.append(
            f"Ignoring every numeric threshold does not raise the false-positive rate "
            f"({blind_fpr} vs {oracle_fpr}). RQ1 cannot be measured with this metric."
        )

    excl_fpr = stat("probe:exclusion_blind", "fpr")
    if excl_fpr is None or (oracle_fpr is not None and excl_fpr <= oracle_fpr):
        failures.append(
            f"Ignoring exclusion clauses does not raise the false-positive rate ({excl_fpr})."
        )

    abstain_fpr = stat("probe:abstain", "fpr")
    if abstain_fpr is not None:
        failures.append(
            f"A system that always abstains posts a false-positive rate of {abstain_fpr} "
            "instead of no score. The metric rewards silence."
        )

    abstain_recall = stat("probe:abstain", "recall")
    if abstain_recall not in (0.0, None) and abstain_recall > 0.5:
        failures.append(f"A system that answers nothing scores recall {abstain_recall}.")

    topical_gap = stat("probe:topical[k=5]", "retrieval_gap")
    topical_fpr = stat("probe:topical[k=5]", "fpr")
    if topical_fpr is None or (oracle_fpr is not None and topical_fpr <= oracle_fpr):
        failures.append(
            f"Returning retrieved schemes unfiltered does not raise the false-positive "
            f"rate ({topical_fpr}). The retrieval-vs-matching distinction is not being measured."
        )

    no_elicit_recall = stat("ablation:no_elicitation", "recall")
    oracle_recall = stat("probe:oracle", "recall")
    if no_elicit_recall is not None and oracle_recall is not None:
        if no_elicit_recall >= oracle_recall:
            failures.append(
                "Refusing to ask any question costs nothing in recall — the personas are "
                "not underspecified enough for elicitation to matter."
            )
    no_elicit_fpr = stat("ablation:no_elicitation", "fpr")
    if no_elicit_fpr not in (0.0, None):
        failures.append(
            f"The no-elicitation grounding ablation produced false positives ({no_elicit_fpr}). "
            "It should only ever under-answer; this suggests the rule engine is asserting "
            "eligibility on incomplete profiles."
        )

    _ = topical_gap  # reported in the table; not asserted on, since it depends on k
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["anthropic", "openai", "none"], default="none")
    parser.add_argument("--model", default=None)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    kb = load_kb()
    personas = load_personas()

    problems = validate_kb(kb) + validate_personas(personas, kb)
    if problems:
        print("Validation failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    systems = reference_suite(kb)
    # The structured pipeline with extraction replaced by the persona's annotated facts.
    # It needs no API key, and it is the arm that answers RQ3's first half: what the
    # grounding approach is worth when extraction is not the bottleneck. Its answers do not
    # depend on the language of the query — it reads the annotation, not the text — which
    # makes it the control for RQ2: any code-mix effect it shows would be a bug in the
    # harness, and any effect the other arms show has to come from reading the query.
    systems.insert(1, OracleExtractionPipeline(kb))

    client = None
    if args.backend != "none":
        from tn_schemematch.systems.clients import make_client

        client = make_client(args.backend, args.model)
        systems += [
            RAGBaseline(client, kb, retriever=BM25Retriever(kb), top_k=args.top_k),
            RAGBaseline(client, kb, retriever=OracleRetriever(kb)),
            DirectSystem(client, kb),
            GroundingPipeline(client, kb),
        ]

    print(f"Running {len(systems)} system(s) x {len(personas)} persona(s) x 2 conditions\n")
    results = run_experiment(systems, personas, kb, progress=True)
    scores = score_results(results, personas, kb)

    print("\n=== METRIC DISCRIMINATION CHECK ===")
    failures = check_metrics_discriminate(scores)
    if failures:
        print(f"{len(failures)} check(s) FAILED — the metric suite cannot support the "
              "claims it is meant to:\n")
        for failure in failures:
            print(f"  ✗ {failure}\n")
    else:
        print("All checks passed. The metrics separate correct behaviour from each known "
              "failure mode.\n")

    unvalidated = [p.id for p in personas if not p.annotation.validated_by]
    metadata = {
        "backend": args.backend,
        "model": client.name if client else "none",
        "n_schemes": len(kb),
        "n_personas": len(personas),
        "kb_verified": bool(kb.verified()),
        "personas_validated": not unvalidated,
        "metric_checks_passed": not failures,
    }

    out = Path(args.out or (REPO_ROOT / "data" / "runs" /
                            f"pilot-{datetime.now().strftime('%Y%m%d-%H%M%S')}"))
    save_run(out, results, scores, metadata=metadata)

    notes = list(NOTES)
    if failures:
        notes = [f"**METRIC CHECK FAILED:** {f}" for f in failures] + notes

    report = markdown_report(
        scores,
        title="TN-SchemeMatch pilot — metric discrimination check",
        metadata=metadata,
        notes=notes,
    )
    (out / "report.md").write_text(report, encoding="utf-8")

    print(report)
    print(f"\nwrote {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
