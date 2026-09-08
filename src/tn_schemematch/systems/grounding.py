"""The structured eligibility-grounding pipeline: extract, normalize, elicit, evaluate.

The mechanism is not new — it is the extract-to-structure-then-solve pattern established
in clinical-trial patient matching (Criteria2Query and its successors, and the more
recent neurosymbolic variants). What is new here is where it is being asked to work: an
underspecified query in code-mixed Tamil-English, against Indian welfare rules.

The division of labour is the point. The model does one job — read a messy sentence and
say which attribute slots it fills. Everything after that is deterministic: units and
category labels are canonicalized by the normalizer, missing attributes are chosen by a
transparent policy, and the eligibility decision is a rule evaluation that can be printed
and audited. The model never gets to assert that someone qualifies.

Two consequences follow, and both should be stated in the paper rather than left for a
reviewer to notice:

1. The pipeline's errors are almost entirely *extraction* errors. If it says a farmer
   with 2 acres qualifies for something they do not, the mistake was reading "rendu
   ekkar" as 20 acres, not misapplying the ceiling. That is a strictly easier failure to
   diagnose and fix than a reasoning error — which is much of the argument for RQ3.

2. Its elicitation scores measure a hand-written policy, not the model, so they are near
   the oracle by construction and are not comparable to the agent systems' scores as
   evidence about model ability. They belong in the table as a reference row, labelled as
   such. What *is* comparable is the RQ2 question: whether extraction quality — and so
   the whole pipeline — degrades under code-mixing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .. import DEFAULT_QUESTION_BUDGET
from ..attributes import SchemaError
from ..elicitation import question_priority
from ..kb import SchemeKB
from ..personas import Persona
from ..rules import Verdict
from .base import (
    LLMClient,
    MatchResult,
    SimulatedCitizen,
    attribute_catalogue,
    parse_json_response,
    timed,
)

EXTRACTION_SYSTEM_PROMPT = """\
You extract structured facts from a citizen's question about Indian government welfare \
schemes. The question may be written in code-mixed Tamil and English, in Tamil script, \
in romanized Tamil, or in English.

You will be given a list of attributes. Return ONLY the attributes the question actually \
states or unambiguously implies. Do not guess, do not infer from stereotypes, and do not \
fill in what a typical person might answer. Leaving an attribute out is correct and \
expected; inventing one is not.

Keep quantities in the words the citizen used — write "2 ekkar" or "80 cent" or "month-ku \
8000" rather than converting them. Conversion happens downstream.

Reply with JSON only: {"attribute_name": value, ...}. Use an empty object {} if the \
question states nothing."""


@dataclass
class GroundingPipeline:
    """Extract attributes with a model, then decide with rules."""

    client: LLMClient
    kb: SchemeKB
    # Raised from 20 to 40 when the KB grew from 10 schemes to 41. The budget is not a
    # free parameter: it has to cover the *minimal confirming* question set, which grows
    # with the number of schemes a person might plausibly qualify for. On the seed personas
    # that set runs to 20 questions at 41 schemes against 8 at 10 schemes, the greedy policy needs
    # about twice that to get there, and a budget of
    # 20 silently truncated the interview and dropped schemes people qualified for. That
    # scaling is itself a result worth reporting, and it is the reason the elicitation
    # metrics are ratios against the oracle rather than raw counts.
    max_questions: int = DEFAULT_QUESTION_BUDGET
    # Ask one question at a time and re-rank after each answer. Batching is tempting for a
    # UI, but every answer changes which question is most informative next: on the seed
    # personas, batches of three cost enough wasted questions to lose a scheme the citizen
    # genuinely qualified for within a fixed budget, while one-at-a-time reached the
    # correct answer for all of them.
    ask_batch_size: int = 1
    name: str = "grounding"

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        active = kb.active()
        query = persona.query(condition)
        result = MatchResult(
            persona_id=persona.id,
            condition=condition,
            system=self.name,
            model=getattr(self.client, "name", "unknown"),
            retrieved=active.ids(),  # every scheme is evaluated; nothing is filtered out first
        )
        citizen = SimulatedCitizen(persona, kb.spec, max_questions=self.max_questions)

        with timed() as clock:
            try:
                # 1. Extract ------------------------------------------------
                raw_extraction = self._extract(query, kb)
                result.transcript.append({"role": "extractor", "text": json.dumps(raw_extraction,
                                                                                 ensure_ascii=False)})

                # 2. Normalize ----------------------------------------------
                profile, rejected = self._normalize(raw_extraction, kb)
                result.extracted_profile = dict(profile)
                if rejected:
                    result.transcript.append(
                        {"role": "harness", "text": f"unnormalizable extractions: {rejected}"}
                    )

                # 3. Elicit -------------------------------------------------
                while not citizen.exhausted:
                    outstanding = active.match(profile)[Verdict.UNKNOWN]
                    if not outstanding:
                        break
                    to_ask = [
                        attr for attr in question_priority(active, profile)
                        if attr not in citizen.asked and profile.get(attr) is None
                    ][: self.ask_batch_size]
                    if not to_ask:
                        break
                    for attr in to_ask:
                        reply, value = citizen.answer(attr)
                        result.questions_asked.append(attr)
                        result.transcript.append({"role": "citizen", "text": f"{attr}: {reply}"})
                        if value is not None:
                            profile[attr] = value
                    profile.update(kb.spec.derive(profile))

                # 4. Evaluate -----------------------------------------------
                result.final_profile = dict(profile)
                result.returned = active.eligible_ids(profile)
                still_open = active.match(profile)[Verdict.UNKNOWN]
                if still_open:
                    result.transcript.append(
                        {"role": "harness",
                         "text": f"still undetermined at answer time (reported as not eligible): "
                                 f"{still_open}"}
                    )
            except Exception as exc:  # noqa: BLE001 — a failed run is a recorded result
                result.error = f"{type(exc).__name__}: {exc}"

        result.latency_s = clock.elapsed
        return result

    # -- steps --------------------------------------------------------------

    def _extract(self, query: str, kb: SchemeKB) -> dict[str, Any]:
        user = (
            "ATTRIBUTES:\n"
            + attribute_catalogue(kb.spec)
            + f'\n\nCITIZEN\'S QUESTION:\n"{query}"'
        )
        raw = self.client.complete(EXTRACTION_SYSTEM_PROMPT, user, json_mode=True)
        payload = parse_json_response(raw)
        if not isinstance(payload, dict):
            raise ValueError(f"extractor returned {type(payload).__name__}, expected an object")
        return payload

    def _normalize(self, raw: dict[str, Any], kb: SchemeKB) -> tuple[dict[str, Any], list[str]]:
        """Canonicalize extracted values, discarding what cannot be normalized.

        Discarding is the right failure mode. An unparseable value means we do not know
        the attribute, which leaves the relevant schemes UNDETERMINED and sends the
        pipeline to ask about them — the citizen is questioned rather than misjudged.
        """
        profile: dict[str, Any] = {}
        rejected: list[str] = []
        for name, value in raw.items():
            if name not in kb.spec or value is None:
                rejected.append(f"{name}={value!r} (not in vocabulary)")
                continue
            if kb.spec[name].is_derived:
                rejected.append(f"{name}={value!r} (derived; recomputed from its source)")
                continue
            try:
                profile[name] = kb.spec.canonicalize(name, value)
            except SchemaError as exc:
                rejected.append(f"{name}={value!r} ({exc})")
        profile.update(kb.spec.derive(profile))
        return profile, rejected


# -------------------------------------------------------- diagnostic: no extractor


@dataclass
class OracleExtractionPipeline:
    """Grounding pipeline with extraction replaced by the persona's annotated facts.

    This is the ceiling: if it still makes mistakes, the fault is in the rule KB rather
    than in the model. Running it beside the real pipeline splits the grounding system's
    error into an extraction share and a KB share, which is the difference between "the
    model misread the query" and "we encoded the scheme wrongly" — and only one of those
    is a finding about models.
    """

    kb: SchemeKB
    # Raised from 20 to 40 when the KB grew from 10 schemes to 41. The budget is not a
    # free parameter: it has to cover the *minimal confirming* question set, which grows
    # with the number of schemes a person might plausibly qualify for. On the seed personas
    # that set runs to 20 questions at 41 schemes against 8 at 10 schemes, the greedy policy needs
    # about twice that to get there, and a budget of
    # 20 silently truncated the interview and dropped schemes people qualified for. That
    # scaling is itself a result worth reporting, and it is the reason the elicitation
    # metrics are ratios against the oracle rather than raw counts.
    max_questions: int = DEFAULT_QUESTION_BUDGET
    # Ask one question at a time and re-rank after each answer. Batching is tempting for a
    # UI, but every answer changes which question is most informative next: on the seed
    # personas, batches of three cost enough wasted questions to lose a scheme the citizen
    # genuinely qualified for within a fixed budget, while one-at-a-time reached the
    # correct answer for all of them.
    ask_batch_size: int = 1
    name: str = "grounding[oracle_extraction]"

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        active = kb.active()
        result = MatchResult(
            persona_id=persona.id,
            condition=condition,
            system=self.name,
            model="none",
            retrieved=active.ids(),
        )
        citizen = SimulatedCitizen(persona, kb.spec, max_questions=self.max_questions)

        with timed() as clock:
            profile = dict(persona.known_profile())
            profile.update(kb.spec.derive(profile))
            result.extracted_profile = dict(profile)

            while not citizen.exhausted and active.match(profile)[Verdict.UNKNOWN]:
                to_ask = [
                    attr for attr in question_priority(active, profile)
                    if attr not in citizen.asked and profile.get(attr) is None
                ][: self.ask_batch_size]
                if not to_ask:
                    break
                for attr in to_ask:
                    _, value = citizen.answer(attr)
                    result.questions_asked.append(attr)
                    if value is not None:
                        profile[attr] = value
                profile.update(kb.spec.derive(profile))

            result.final_profile = dict(profile)
            result.returned = active.eligible_ids(profile)

        result.latency_s = clock.elapsed
        return result
