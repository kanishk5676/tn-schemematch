#!/usr/bin/env python3
"""Run the benchmark grid and write a scored report.

    python scripts/run_experiment.py --backend anthropic --model claude-sonnet-5
    python scripts/run_experiment.py --backend none      # offline: rule-only arms

The offline mode runs the arms that need no model — the oracle-extraction grounding
pipeline and the retrieval-only diagnostics — which is enough to sanity-check the KB and
the metrics before spending anything on a model.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tn_schemematch import load_kb, validate_kb                       # noqa: E402
from tn_schemematch.eval.runner import (                               # noqa: E402
    rq2_report,
    run_experiment,
    save_run,
    score_results,
    summarize,
)
from tn_schemematch.personas import load_personas, validate_personas   # noqa: E402
from tn_schemematch.systems.grounding import (                         # noqa: E402
    GroundingPipeline,
    OracleExtractionPipeline,
)
from tn_schemematch.systems.rag_baseline import DirectSystem, RAGBaseline  # noqa: E402
from tn_schemematch.systems.retrieval import BM25Retriever, OracleRetriever  # noqa: E402


def build_client(backend: str, model: str, temperature: float):
    if backend == "none":
        return None
    from tn_schemematch.systems.clients import AnthropicClient, CachingClient, OpenAIClient

    inner = (
        AnthropicClient(model=model, temperature=temperature)
        if backend == "anthropic"
        else OpenAIClient(model=model, temperature=temperature)
    )
    return CachingClient(inner)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["anthropic", "openai", "none"], default="none")
    parser.add_argument("--model", default="claude-sonnet-5")
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--out", default=None)
    parser.add_argument("--allow-unverified", action="store_true",
                        help="run against a KB that has not been human-verified")
    parser.add_argument("--max-personas", type=int, default=None,
                        help="score only the first N personas — a costed subset run. The "
                             "slice keeps every hand-written persona before any sampled "
                             "one, so the awkward cases are the ones that survive.")
    args = parser.parse_args()

    kb = load_kb()
    personas = load_personas()

    problems = validate_kb(kb) + validate_personas(personas, kb)
    if problems:
        print("Validation failed — fix these before running:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    if not kb.verified() and not args.allow_unverified:
        print(
            "REFUSING TO RUN: no scheme in this KB is human-verified, so any result would be\n"
            "a measurement of unverified rules rather than of the systems. Complete the pass in\n"
            "docs/verification-protocol.md, or pass --allow-unverified for a development run\n"
            "whose numbers must not be reported.",
            file=sys.stderr,
        )
        return 2

    unvalidated = [p.id for p in personas if not p.annotation.validated_by]
    if unvalidated:
        print(f"WARNING: {len(unvalidated)} persona(s) are not natively validated: "
              f"{unvalidated}\n         Their results are diagnostic only.\n")

    if args.max_personas:
        # Hand-written personas (p*) sort before the generated archetypes (g*), and they
        # are the ones chosen because they are hard. Taking a prefix of that order keeps
        # the interesting cases and thins only the samples.
        from tn_schemematch.personas import PersonaSet
        chosen = sorted(personas, key=lambda p: (p.id.startswith("g"), p.id))
        personas = PersonaSet({p.id: p for p in chosen[: args.max_personas]}, personas.spec)
        print(f"Subset run: {len(personas)} persona(s)\n")

    client = build_client(args.backend, args.model, args.temperature)

    systems = [OracleExtractionPipeline(kb)]
    if client is not None:
        systems += [
            RAGBaseline(client, kb, retriever=BM25Retriever(kb), top_k=args.top_k),
            RAGBaseline(client, kb, retriever=OracleRetriever(kb)),  # retrieval-error-free arm
            DirectSystem(client, kb),
            GroundingPipeline(client, kb),
        ]

    print(f"Running {len(systems)} system(s) x {len(personas)} persona(s) x 2 conditions\n")
    results = run_experiment(systems, personas, kb, progress=True)
    scores = score_results(results, personas, kb)

    out = Path(args.out or (REPO_ROOT / "data" / "runs" /
                            datetime.now().strftime("%Y%m%d-%H%M%S")))
    save_run(out, results, scores, metadata={
        "backend": args.backend,
        "model": args.model,
        "temperature": args.temperature,
        "top_k": args.top_k,
        "kb_verified": bool(kb.verified()),
        "personas_validated": not unvalidated,
        "n_schemes": len(kb),
        "n_personas": len(personas),
        "subset": bool(args.max_personas),
    })

    print("\n=== SUMMARY ===")
    print(json.dumps(summarize(scores), indent=2, ensure_ascii=False))
    print("\n=== RQ2: code-mixed minus English ===")
    print(json.dumps(rq2_report(scores), indent=2, ensure_ascii=False))
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
