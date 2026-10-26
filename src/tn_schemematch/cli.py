"""Command line entry point.

    schemematch validate          check the KB and persona set
    schemematch stats             coverage and benchmark statistics
    schemematch build             export the KB and benchmark as released artifacts
    schemematch explain           print the rule trace for a persona against a scheme
    schemematch ask               show what an agent should ask next, and why
    schemematch verify-queue      list what still needs human verification
    schemematch serve             run the browser front end
    schemematch watch-sources     re-fetch every cited source and flag the changed ones
    schemematch keys              create, list or revoke partner API keys
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .attributes import default_spec
from .elicitation import (
    ground_truth,
    necessary_questions,
    resolving_power,
)
from .documents import load_documents, validate_documents
from .kb import STALE_AFTER_DAYS, load_kb, stale_schemes, validate_kb
from .personas import load_personas, validate_personas
from .rules import Verdict

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load(args) -> tuple:
    spec = default_spec()
    kb = load_kb(args.kb, spec)
    personas = load_personas(args.personas, spec) if Path(args.personas or
                                                          (_REPO_ROOT / "data/personas")).exists() else None
    return spec, kb, personas


# ------------------------------------------------------------------- commands


def cmd_validate(args) -> int:
    spec, kb, personas = _load(args)
    documents = load_documents(spec)
    problems = validate_kb(kb) + validate_documents(documents, kb)
    if personas is not None:
        problems += validate_personas(personas, kb)

    print(f"KB:       {len(kb)} schemes ({len(kb.active())} active, "
          f"{len(kb.verified())} human-verified)")
    print(f"Documents: {len(documents.uploadable())} document types, every scheme "
          "requirement mapped" if not validate_documents(documents, kb) else
          f"Documents: {len(documents.uploadable())} document types")
    if personas is not None:
        print(f"Personas: {len(personas)}")

    # Stale sources are reported but never fail validation: the rule still parses and
    # still means what it meant, it just needs a person to re-read its source.
    stale = stale_schemes(kb, max_age_days=args.max_age_days)
    if stale:
        print(f"\n{len(stale)} warning(s), no source checked in {args.max_age_days} days:")
        for warning in stale:
            print(f"  - {warning}")
    if not problems:
        print("\nAll checks passed.")
        return 0
    print(f"\n{len(problems)} problem(s):")
    for problem in problems:
        print(f"  - {problem}")
    return 1


def cmd_stats(args) -> int:
    _, kb, personas = _load(args)
    report = {"kb": kb.coverage_report()}
    if personas is not None:
        report["benchmark"] = personas.summary(kb)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_build(args) -> int:
    _, kb, personas = _load(args)
    out = Path(args.out or (_REPO_ROOT / "kb" / "build"))
    written = [kb.to_json(out / "schemes.json")]
    if personas is not None:
        written.append(personas.to_jsonl(out / "benchmark.jsonl", kb))
    for path in written:
        print(f"wrote {path}")
    if not kb.verified():
        print("\nNOTE: no scheme is marked 'verified'. This export is a development "
              "artifact, not a release — run the human verification pass first "
              "(see docs/verification-protocol.md).")
    return 0


def cmd_explain(args) -> int:
    _, kb, personas = _load(args)
    if personas is None:
        print("no persona set found", file=sys.stderr)
        return 1
    persona = personas[args.persona]
    profile = persona.profile if args.full else persona.known_profile()
    label = "full profile" if args.full else "facts stated in the query only"

    scheme_ids = [args.scheme] if args.scheme else kb.active().ids()
    print(f"Persona {persona.id} — {label}\n")
    for scheme_id in scheme_ids:
        scheme = kb[scheme_id]
        trace = scheme.decide(profile)
        print(f"=== {scheme.id}: {scheme.name}")
        print(f"    verdict: {trace.verdict.value.upper()}")
        print(trace.explain(indent=2))
        print()
    return 0


def cmd_ask(args) -> int:
    _, kb, personas = _load(args)
    if personas is None:
        print("no persona set found", file=sys.stderr)
        return 1
    persona = personas[args.persona]
    active = kb.active()
    known = dict(persona.known_profile())
    known.update(kb.spec.derive(known))
    ground = ground_truth(active, persona.id, persona.known_profile(), persona.profile)

    print(f"Persona {persona.id}: {persona.persona_sketch.strip()}\n")
    print(f'Query (code-mixed): "{persona.queries["code_mixed"]}"\n')
    print("Known from the query:")
    for attr, value in sorted(known.items()):
        print(f"  {attr} = {value}")

    buckets = active.match(known)
    print(f"\nAlready settled: eligible={buckets[Verdict.TRUE]} "
          f"ineligible={len(buckets[Verdict.FALSE])} schemes")
    print(f"Still open: {buckets[Verdict.UNKNOWN]}")

    print(f"\nLegitimate questions ({len(ground.necessary)}): {sorted(ground.necessary)}")
    print("\nBest next questions (by how many schemes each would settle):")
    for attr, count in list(resolving_power(active, known).items())[:8]:
        print(f"  {attr:38s} settles {count} scheme(s)  [{kb.spec[attr].sensitivity} sensitivity]")

    print(f"\nMinimum questions to reach the right answer ({ground.minimal_n_questions}): "
          f"{ground.minimal_confirming}")
    print(f"Questions to settle every scheme ({ground.oracle_n_questions}): "
          f"{ground.oracle_sequence}")
    print(f"\nGold eligible set: {persona.gold_eligible(kb)}")
    return 0


def cmd_serve(args) -> int:
    """Run the browser front end.

    Flask is imported inside the function, never at module scope: the core package has no
    web dependency, and `schemematch validate` plus the test suite must keep working on an
    environment where Flask is not installed.
    """
    client = None
    if args.backend != "none":
        from .systems.clients import has_credentials, make_client
        if not has_credentials(args.backend):
            # Fail before binding a port rather than seven seconds into a live extraction.
            env_var = "ANTHROPIC_API_KEY" if args.backend == "anthropic" else "OPENAI_API_KEY"
            print(f"No credentials for {args.backend}. Set {env_var}, or run with "
                  "--backend none.", file=sys.stderr)
            return 2
        client = make_client(args.backend, args.model, max_retries=1)

    try:
        from .web import create_app
    except ImportError:
        print("Flask is not installed — pip install -e \".[web]\"", file=sys.stderr)
        return 1

    app = create_app(client=client, max_questions=args.max_questions, debug=args.debug,
                     vault_dir=args.vault_dir)
    print(f"\n  TN-SchemeMatch \u2192 http://{args.host}:{args.port}")
    print(f"  model: {getattr(client, 'name', 'none (rules only)')}\n")
    app.run(host=args.host, port=args.port, debug=args.debug, use_reloader=False)
    return 0


def cmd_verify_queue(args) -> int:
    _, kb, _ = _load(args)
    pending = [s for s in kb if not s.is_verified]
    print(f"{len(pending)} of {len(kb)} schemes await human verification.\n")
    for scheme in sorted(pending, key=lambda s: s.id):
        print(f"=== {scheme.id} ({scheme.status})")
        print(f"    {scheme.name}")
        for source in scheme.sources:
            print(f"    source: {source.url}  (retrieved {source.retrieved})")
        for line in scheme.notes.splitlines():
            if "VERIFY" in line or "WARNING" in line or "LIMITATION" in line:
                print(f"    ! {line.strip()}")
        print()
    return 0


def cmd_watch_sources(args) -> int:
    """Exit 1 when a source changed, so a scheduled job can alert; unreachable is not a change."""
    from .watch import fetch, load_baseline, save_baseline, watch

    _, kb, _ = _load(args)
    baseline = load_baseline(args.baseline)
    rows = watch(kb, baseline, fetcher=lambda url: fetch(url, timeout=args.timeout))
    marks = {"unchanged": " ", "new": "+", "changed": "!", "unreachable": "?"}
    for row in rows:
        print(f"{marks[row['status']]} {row['status']:<11} {row['url']}")
        if row["status"] in {"changed", "unreachable"}:
            print(f"    {', '.join(row['schemes'])}{'  — ' + row['error'] if 'error' in row else ''}")
    counts = {status: sum(1 for r in rows if r["status"] == status) for status in marks}
    print("\n" + ", ".join(f"{n} {status}" for status, n in counts.items()))
    if args.update:
        print(f"fingerprints saved to {save_baseline(rows, baseline, args.baseline)}")
        return 0
    if counts["changed"]:
        print("Re-read each changed source against its scheme's rule, then run with --update.")
        return 1
    return 0


def cmd_keys(args) -> int:
    from .partners import create_key
    from .vault import DEFAULT_VAULT_DIR, Vault

    vault = Vault(args.vault_dir or DEFAULT_VAULT_DIR, default_spec())
    try:
        if args.action == "create":
            record, key = create_key(vault, args.name or "")
            print(f"Key for {record['name']} (id {record['id']}). It is shown once — store it now:")
            print(f"\n    {key}\n")
            print("Partners send it as:  Authorization: Bearer <key>  to POST /api/v1/check")
        elif args.action == "revoke":
            record = vault.revoke_api_key(args.name or "")
            print(f"revoked {record['id']} ({record['name']})")
        else:
            for record in vault.api_keys():
                state = "revoked" if record["revoked_at"] else "active"
                print(f"{record['id']}  {state:<8} {record['n_calls']:>6} calls  {record['name']}")
    except KeyError:
        print(f"no key with id {args.name!r}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        vault.close()
    return 0


# ----------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="schemematch", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--kb", default=None, help="scheme KB directory")
    parser.add_argument("--personas", default=None, help="persona directory")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="check the KB and persona set")
    validate.add_argument("--max-age-days", type=int, default=STALE_AFTER_DAYS,
                          help="warn about schemes whose newest source is older than this "
                               f"(default {STALE_AFTER_DAYS})")
    validate.set_defaults(func=cmd_validate)
    sub.add_parser("stats", help="coverage and benchmark statistics").set_defaults(func=cmd_stats)

    build = sub.add_parser("build", help="export released artifacts")
    build.add_argument("--out", default=None)
    build.set_defaults(func=cmd_build)

    serve = sub.add_parser("serve", help="run the browser front end")
    serve.add_argument("--backend", choices=["anthropic", "openai", "none"],
                       default="anthropic")
    serve.add_argument("--model", default=None,
                       help="defaults to claude-opus-5-5 (anthropic) / gpt-4o (openai)")
    serve.add_argument("--host", default="127.0.0.1")
    # 5000 is taken by ControlCenter/AirPlay on macOS out of the box.
    serve.add_argument("--port", type=int,
                       default=int(os.environ.get("PORT", 5001)))
    serve.add_argument("--max-questions", type=int, default=15)
    serve.add_argument("--debug", action="store_true")
    serve.add_argument("--vault-dir", default=None,
                       help="where saved profiles and documents live (default data/vault)")
    serve.set_defaults(func=cmd_serve)

    explain = sub.add_parser("explain", help="print the rule trace for a persona")
    explain.add_argument("persona")
    explain.add_argument("--scheme", default=None)
    explain.add_argument("--full", action="store_true",
                         help="use the full profile instead of only what the query states")
    explain.set_defaults(func=cmd_explain)

    ask = sub.add_parser("ask", help="show what should be asked next, and why")
    ask.add_argument("persona")
    ask.set_defaults(func=cmd_ask)

    sub.add_parser("verify-queue", help="list schemes awaiting human verification").set_defaults(
        func=cmd_verify_queue
    )

    watch = sub.add_parser("watch-sources", help="re-fetch cited sources and flag changes")
    watch.add_argument("--update", action="store_true", help="save the new fingerprints")
    watch.add_argument("--baseline", default=None, help="default kb/source-hashes.json")
    watch.add_argument("--timeout", type=float, default=20.0)
    watch.set_defaults(func=cmd_watch_sources)

    keys = sub.add_parser("keys", help="partner API keys")
    keys.add_argument("action", choices=["create", "list", "revoke"])
    keys.add_argument("name", nargs="?", help="who the key is for (create) or its id (revoke)")
    keys.add_argument("--vault-dir", default=None)
    keys.set_defaults(func=cmd_keys)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
