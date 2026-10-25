"""A headless, resumable eligibility interview.

The loop in :class:`~tn_schemematch.systems.grounding.GroundingPipeline` runs to
completion inside one call, driving a :class:`SimulatedCitizen` that answers from a
persona. That is exactly right for benchmarking and unusable anywhere a real person is
answering, because there is nowhere to suspend while the question sits on a screen.

This module inverts it: every operation takes an :class:`InterviewState` and returns a new
outcome, so a caller can persist the state between turns — an HTTP session, a terminal
loop, a test driving it question by question. The state is deliberately a plain
JSON-serializable record, so persisting it is ``json.dump`` and nothing more.

The division of labour is the one the project argues for. The model reads a messy sentence
and fills attribute slots, and it normalizes a free-text answer the alias table cannot.
Everything that decides anything — which question comes next, what each scheme's verdict
is — is a rule evaluation. Two invariants enforce that here rather than trusting callers:

- **Derived attributes are never accepted from outside.** ``spec.elicitable_names()`` is
  the allowlist; the five derived attributes are recomputed from their sources, so
  accepting one would let a caller contradict the vocabulary.
- **``spec.derive`` runs after every accepted answer**, inside :func:`apply_value`, because
  ``question_priority`` reads derived attributes when it ranks.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping

from .attributes import AttributeSpec, SchemaError
from .elicitation import question_priority, resolving_power
from .kb import SchemeKB
from .rules import Verdict
from .serialize import (
    attribute_form,
    board,
    format_value,
    label_for,
    near_misses,
    profile_rows,
    scheme_summary,
    trace_to_dict,
)
from .systems.base import LLMClient, attribute_catalogue, parse_json_response

# Imported rather than restated: the benchmark and the live app must extract with the same
# prompt, or the numbers stop describing the thing being demonstrated.
from .systems.grounding import EXTRACTION_SYSTEM_PROMPT

__all__ = [
    "EXTRACTION_SYSTEM_PROMPT",
    "NORMALIZE_SYSTEM_PROMPT",
    "AnswerOutcome",
    "Interview",
    "InterviewState",
    "extract_attributes",
    "next_question",
    "normalize_extraction",
    "parse_answer",
]

NORMALIZE_SYSTEM_PROMPT = """\
You convert one citizen's answer into a single canonical value for one attribute.

You are given the attribute's name, type, and permitted values. The answer may be in \
English, Tamil script, or romanized Tamil, and may contain units the citizen chose \
themselves ("rendu ekkar", "month-ku 8000").

Reply with JSON only: {"value": <value>} using the canonical type, or {"value": null} if \
the answer does not actually state the attribute. Never guess a plausible value."""

# Two bad free-text answers and the question is retired. Without a cap a stubborn phrasing
# can hold the interview on one question indefinitely, which on a stage is indistinguishable
# from a hang.
MAX_RETRIES = 2


# ------------------------------------------------------------------------------ state


@dataclass
class InterviewState:
    """Everything that must survive between two turns. JSON-serializable throughout."""

    query: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    asked: list[str] = field(default_factory=list)
    # Load-bearing, not an optimisation. ``question_priority`` is a pure function of
    # (kb, profile) with no memory of what was already refused, so without this a declined
    # question is re-ranked to the top on the very next turn, forever.
    skipped: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    retries: dict[str, int] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    raw_extraction: dict[str, Any] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)
    max_questions: int = 15
    used_ai: bool = False
    extraction_ms: int = 0
    extraction_error: str | None = None
    finished: bool = False

    @property
    def skipped_set(self) -> set[str]:
        return set(self.skipped)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "InterviewState":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class AnswerOutcome:
    """What one turn did. ``accepted`` false means the question is still open."""

    attr: str
    value: Any = None
    source: str = "unparsed"
    accepted: bool = False
    settled: int = 0
    message: str | None = None


# -------------------------------------------------------------------- free functions


def extract_attributes(client: LLMClient, spec: AttributeSpec, query: str) -> dict[str, Any]:
    """Ask the model which attribute slots a query fills.

    Mirrors ``GroundingPipeline._extract``, including raising on a non-object payload: a
    system that cannot emit parseable output is producing a real result about itself, and
    repairing it here would flatter it.
    """
    user = (
        "ATTRIBUTES:\n"
        + attribute_catalogue(spec)
        + f'\n\nCITIZEN\'S QUESTION:\n"{query}"'
    )
    payload = parse_json_response(client.complete(EXTRACTION_SYSTEM_PROMPT, user, json_mode=True))
    if not isinstance(payload, dict):
        raise ValueError(f"extractor returned {type(payload).__name__}, expected an object")
    return payload


def normalize_extraction(spec: AttributeSpec,
                         raw: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Canonicalize extracted values, discarding what cannot be normalized.

    Discarding is the right failure mode: an unparseable value means we do not know the
    attribute, which leaves the relevant schemes UNDETERMINED and sends the interview to
    ask about them. The citizen is questioned rather than misjudged.
    """
    profile: dict[str, Any] = {}
    rejected: list[str] = []
    for name, value in raw.items():
        if name not in spec or value is None:
            rejected.append(f"{name}={value!r} (not in vocabulary)")
            continue
        if spec[name].is_derived:
            rejected.append(f"{name}={value!r} (derived; recomputed from its source)")
            continue
        try:
            profile[name] = spec.canonicalize(name, value)
        except SchemaError as exc:
            rejected.append(f"{name}={value!r} ({exc})")
    profile.update(spec.derive(profile))
    return profile, rejected


def parse_answer(spec: AttributeSpec, attr_name: str, raw: str,
                 client: LLMClient | None = None) -> tuple[Any, str]:
    """Turn a free-text answer into a canonical value.

    Deterministic first: the vocabulary already carries Tamil and romanized aliases plus
    unit conversion, so most answers normalize with no model call at all. The model is the
    fallback for phrasings the alias table does not cover, which keeps the live path fast
    and keeps the model off the decision path.
    """
    try:
        return spec.canonicalize(attr_name, raw), "aliases"
    except SchemaError:
        pass
    if client is None:
        return None, "unparsed"
    attr = spec[attr_name]
    hint = (f"one of [{', '.join(str(v) for v in attr.domain or ())}]"
            if attr.type == "enum" else
            f"number in {attr.unit or 'units'}" if attr.type == "number" else "true/false")
    user = (
        f"ATTRIBUTE: {attr_name}\n"
        f"TYPE: {attr.type} ({hint})\n"
        f"MEANING: {attr.description.strip()}\n\n"
        f'CITIZEN\'S ANSWER: "{raw}"'
    )
    try:
        payload = parse_json_response(
            client.complete(NORMALIZE_SYSTEM_PROMPT, user, json_mode=True))
        value = payload.get("value") if isinstance(payload, dict) else None
        if value is None:
            return None, "model-said-unstated"
        return spec.canonicalize(attr_name, value), "model"
    except Exception as exc:  # noqa: BLE001 — an unreadable answer is a real outcome
        return None, f"unparsed ({type(exc).__name__})"


def next_question(active: SchemeKB, profile: Mapping[str, Any], asked: list[str],
                  skipped: set[str], *, max_questions: int = 15) -> str | None:
    """The highest-value attribute still worth asking, or ``None`` when done."""
    if len(asked) >= max_questions:
        return None
    if not active.match(profile)[Verdict.UNKNOWN]:
        return None
    for attr in question_priority(active, profile):
        if attr not in asked and attr not in skipped and profile.get(attr) is None:
            return attr
    return None


def apply_value(active: SchemeKB, spec: AttributeSpec, profile: dict[str, Any],
                attr: str, value: Any) -> int:
    """Write one answer into a profile and report how many schemes it settled."""
    before = len(active.match(profile)[Verdict.UNKNOWN])
    profile[attr] = value
    profile.update(spec.derive(profile))
    return before - len(active.match(profile)[Verdict.UNKNOWN])


def question_reason(active: SchemeKB, profile: Mapping[str, Any], attr: str) -> dict[str, Any]:
    """Why this question — how many schemes it could settle, and which."""
    settles = resolving_power(active, profile).get(attr, 0)
    return {"settles": settles}


# ---------------------------------------------------------------------------- engine


@dataclass
class Interview:
    """Drives an interview turn by turn against a fixed KB."""

    kb: SchemeKB
    spec: AttributeSpec
    client: LLMClient | None = None
    active: SchemeKB = field(init=False)

    def __post_init__(self) -> None:
        self.active = self.kb.active()

    # -- phase 1: read the sentence ------------------------------------------

    def start(self, query: str, *, max_questions: int = 15, use_ai: bool = True,
              seed_profile: Mapping[str, Any] | None = None) -> InterviewState:
        """Begin an interview, optionally from a saved profile.

        Seeded facts count as known, so ``next_question`` never asks for them — that is the
        whole point of saving a profile. They are marked ``saved`` so the page can show
        which answers came from memory. Facts the query states win over seeded ones: the
        sentence typed just now is newer than anything on file.
        """
        state = InterviewState(query=query, max_questions=max_questions)
        for name, value in (seed_profile or {}).items():
            if name in self.spec and not self.spec[name].is_derived and value is not None:
                state.profile[name] = value
                state.sources[name] = "saved"
        self._rederive(state)
        if not (use_ai and self.client is not None and query.strip()):
            return state

        started = time.time()
        try:
            state.raw_extraction = extract_attributes(self.client, self.spec, query)
            state.used_ai = True
        except Exception as exc:  # noqa: BLE001 — degrade to rules-only, never 500
            state.extraction_error = f"{type(exc).__name__}: {exc}"
            state.raw_extraction = {}
        state.extraction_ms = int((time.time() - started) * 1000)

        profile, rejected = normalize_extraction(self.spec, state.raw_extraction)
        for name, value in profile.items():
            if not self.spec[name].is_derived:
                state.profile[name] = value
                state.sources[name] = "query"
        state.rejected = rejected
        self._rederive(state)
        return state

    def _rederive(self, state: InterviewState) -> None:
        state.profile.update(self.spec.derive(state.profile))
        for name in state.profile:
            if self.spec[name].is_derived:
                state.sources[name] = "derived"

    # -- phase 2: the turn loop ----------------------------------------------

    def next_question(self, state: InterviewState) -> str | None:
        return next_question(self.active, state.profile, state.asked, state.skipped_set,
                             max_questions=state.max_questions)

    def _validate(self, attr: str) -> str | None:
        if attr not in self.spec:
            return f"unknown attribute {attr!r}"
        if self.spec[attr].is_derived:
            return f"{attr} is derived from other answers and cannot be answered directly"
        if not self.spec[attr].elicitable:
            return f"{attr} is not something a citizen can be asked"
        return None

    def _commit(self, state: InterviewState, attr: str, value: Any,
                source: str) -> AnswerOutcome:
        settled = apply_value(self.active, self.spec, state.profile, attr, value)
        state.sources[attr] = source
        for name in state.profile:
            state.sources.setdefault(name, "derived")
        if attr not in state.asked:
            state.asked.append(attr)
        state.history.append({
            "i": len(state.history) + 1,
            "attr": attr,
            "label": label_for(self.spec, attr),
            "value": value,
            "display": format_value(self.spec, attr, value),
            "source": source,
            "settled": settled,
        })
        return AnswerOutcome(attr=attr, value=value, source=source, accepted=True,
                             settled=settled)

    def answer_value(self, state: InterviewState, attr: str, value: Any) -> AnswerOutcome:
        """Answer from a typed control. Canonicalized, never sent to the model."""
        problem = self._validate(attr)
        if problem:
            return AnswerOutcome(attr=attr, source="rejected", message=problem)
        try:
            canonical = self.spec.canonicalize(attr, value)
        except SchemaError as exc:
            return AnswerOutcome(attr=attr, source="rejected", message=str(exc))
        if canonical is None:
            return self.skip(state, attr)
        return self._commit(state, attr, canonical, "form")

    def answer_text(self, state: InterviewState, attr: str, raw: str) -> AnswerOutcome:
        """Answer in free text — the path that accepts Tamil and improvised units."""
        problem = self._validate(attr)
        if problem:
            return AnswerOutcome(attr=attr, source="rejected", message=problem)

        value, source = parse_answer(self.spec, attr, raw, self.client)
        if value is not None:
            state.retries.pop(attr, None)
            return self._commit(state, attr, value, source)

        # Not understood. Leave the question open so it can be rephrased — but only twice,
        # then retire it, so one stubborn phrasing cannot stall the whole interview.
        state.retries[attr] = state.retries.get(attr, 0) + 1
        if state.retries[attr] >= MAX_RETRIES:
            outcome = self.skip(state, attr)
            outcome.source = source
            outcome.message = ("Still could not read that, so this question was skipped. "
                               "The schemes that needed it stay undetermined.")
            return outcome
        return AnswerOutcome(
            attr=attr, source=source,
            message="Could not read that answer. Rephrase it, pick a value, or skip.")

    def skip(self, state: InterviewState, attr: str) -> AnswerOutcome:
        if attr not in state.skipped:
            state.skipped.append(attr)
        if attr not in state.asked:
            state.asked.append(attr)
        state.history.append({
            "i": len(state.history) + 1,
            "attr": attr,
            "label": label_for(self.spec, attr),
            "value": None,
            "display": "skipped",
            "source": "skipped",
            "settled": 0,
        })
        return AnswerOutcome(attr=attr, source="skipped", accepted=True, settled=0)

    # -- phase 3: what the caller renders ------------------------------------

    def board(self, state: InterviewState) -> dict[str, Any]:
        return board(self.active, state.profile)

    def question_payload(self, state: InterviewState, attr: str) -> dict[str, Any]:
        payload = attribute_form(self.spec, attr)
        payload.update({
            "attr": attr,
            "index": len(state.asked) + 1,
            "why": question_reason(self.active, state.profile, attr),
        })
        return payload

    def progress(self, state: InterviewState) -> dict[str, Any]:
        return {"asked": len(state.asked), "max_questions": state.max_questions}

    def results(self, state: InterviewState) -> dict[str, Any]:
        """The final payload: verdicts, traces, near misses, and how we got there."""
        buckets = self.active.match(state.profile)
        eligible = []
        for scheme_id in buckets[Verdict.TRUE]:
            scheme = self.active[scheme_id]
            card = scheme_summary(scheme)
            card["trace"] = trace_to_dict(scheme.decide(state.profile), self.spec)
            card["eligibility_prose"] = scheme.eligibility_prose
            eligible.append(card)

        undetermined = []
        for scheme_id in buckets[Verdict.UNKNOWN]:
            scheme = self.active[scheme_id]
            trace = scheme.decide(state.profile)
            undetermined.append({
                "id": scheme.id,
                "name": scheme.name,
                "n_unknown": len(trace.unknown_predicates()),
            })

        return {
            "query": state.query,
            "counts": {
                "eligible": len(buckets[Verdict.TRUE]),
                "ineligible": len(buckets[Verdict.FALSE]),
                "undetermined": len(buckets[Verdict.UNKNOWN]),
            },
            "questions_asked": len(state.asked),
            "used_ai": state.used_ai,
            "eligible": eligible,
            "near_misses": near_misses(self.active, state.profile, self.spec),
            "undetermined": undetermined,
            "profile": profile_rows(self.spec, state.profile, state.sources),
            "transcript": state.history,
            "disclaimer": "KB is unverified draft data — demo only, not advice.",
        }
