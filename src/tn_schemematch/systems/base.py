"""Common interface for the systems under test, plus the simulated citizen.

Both systems answer the same question — "which schemes does this person qualify for?" —
and both may ask the citizen for missing attributes before answering. Holding the
interface identical is what makes the RAG-versus-grounding comparison mean anything:
the two differ in how they represent eligibility, not in what they are allowed to do.

The citizen is simulated from the persona's full profile. Real elicitation studies need
real people, and this is not a substitute for one; it is a way to run a multi-turn
protocol reproducibly across models and language conditions. The simulation is
deliberately literal — it answers exactly what was asked and volunteers nothing — so
that a system cannot score well on elicitation by accident.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol, runtime_checkable

from .. import DEFAULT_QUESTION_BUDGET
from ..attributes import AttributeSpec
from ..kb import SchemeKB
from ..personas import Persona


# ------------------------------------------------------------------- LLM backend


@runtime_checkable
class LLMClient(Protocol):
    """Minimal backend interface. Implement this to plug in a model."""

    name: str

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        """Return the model's completion for a system + user prompt pair."""
        ...


@dataclass
class ScriptedClient:
    """Offline client that replays canned responses, keyed by substring of the prompt.

    Exists so the whole harness — prompts, parsing, elicitation loop, scoring — can be
    exercised in CI with no API key and no nondeterminism. Tests that depend on a live
    model test the model, not the code.
    """

    responses: dict[str, str] = field(default_factory=dict)
    default: str = "{}"
    name: str = "scripted"
    calls: list[tuple[str, str]] = field(default_factory=list)
    # Agent turns, consumed in order by ``converse``: each is
    # {"stop_reason": ..., "content": [{"type": "text" | "tool_use", ...}, ...]}.
    turns: list[dict[str, Any]] = field(default_factory=list)
    image_calls: list[dict[str, Any]] = field(default_factory=list)
    conversations: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.calls.append((system, user))
        for key, response in self.responses.items():
            if key in user:
                return response
        return self.default

    def complete_with_images(self, system: str, user: str, images, *,
                             schema: dict[str, Any] | None = None,
                             effort: str | None = None) -> str:
        self.image_calls.append({"system": system, "user": user, "schema": schema,
                                 "media_types": [media for media, _ in images]})
        return self.complete(system, user, json_mode=True)

    def converse(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]], *, effort: str | None = None) -> "ScriptedMessage":
        # Snapshot, because the caller keeps appending to the same list.
        self.conversations.append({"system": system, "messages": json.loads(json.dumps(
            messages, default=str)), "tools": [t["name"] for t in tools]})
        turn = self.turns.pop(0) if self.turns else {
            "stop_reason": "end_turn", "content": [{"type": "text", "text": self.default}]}
        return ScriptedMessage(turn["stop_reason"],
                               [ScriptedBlock(dict(block)) for block in turn["content"]])


class ScriptedBlock:
    """A content block shaped like the SDK's: attribute access plus ``to_dict``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name) from None

    def to_dict(self, **_: Any) -> dict[str, Any]:
        return dict(self._data)


@dataclass
class ScriptedMessage:
    stop_reason: str
    content: list[ScriptedBlock]


# ------------------------------------------------------------------ result record


@dataclass
class MatchResult:
    """Everything one system produced for one persona in one language condition."""

    persona_id: str
    condition: str
    system: str
    model: str = ""
    returned: list[str] = field(default_factory=list)
    questions_asked: list[str] = field(default_factory=list)
    retrieved: list[str] = field(default_factory=list)
    extracted_profile: dict[str, Any] = field(default_factory=dict)
    final_profile: dict[str, Any] = field(default_factory=dict)
    transcript: list[dict[str, str]] = field(default_factory=list)
    latency_s: float = 0.0
    error: str = ""

    @property
    def failed(self) -> bool:
        return bool(self.error)

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona_id": self.persona_id,
            "condition": self.condition,
            "system": self.system,
            "model": self.model,
            "returned": self.returned,
            "questions_asked": self.questions_asked,
            "retrieved": self.retrieved,
            "extracted_profile": self.extracted_profile,
            "final_profile": self.final_profile,
            "transcript": self.transcript,
            "latency_s": round(self.latency_s, 3),
            "error": self.error,
        }


class MatchSystem(Protocol):
    """A system under test."""

    name: str

    def run(self, persona: Persona, condition: str, kb: SchemeKB) -> MatchResult:
        ...


# --------------------------------------------------------------- simulated citizen


@dataclass
class SimulatedCitizen:
    """Answers questions about one persona, truthfully and only when asked."""

    persona: Persona
    spec: AttributeSpec
    max_questions: int = DEFAULT_QUESTION_BUDGET
    asked: list[str] = field(default_factory=list)

    @property
    def exhausted(self) -> bool:
        return len(self.asked) >= self.max_questions

    def answer(self, attr: str) -> tuple[str, Any]:
        """Answer a question about ``attr``. Returns (natural-language reply, value)."""
        self.asked.append(attr)
        if attr not in self.spec:
            return (f"I don't understand what '{attr}' means.", None)
        if not self.spec[attr].elicitable:
            return (
                f"That's not something I would know — {attr} is worked out from other details.",
                None,
            )
        value = self.persona.profile.get(attr)
        if value is None:
            return ("I don't know that.", None)
        return (_verbalize(attr, value, self.spec), value)


def _verbalize(attr: str, value: Any, spec: AttributeSpec) -> str:
    """Render an answer the way a person would say it, not as a JSON field."""
    attribute = spec[attr]
    if attribute.type == "bool":
        return "Yes." if value else "No."
    if attribute.type == "number":
        pretty = int(value) if float(value).is_integer() else round(float(value), 2)
        unit = {"INR_per_year": "rupees a year", "INR_per_month": "rupees a month",
                "acres": "acres", "years": "years", "percent": "percent",
                "persons": "people", "units_per_year": "units a year",
                "INR": "rupees"}.get(attribute.unit or "", "")
        return f"{pretty} {unit}".strip() + "."
    return f"{str(value).replace('_', ' ')}."


# ------------------------------------------------------------------ shared helpers


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_response(text: str) -> Any:
    """Pull a JSON object out of a model response, tolerating fenced code blocks.

    Parse failures raise, and the caller records the failure as an error rather than
    retrying or repairing. A system that cannot emit parseable output is producing a
    real result about itself, and silently patching it around would flatter it.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty response")
    match = _JSON_BLOCK.search(text)
    if match:
        text = match.group(1).strip()
    else:
        start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
        if start > 0:
            text = text[start:]
    return json.loads(text)


def scheme_catalogue(kb: SchemeKB, ids: Iterable[str] | None = None) -> str:
    """The scheme list shown to a model, as id + name + one-line summary."""
    chosen = list(ids) if ids is not None else kb.ids()
    lines = []
    for scheme_id in chosen:
        scheme = kb[scheme_id]
        lines.append(f"- {scheme.id}: {scheme.name} — {scheme.summary.strip()}")
    return "\n".join(lines)


def attribute_catalogue(spec: AttributeSpec) -> str:
    """The elicitable attribute vocabulary, rendered for a prompt."""
    lines = []
    for name in spec.elicitable_names():
        attr = spec[name]
        if attr.type == "enum":
            kind = f"one of [{', '.join(str(v) for v in attr.domain or ())}]"
        elif attr.type == "number":
            kind = f"number in {attr.unit or 'units'}"
        else:
            kind = "true/false"
        lines.append(f"- {name} ({kind}): {attr.description.strip().splitlines()[0]}")
    return "\n".join(lines)


def timed() -> "Timer":
    return Timer()


class Timer:
    def __enter__(self) -> "Timer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed = time.perf_counter() - self._start

    elapsed: float = 0.0


def coerce_scheme_ids(raw: Any, kb: SchemeKB) -> tuple[list[str], list[str]]:
    """Map whatever the model returned onto known scheme ids.

    Returns (recognised ids, unrecognised strings). Hallucinated scheme names are kept
    and reported rather than dropped: inventing a scheme is itself a false positive with
    a real cost, and a harness that silently discards them under-reports harm.
    """
    if isinstance(raw, Mapping):
        raw = raw.get("eligible_schemes") or raw.get("schemes") or raw.get("returned") or []
    if isinstance(raw, str):
        raw = [raw]
    recognised: list[str] = []
    unknown: list[str] = []
    by_name = {kb[s].name.casefold(): s for s in kb.ids()}
    for item in raw or []:
        if isinstance(item, Mapping):
            item = item.get("id") or item.get("scheme_id") or item.get("name") or ""
        key = str(item).strip()
        if key in kb:
            recognised.append(key)
        elif key.casefold() in by_name:
            recognised.append(by_name[key.casefold()])
        elif key:
            unknown.append(key)
    return sorted(set(recognised)), sorted(set(unknown))
