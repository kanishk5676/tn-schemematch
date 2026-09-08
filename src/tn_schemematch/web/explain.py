"""Plain-language explanation of a decision the rule engine already made.

The model is handed the conclusion *and its evidence* and asked only to phrase it. It
receives the satisfied clauses and nothing else — not the profile, not the other schemes,
not the rules that failed — and it is told to mention no condition outside that list. So
the failure mode available to it is a clumsy sentence, not a wrong verdict.

The page renders the trace directly above the generated paragraph. That is a stronger
guarantee than the prompt: any drift between the two is visible side by side, on the same
screen, to the person reading it.
"""

from __future__ import annotations

from ..attributes import AttributeSpec
from ..kb import Scheme
from ..rules import Predicate, Trace, Verdict
from ..serialize import describe_clause, format_value
from ..systems.base import LLMClient

EXPLAIN_SYSTEM_PROMPT = """\
You are given an eligibility check that has ALREADY been decided by a rule engine. Your \
only job is to restate the listed conditions as prose a citizen can read.

Rules you must follow:
- Use ONLY the conditions listed. Do not add, infer, or imply any other requirement.
- Do not say the person qualifies for anything not named.
- Do not give advice, and do not describe how to apply.
- Two or three short sentences. Address the reader as "you".

Reply with the explanation text only — no JSON, no preamble, no bullet points."""

_LANGUAGES = {
    "en": "Write in plain English.",
    "ta": "Write in Tamil (தமிழ்). Use everyday spoken Tamil, not formal literary Tamil. "
          "Keep scheme names and rupee amounts as they are.",
}


def grounding_lines(trace: Trace, spec: AttributeSpec) -> list[str]:
    """The satisfied clauses, as sentences. This is the model's entire evidence set."""
    lines: list[str] = []
    for node in _walk(trace):
        if not isinstance(node.node, Predicate) or node.verdict is not Verdict.TRUE:
            continue
        sentence = describe_clause(node.node, spec)
        if node.actual is not None:
            sentence += f" — you said {format_value(spec, node.node.attr, node.actual)}"
        lines.append(sentence)
    return lines


def _walk(trace: Trace):
    yield trace
    for child in trace.children:
        yield from _walk(child)


def explain_trace(client: LLMClient, scheme: Scheme, trace: Trace, spec: AttributeSpec,
                  *, language: str = "en") -> str:
    """Phrase a satisfied rule trace as prose. Never called for a scheme that failed."""
    lines = grounding_lines(trace, spec)
    if not lines:
        return ""
    benefit = (scheme.benefit_prose or scheme.summary or "").strip().splitlines()
    user = "\n".join([
        _LANGUAGES.get(language, _LANGUAGES["en"]),
        "",
        f"SCHEME: {scheme.name}",
        f"BENEFIT: {benefit[0] if benefit else '(not stated)'}",
        "",
        "CONDITIONS THIS PERSON SATISFIES:",
        *(f"- {line}" for line in lines),
    ])
    return client.complete(EXPLAIN_SYSTEM_PROMPT, user).strip()
