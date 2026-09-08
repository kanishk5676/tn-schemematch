#!/usr/bin/env python3
"""Snapshot and diff the benchmark's ground truth.

    python scripts/gold_diff.py snapshot --label pre-batch-ka
    python scripts/gold_diff.py check --baseline .snapshots/pre-batch-ka.json \
           --expect-added ka-widow-pension,ka-oap

This exists because of one failure mode that nothing else in the repo detects. Gold labels
are computed, not written down, so a change to the attribute spec, to a shared rule, or to
a persona's back-filled default silently rewrites the answers the whole benchmark is scored
against — and every test stays green, because every test is scored against the same
rewritten answers.

The invariant it enforces:

    Adding scheme X may add X to a persona's eligible set. It may not change that
    persona's verdict on any scheme that is not X.

Anything else means a spec edit, a rule edit or an attribute default leaked into a batch it
did not belong to. That is the corruption with no other detector, and it compounds — by the
time it is noticed the baseline it should have been caught against is gone.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tn_schemematch import load_kb                       # noqa: E402
from tn_schemematch.attributes import default_spec       # noqa: E402
from tn_schemematch.personas import load_personas        # noqa: E402

SNAPSHOT_DIR = REPO_ROOT / ".snapshots"


def build_snapshot() -> dict:
    """Every persona's verdict on every active scheme, plus the derived gold sets."""
    spec = default_spec()
    kb = load_kb(None, spec)
    active = kb.active()
    personas = load_personas(None, spec)

    verdicts: dict[str, dict[str, str]] = {}
    gold: dict[str, list[str]] = {}
    for persona in personas:
        profile = persona.profile
        buckets = active.match(profile)
        row = {}
        for verdict, ids in buckets.items():
            for scheme_id in ids:
                row[scheme_id] = verdict.value
        verdicts[persona.id] = row
        gold[persona.id] = sorted(persona.gold_eligible(kb))

    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "n_schemes": len(kb),
        "n_active": len(active),
        "n_personas": len(personas),
        "scheme_ids": sorted(active.ids()),
        "attribute_spec_version": spec.version,
        "verdicts": verdicts,
        "gold": gold,
    }


def cmd_snapshot(args) -> int:
    snapshot = build_snapshot()
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    path = SNAPSHOT_DIR / f"{args.label}.json"
    path.write_text(json.dumps(snapshot, indent=1, ensure_ascii=False))
    print(f"wrote {path.relative_to(REPO_ROOT)}  "
          f"({snapshot['n_active']} active schemes x {snapshot['n_personas']} personas)")
    return 0


def cmd_check(args) -> int:
    baseline = json.loads(Path(args.baseline).read_text())
    current = build_snapshot()
    expected_new = {s.strip() for s in (args.expect_added or "").split(",") if s.strip()}

    problems: list[str] = []

    # --- the scheme set itself ------------------------------------------------
    was = set(baseline["scheme_ids"])
    now = set(current["scheme_ids"])
    actually_new = now - was
    removed = was - now

    if removed:
        problems.append(f"schemes DISAPPEARED from the active KB: {sorted(removed)}")
    if actually_new != expected_new:
        unannounced = actually_new - expected_new
        missing = expected_new - actually_new
        if unannounced:
            problems.append(f"schemes added but not declared via --expect-added: "
                            f"{sorted(unannounced)}")
        if missing:
            problems.append(f"declared via --expect-added but not present: {sorted(missing)}")

    # --- the invariant --------------------------------------------------------
    # A new scheme may appear in a persona's row. Nothing else about that row may move.
    changed_verdicts = 0
    lost_gold = 0
    for persona_id, old_row in baseline["verdicts"].items():
        new_row = current["verdicts"].get(persona_id)
        if new_row is None:
            problems.append(f"persona {persona_id} disappeared")
            continue
        for scheme_id, old_verdict in old_row.items():
            new_verdict = new_row.get(scheme_id)
            if new_verdict is None:
                problems.append(f"{persona_id}: scheme {scheme_id} no longer evaluated")
            elif new_verdict != old_verdict:
                changed_verdicts += 1
                if changed_verdicts <= 12:
                    problems.append(
                        f"{persona_id}: {scheme_id} moved {old_verdict} -> {new_verdict} "
                        f"(this scheme is not part of this batch)")

        old_gold = set(baseline["gold"][persona_id])
        new_gold = set(current["gold"].get(persona_id, []))
        dropped = old_gold - new_gold
        if dropped:
            lost_gold += 1
            if lost_gold <= 12:
                problems.append(f"{persona_id}: LOST eligibility for {sorted(dropped)}")
        gained = new_gold - old_gold - expected_new
        if gained:
            problems.append(f"{persona_id}: gained {sorted(gained)}, which this batch "
                            f"did not add")

    if changed_verdicts > 12:
        problems.append(f"... and {changed_verdicts - 12} further verdict changes")

    new_personas = set(current["verdicts"]) - set(baseline["verdicts"])
    if new_personas:
        print(f"note: {len(new_personas)} new persona(s): {sorted(new_personas)[:6]}")

    if baseline["attribute_spec_version"] != current["attribute_spec_version"]:
        print(f"note: attribute spec {baseline['attribute_spec_version']} -> "
              f"{current['attribute_spec_version']}")

    # --- report ---------------------------------------------------------------
    print(f"baseline {baseline['n_active']} active schemes -> now {current['n_active']}")
    if expected_new:
        print(f"expected additions: {sorted(expected_new)}")

    if problems:
        print(f"\nGOLD DIFF FAILED — {len(problems)} problem(s):", file=sys.stderr)
        for problem in problems[:30]:
            print(f"  - {problem}", file=sys.stderr)
        print("\nA batch that adds schemes must not move any other verdict. Something "
              "outside this batch changed — check the attribute spec, a shared rule, or a "
              "persona back-fill.", file=sys.stderr)
        return 1

    print("clean: every difference is an expected addition, and no persona lost anything.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    snap = sub.add_parser("snapshot", help="record the current ground truth")
    snap.add_argument("--label", required=True)
    snap.set_defaults(func=cmd_snapshot)

    check = sub.add_parser("check", help="diff current ground truth against a snapshot")
    check.add_argument("--baseline", required=True)
    check.add_argument("--expect-added", default="",
                       help="comma-separated scheme ids this batch is allowed to add")
    check.set_defaults(func=cmd_check)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
