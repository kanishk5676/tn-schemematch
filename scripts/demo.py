#!/usr/bin/env python3
"""Live eligibility interview: type a code-mixed question, get an audited answer.

    python scripts/demo.py                        # live, you answer the questions
    python scripts/demo.py --persona p001         # auto-answer from a test profile (hands-free)
    python scripts/demo.py --backend none         # no model: skip extraction, ask everything

The demo is the interview engine at a keyboard. The division of labour is unchanged and is the point worth
showing: the model reads one messy sentence and fills attribute slots, and every decision
after that is a rule evaluation that prints its own reasoning. The model is never asked
whether someone qualifies.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from tn_schemematch.attributes import SchemaError, default_spec      # noqa: E402
from tn_schemematch.elicitation import question_priority             # noqa: E402
from tn_schemematch.kb import load_kb                                # noqa: E402
from tn_schemematch.rules import Verdict                             # noqa: E402
from tn_schemematch.interview import EXTRACTION_SYSTEM_PROMPT       # noqa: E402
from tn_schemematch.systems.base import attribute_catalogue, parse_json_response  # noqa: E402

# ------------------------------------------------------------------ presentation

_TTY = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def bold(t: str) -> str:   return _c(t, "1")
def dim(t: str) -> str:    return _c(t, "2")
def green(t: str) -> str:  return _c(t, "32")
def red(t: str) -> str:    return _c(t, "31")
def yellow(t: str) -> str: return _c(t, "33")
def cyan(t: str) -> str:   return _c(t, "36")


def rule(char: str = "─", width: int = 74) -> str:
    return dim(char * width)


SAMPLE_QUERIES = [
    "enakku ration card irukku, vivasayi, rendu ekkar nilam — enna scheme kedaikum?",
    "naan widow, 55 vayasu, Madurai la irukken. enna udhavi kidaikum?",
    "en ponnu 12th padikkira, government school, enna scholarship irukku?",
    "I am a 34 year old tailor in Salem, I have a shop but no land. What can I apply for?",
]


# ------------------------------------------------------------------ answer parsing

_NORMALIZE_SYSTEM = """\
You convert one citizen's answer into a single canonical value for one attribute.

You are given the attribute's name, type, and permitted values. The answer may be in \
English, Tamil script, or romanized Tamil, and may contain units the citizen chose \
themselves ("rendu ekkar", "month-ku 8000").

Reply with JSON only: {"value": <value>} using the canonical type, or {"value": null} if \
the answer does not actually state the attribute. Never guess a plausible value."""


def question_text(attr) -> str:
    """The first sentence of the attribute's description, as the question to a citizen.

    Descriptions carry maintainer notes after the first sentence — unit conversion
    factors, why the domain is drawn where it is. Those belong in the vocabulary file,
    not on screen in front of the person being interviewed.
    """
    first = attr.description.strip().splitlines()[0].strip()
    for stop in (". ", "; "):
        if stop in first:
            first = first.split(stop)[0]
            break
    return first.rstrip(".") + "?" if first.lower().startswith(
        ("is ", "are ", "does ", "do ", "has ", "have ", "whether ")) else first.rstrip(".") + "."


def describe_attr(attr) -> str:
    """The type/domain hint shown under a question."""
    if attr.type == "enum":
        return f"one of: {', '.join(str(v) for v in attr.domain or ())}"
    if attr.type == "bool":
        return "yes / no"
    if attr.type == "number":
        lo, hi = attr.domain or ("", "")
        span = f", {lo}–{hi}" if attr.domain else ""
        return f"a number in {attr.unit or 'units'}{span}"
    return attr.type


def parse_answer(spec, attr_name: str, raw: str, client) -> tuple[object, str]:
    """Turn a free-text answer into a canonical value.

    Deterministic first: the vocabulary already carries Tamil and romanized aliases, so
    most answers normalize without a model call. The model is the fallback for phrasings
    the alias table does not cover, which keeps the live path fast and keeps the model out
    of the decision itself.
    """
    try:
        return spec.canonicalize(attr_name, raw), "aliases"
    except SchemaError:
        pass
    if client is None:
        return None, "unparsed"
    attr = spec[attr_name]
    user = (
        f"ATTRIBUTE: {attr_name}\n"
        f"TYPE: {attr.type} ({describe_attr(attr)})\n"
        f"MEANING: {attr.description.strip()}\n\n"
        f'CITIZEN\'S ANSWER: "{raw}"'
    )
    try:
        payload = parse_json_response(client.complete(_NORMALIZE_SYSTEM, user, json_mode=True))
        value = payload.get("value") if isinstance(payload, dict) else None
        if value is None:
            return None, "model-said-unstated"
        return spec.canonicalize(attr_name, value), "model"
    except Exception as exc:  # noqa: BLE001 — an unparseable answer is a real outcome
        return None, f"unparsed ({type(exc).__name__})"


# ------------------------------------------------------------------ display helpers

def show_board(active, profile, *, note: str = "") -> dict:
    buckets = active.match(profile)
    n_yes, n_no = len(buckets[Verdict.TRUE]), len(buckets[Verdict.FALSE])
    n_open = len(buckets[Verdict.UNKNOWN])
    line = (f"  {green(f'{n_yes} eligible')}   {red(f'{n_no} ruled out')}   "
            f"{yellow(f'{n_open} still open')}")
    print(line + (dim(f"   {note}") if note else ""))
    return buckets


def show_profile(spec, profile, keys=None) -> None:
    keys = sorted(keys if keys is not None else profile)
    if not keys:
        print(dim("  (nothing)"))
        return
    for name in keys:
        if name not in profile:
            continue
        derived = name in spec and spec[name].is_derived
        tag = dim("  (derived)") if derived else ""
        print(f"  {name:34s} = {bold(str(profile[name]))}{tag}")


def show_results(kb, active, profile, asked) -> None:
    print()
    print(rule("═"))
    print(bold("  RESULT"))
    print(rule("═"))

    buckets = active.match(profile)
    eligible = buckets[Verdict.TRUE]
    still_open = buckets[Verdict.UNKNOWN]

    if eligible:
        print(f"\n{green(bold(f'✓ Eligible for {len(eligible)} scheme(s)'))}\n")
        for scheme_id in eligible:
            scheme = kb[scheme_id]
            print(f"  {bold(scheme.name)}")
            if scheme.name_ta:
                print(f"  {dim(scheme.name_ta)}")
            if scheme.benefit_prose:
                print(f"    {scheme.benefit_prose.strip().splitlines()[0]}")
            if scheme.apply_url:
                print(dim(f"    apply: {scheme.apply_url}"))
            print(dim("    why:"))
            for line in scheme.decide(profile).explain(indent=3).splitlines():
                print(dim(line))
            print()
    else:
        print(f"\n{yellow('No scheme is confirmed on what we know.')}\n")

    # Near misses are the most useful thing on the screen for a citizen: one clause away.
    near = []
    for scheme_id in buckets[Verdict.FALSE]:
        failing = kb[scheme_id].decide(profile).failing_predicates()
        if len(failing) == 1:
            near.append((scheme_id, failing[0]))
    if near:
        print(rule())
        print(dim(f"  Missed by a single condition ({len(near)}):"))
        for scheme_id, predicate in near[:6]:
            print(f"    {kb[scheme_id].name}")
            print(red(f"      needs: {predicate.describe()}"))
        print()

    if still_open:
        print(dim(f"  {len(still_open)} scheme(s) remain undetermined and are reported as "
                  f"not eligible:"))
        print(dim(f"    {', '.join(still_open)}"))
        print()

    print(rule())
    print(f"  questions asked: {bold(str(len(asked)))}")
    print(dim("  Every verdict above is a rule evaluation, not a model assertion."))
    print(yellow("  KB is unverified draft data — demo only, not advice."))
    print(rule())


# ------------------------------------------------------------------ main

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backend", choices=["anthropic", "openai", "none"],
                        default="anthropic")
    parser.add_argument("--model", default=None)
    parser.add_argument("--query", default=None, help="skip the prompt and use this query")
    parser.add_argument("--persona", default=None,
                        help="auto-answer from a test profile instead of a keyboard")
    parser.add_argument("--max-questions", type=int, default=40)
    args = parser.parse_args()

    spec = default_spec()
    kb = load_kb(None, spec)
    active = kb.active()

    client = None
    if args.backend != "none":
        # Fail here rather than inside the first call. The client retries with backoff, so
        # a missing key otherwise surfaces as a seven-second pause and a stack trace —
        # which is a bad thing to discover while someone is watching.
        from tn_schemematch.systems.clients import has_credentials, make_client
        env_var = ("ANTHROPIC_API_KEY" if args.backend == "anthropic"
                   else "OPENAI_API_KEY")
        if not has_credentials(args.backend):
            print(red(f"\n  {env_var} is not set."))
            print(f"  Set it, or run rules-only with {bold('--backend none')}:\n")
            print(f"    export {env_var}='...'")
            print(f"    python scripts/demo.py\n")
            return 2
        client = make_client(args.backend, args.model)

    print()
    print(rule("═"))
    print(bold("  TN-SchemeMatch — live eligibility interview"))
    print(rule("═"))
    print(f"  {len(active)} active schemes   {len(spec.elicitable_names())} attributes   "
          f"model: {bold(client.name if client else 'none (rules only)')}")
    print(dim("  Ask in Tamil, English, or a mix of both."))
    print()

    # -- the citizen, real or simulated -------------------------------------
    persona = None
    if args.persona:
        from tn_schemematch.personas import load_personas
        persona = load_personas(None, spec)[args.persona]
        query = args.query or persona.queries["code_mixed"]
        print(dim(f"  auto-answering as test profile {persona.id}"))
    else:
        query = args.query

    if not query:
        print(bold("  Sample questions:"))
        for i, sample in enumerate(SAMPLE_QUERIES, 1):
            print(f"    {i}. {sample}")
        print()
        try:
            raw = input(bold("  Your question (or 1-4): ")).strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  cancelled")
            return 1
        query = (SAMPLE_QUERIES[int(raw) - 1]
                 if raw.isdigit() and 1 <= int(raw) <= len(SAMPLE_QUERIES) else raw)
    if not query:
        print("  no question given")
        return 1

    print()
    print(rule())
    print(f'  {cyan(query)}')
    print(rule())

    # -- 1. extract ---------------------------------------------------------
    profile: dict = {}
    if client is not None:
        print(f"\n{bold('1. Extracting facts from the question')} {dim('(model)')}")
        started = time.time()
        try:
            user = (f"ATTRIBUTES:\n{attribute_catalogue(spec)}"
                    f'\n\nCITIZEN\'S QUESTION:\n"{query}"')
            raw_extraction = parse_json_response(
                client.complete(EXTRACTION_SYSTEM_PROMPT, user, json_mode=True))
        except Exception as exc:  # noqa: BLE001
            print(red(f"  extraction failed: {type(exc).__name__}: {exc}"))
            raw_extraction = {}
        elapsed = time.time() - started

        rejected = []
        for name, value in (raw_extraction or {}).items():
            if name not in spec or value is None:
                rejected.append(f"{name}={value!r} (not in vocabulary)")
                continue
            if spec[name].is_derived:
                rejected.append(f"{name}={value!r} (derived; recomputed)")
                continue
            try:
                profile[name] = spec.canonicalize(name, value)
            except SchemaError as exc:
                rejected.append(f"{name}={value!r} ({exc})")
        profile.update(spec.derive(profile))
        print(dim(f"  {elapsed:.1f}s"))
        show_profile(spec, profile)
        for item in rejected:
            print(red(f"  dropped: {item}"))
    else:
        print(f"\n{bold('1. Extraction skipped')} {dim('(--backend none)')}")

    print()
    show_board(active, profile, note="after reading the question")

    # -- 2. elicit ----------------------------------------------------------
    print(f"\n{bold('2. Interview')} {dim('— highest-value question first, re-ranked after every answer')}")
    print(dim("   type an answer, 'skip' to pass, 'done' to stop early\n"))

    asked: list[str] = []
    skipped: set[str] = set()
    while len(asked) < args.max_questions:
        if not active.match(profile)[Verdict.UNKNOWN]:
            print(green("  every scheme is settled — no more questions needed"))
            break
        ranked = [a for a in question_priority(active, profile)
                  if a not in asked and a not in skipped and profile.get(a) is None]
        if not ranked:
            break
        attr_name = ranked[0]
        attr = spec[attr_name]
        asked.append(attr_name)

        print(f"  {bold(f'Q{len(asked)}.')} {question_text(attr)}")
        print(dim(f"      {attr_name} · {describe_attr(attr)}"))

        if persona is not None:
            value = persona.profile.get(attr_name)
            print(f"      {cyan(str(value).replace('_', ' ') if value is not None else 'I do not know.')}")
            source = "test profile"
            if value is None:
                skipped.add(attr_name)
        else:
            try:
                raw = input("      > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  stopping early")
                break
            if raw.lower() in {"done", "quit", "exit"}:
                break
            if not raw or raw.lower() in {"skip", "idk", "dunno"}:
                skipped.add(attr_name)
                print(dim("      (skipped — the schemes needing it stay undetermined)"))
                print()
                continue
            value, source = parse_answer(spec, attr_name, raw, client)

        if value is None:
            skipped.add(attr_name)
            print(yellow(f"      could not read that answer ({source}) — moving on"))
        else:
            before = len(active.match(profile)[Verdict.UNKNOWN])
            profile[attr_name] = value
            profile.update(spec.derive(profile))
            after = len(active.match(profile)[Verdict.UNKNOWN])
            settled = before - after
            note = f"settled {settled} scheme(s)" if settled else "settled nothing yet"
            print(dim(f"      → {attr_name} = {value}  [{source}]  {note}"))
        show_board(active, profile)
        print()

    show_results(kb, active, profile, asked)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
