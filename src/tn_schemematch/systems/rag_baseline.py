"""The RAG baseline: retrieve scheme prose, let the model decide from it.

This is the shape of essentially every deployed "scheme discovery" assistant, and it is
the condition RQ3 argues against. The model sees the real eligibility wording — nothing
is withheld — and must apply it to an underspecified citizen query. It may ask for
missing attributes first, using the same vocabulary the grounding pipeline uses, so that
elicitation is measured on equal terms.

``DirectSystem`` is the no-retrieval arm: the model sees only the scheme names and
answers from parametric knowledge. It is worth running because a system that scores well
here is telling you the KB's contents are already memorised, which changes how you read
every other number in the table.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..kb import SchemeKB
from ..personas import Persona
from .base import (
    LLMClient,
    MatchResult,
    SimulatedCitizen,
    attribute_catalogue,
    coerce_scheme_ids,
    parse_json_response,
    scheme_catalogue,
    timed,
)
from .retrieval import BM25Retriever

SYSTEM_PROMPT = """\
You are helping a citizen of Tamil Nadu, India find out which government welfare schemes \
they qualify for. You will be shown the official text of some schemes, including their \
eligibility conditions, and the citizen's question. The question may be written in \
code-mixed Tamil and English.

Decide which of the shown schemes this citizen QUALIFIES FOR. Being relevant to their \
situation is not enough — every eligibility condition must actually be met.

If you need facts about the citizen that the question does not give you, ask for them \
before answering. Ask only for what could change your answer.

Reply with JSON only, in this form:
{"questions": ["attribute_name", ...], "eligible_schemes": ["scheme_id", ...], "reasoning": "..."}

Use attribute names from the list you are given for "questions", and scheme ids for \
"eligible_schemes". When you are ready to answer, return an empty "questions" list. If \
the citizen qualifies for nothing, return an empty "eligible_schemes" list — that is a \
valid and useful answer."""


class Retriever(Protocol):
    name: str

    def retrieve(self, query: str, k: int = 8) -> list[str]:
        ...


@dataclass
class RAGBaseline:
    """Retrieve-then-decide over scheme prose."""

    client: LLMClient
    kb: SchemeKB
    retriever: Retriever | None = None
    top_k: int = 8
    max_rounds: int = 4
    max_questions: int = 15
    name: str = "rag"

    def __post_init__(self) -> None:
        if self.retriever is None:
            self.retriever = BM25Retriever(self.kb)
        self.name = f"rag[{self.retriever.name},k={self.top_k}]"

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        query = persona.query(condition)
        result = MatchResult(
            persona_id=persona.id,
            condition=condition,
            system=self.name,
            model=getattr(self.client, "name", "unknown"),
        )
        citizen = SimulatedCitizen(persona, kb.spec, max_questions=self.max_questions)

        with timed() as clock:
            try:
                retrieved = self.retriever.retrieve(query, self.top_k)  # type: ignore[union-attr]
                result.retrieved = retrieved
                passages = "\n\n".join(kb[s].retrieval_text() for s in retrieved)
                known: list[str] = []

                for round_index in range(self.max_rounds):
                    user = _build_prompt(query, passages, kb.spec, known)
                    raw = self.client.complete(SYSTEM_PROMPT, user, json_mode=True)
                    result.transcript.append({"role": "model", "round": str(round_index), "text": raw})
                    payload = parse_json_response(raw)
                    if not isinstance(payload, dict):
                        raise ValueError(f"expected a JSON object, got {type(payload).__name__}")

                    questions = [str(q) for q in (payload.get("questions") or [])]
                    if questions and round_index < self.max_rounds - 1 and not citizen.exhausted:
                        for attr in questions:
                            reply, _ = citizen.answer(attr)
                            known.append(f"{attr}: {reply}")
                            result.questions_asked.append(attr)
                        continue

                    recognised, hallucinated = coerce_scheme_ids(
                        payload.get("eligible_schemes"), kb
                    )
                    result.returned = recognised
                    if hallucinated:
                        result.transcript.append(
                            {"role": "harness", "text": f"unrecognised scheme names: {hallucinated}"}
                        )
                    break
            except Exception as exc:  # noqa: BLE001 — a failed run is a recorded result
                result.error = f"{type(exc).__name__}: {exc}"

        result.latency_s = clock.elapsed
        return result


def _build_prompt(query: str, passages: str, spec: Any, known: list[str]) -> str:
    parts = [
        "SCHEMES:",
        passages,
        "",
        "ATTRIBUTES YOU MAY ASK ABOUT:",
        attribute_catalogue(spec),
        "",
        f'CITIZEN\'S QUESTION:\n"{query}"',
    ]
    if known:
        parts += ["", "ANSWERS THE CITIZEN HAS ALREADY GIVEN:", "\n".join(known)]
    return "\n".join(parts)


# ------------------------------------------------------------------ no retrieval


DIRECT_SYSTEM_PROMPT = """\
You are helping a citizen of Tamil Nadu, India find out which government welfare schemes \
they qualify for. You will be shown a list of scheme names and one-line summaries, but \
not their eligibility rules — use what you know about these schemes.

Decide which schemes this citizen QUALIFIES FOR, not merely which are topically related. \
You may ask for citizen attributes you need first.

Reply with JSON only:
{"questions": ["attribute_name", ...], "eligible_schemes": ["scheme_id", ...], "reasoning": "..."}"""


@dataclass
class DirectSystem:
    """No retrieval, no rules: the model answers from what it already knows."""

    client: LLMClient
    kb: SchemeKB
    max_rounds: int = 4
    max_questions: int = 15
    name: str = "direct"

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        query = persona.query(condition)
        result = MatchResult(
            persona_id=persona.id,
            condition=condition,
            system=self.name,
            model=getattr(self.client, "name", "unknown"),
            retrieved=kb.ids(),
        )
        citizen = SimulatedCitizen(persona, kb.spec, max_questions=self.max_questions)

        with timed() as clock:
            try:
                known: list[str] = []
                catalogue = scheme_catalogue(kb)
                for round_index in range(self.max_rounds):
                    user = _build_prompt(query, catalogue, kb.spec, known)
                    raw = self.client.complete(DIRECT_SYSTEM_PROMPT, user, json_mode=True)
                    result.transcript.append({"role": "model", "round": str(round_index), "text": raw})
                    payload = parse_json_response(raw)
                    questions = [str(q) for q in (payload.get("questions") or [])]
                    if questions and round_index < self.max_rounds - 1 and not citizen.exhausted:
                        for attr in questions:
                            reply, _ = citizen.answer(attr)
                            known.append(f"{attr}: {reply}")
                            result.questions_asked.append(attr)
                        continue
                    result.returned, _ = coerce_scheme_ids(payload.get("eligible_schemes"), kb)
                    break
            except Exception as exc:  # noqa: BLE001
                result.error = f"{type(exc).__name__}: {exc}"

        result.latency_s = clock.elapsed
        return result
