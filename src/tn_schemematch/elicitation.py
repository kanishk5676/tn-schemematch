"""Which questions actually matter — the ground truth for elicitation efficiency.

An agent facing "enakku ration card irukku, farmer, 2 acre land — enna scheme
kedaikum?" has two bad options and one good one. It can answer immediately from
three attributes (fast, and wrong). It can interrogate the citizen through all
thirty-odd attributes in the vocabulary (correct, and unusable). Or it can ask only
the questions whose answers can still change the outcome. This module defines that
third set precisely, so "did the agent ask well?" becomes a measurable quantity
rather than a judgement call.

Two definitions do the work:

**Pivotal.** Attribute *a* is pivotal for scheme *s* under partial profile *p* if
some value of *a* changes *s*'s verdict. Only UNDETERMINED schemes can have pivotal
attributes: Kleene evaluation is monotone in the information ordering, so once a
scheme is settled, learning more never unsettles it (:func:`assert_monotone` checks
this empirically over the KB).

**Oracle question sequence.** Given the persona's true full profile, the greedy
sequence of questions that settles every scheme in the fewest steps. This is the
denominator for question overhead — how much more the agent asked than it needed to.

Searching over values is cheap because rules are built from comparisons: an
enum or bool attribute is probed over its whole domain, and a numeric attribute only
at the thresholds the rules themselves mention (just below, at, and just above each),
since behaviour cannot change anywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .attributes import AttributeSpec
from .kb import Scheme, SchemeKB
from .rules import Node, Predicate, Verdict, numeric_boundaries, referenced_attributes

__all__ = [
    "candidate_values",
    "is_pivotal",
    "pivotal_attributes",
    "necessary_questions",
    "immediately_pivotal_questions",
    "resolving_power",
    "oracle_question_sequence",
    "minimal_confirming_questions",
    "ElicitationGround",
    "ground_truth",
    "assert_monotone",
]

_EPSILON = 1e-6


# ---------------------------------------------------------------- value probing


def candidate_values(rule: Node, attr: str, spec: AttributeSpec) -> list[Any]:
    """Values worth testing for ``attr`` when probing ``rule``.

    Booleans get both values. Numeric attributes get the domain endpoints plus a triple
    around each threshold the rule mentions — enough to cross every comparison boundary
    in either direction.

    Enums get the values the rule actually names, plus one witness standing for all the
    rest. That reduction is **exact, not a heuristic**: an enum admits only
    ``eq``/``ne``/``in``/``not_in`` — ordering operators are rejected at parse time — so
    every predicate's verdict is a function of membership in its value set, and two
    values that no predicate names are indistinguishable to the rule. Probing one of them
    settles the question for all of them.

    This is what keeps pivotality flat as the ``state`` domain grows with the KB. Probing
    the full domain would make every state-scoped scheme cost one evaluation per state in
    the country, for information that is the same every time.
    """
    attribute = spec[attr]
    if attribute.type == "bool":
        return list(attribute.values())

    if attribute.type == "enum":
        domain = list(attribute.values())
        referenced: set[Any] = set()
        for node in rule.walk():
            if isinstance(node, Predicate) and node.attr == attr and node.value is not None:
                referenced |= (set(node.value) if isinstance(node.value, (list, tuple))
                               else {node.value})
        named = [v for v in domain if v in referenced]
        rest = [v for v in domain if v not in referenced]
        return named + rest[:1]

    lo, hi = attribute.domain or (0.0, 1.0)
    probes: set[float] = {float(lo), float(hi)}
    for bound in numeric_boundaries(rule, attr):
        for value in (bound - _EPSILON, bound, bound + _EPSILON):
            if lo <= value <= hi:
                probes.add(round(value, 9))
    return sorted(probes)


# ------------------------------------------------------------------- pivotality


def is_pivotal(scheme: Scheme, profile: Mapping[str, Any], attr: str, spec: AttributeSpec) -> bool:
    """Can learning ``attr`` change this scheme's verdict right now?"""
    if profile.get(attr) is not None:
        return False  # already known
    if attr not in scheme.attributes:
        return False  # rule never reads it
    current = scheme.verdict(profile)
    if current is not Verdict.UNKNOWN:
        return False  # settled verdicts are stable under further information
    for value in candidate_values(scheme.eligibility, attr, spec):
        probe = dict(profile)
        probe[attr] = value
        probe.update(spec.derive(probe))
        if scheme.verdict(probe) is not current:
            return True
    return False


def pivotal_attributes(scheme: Scheme, profile: Mapping[str, Any], spec: AttributeSpec) -> set[str]:
    """Every attribute whose answer could still settle ``scheme``."""
    if scheme.verdict(profile) is not Verdict.UNKNOWN:
        return set()
    return {
        attr for attr in referenced_attributes(scheme.eligibility)
        if spec[attr].elicitable and is_pivotal(scheme, profile, attr, spec)
    }


def immediately_pivotal_questions(kb: SchemeKB, profile: Mapping[str, Any]) -> set[str]:
    """Attributes that could settle some scheme *on their own, right now*.

    Narrower than :func:`necessary_questions`, and the right basis for choosing the next
    question — but the wrong basis for judging whether a question was legitimate.
    """
    out: set[str] = set()
    for scheme in kb:
        out |= pivotal_attributes(scheme, profile, kb.spec)
    return out


def necessary_questions(kb: SchemeKB, profile: Mapping[str, Any]) -> set[str]:
    """The attributes an agent is *entitled* to ask about, given what it knows.

    An attribute qualifies if some still-undetermined scheme has a still-undetermined
    clause that reads it. Anything outside this set is wasted burden on the citizen: no
    answer to it can change which schemes they qualify for.

    This is deliberately broader than "could flip a verdict single-handedly". Consider
    PM-KISAN's carve-out for Class IV staff: while employment status is unknown, asking
    whether someone is Class IV cannot settle anything by itself, so a one-attribute
    probe finds it irrelevant. Two questions later it is decisive. Scoring the agent
    against the narrow set would penalise it for asking a question that a competent
    caseworker asks — so the narrow set drives the greedy *policy*, and this broader one
    defines the *legitimacy* bar that question precision is measured against.
    """
    out: set[str] = set()
    for scheme in kb:
        if scheme.verdict(profile) is not Verdict.UNKNOWN:
            continue
        trace = scheme.decide(profile)
        for predicate in trace.unknown_predicates():
            if kb.spec[predicate.attr].elicitable and profile.get(predicate.attr) is None:
                out.add(predicate.attr)
    return out


def resolving_power(kb: SchemeKB, profile: Mapping[str, Any]) -> dict[str, int]:
    """attribute -> how many undetermined schemes it could settle right now."""
    counts: dict[str, int] = {}
    for scheme in kb:
        for attr in pivotal_attributes(scheme, profile, kb.spec):
            counts[attr] = counts.get(attr, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def question_priority(kb: SchemeKB, profile: Mapping[str, Any]) -> list[str]:
    """Order the questions worth asking, nearest-to-confirmation first.

    Ranking purely by :func:`resolving_power` — "how many schemes would this settle?" —
    optimizes the wrong objective. Settling a scheme usually means *ruling it out*, and
    ruling things out changes nothing about the answer, because an undetermined scheme is
    reported as not-eligible anyway. Under a realistic question budget that policy spends
    its questions on irrelevancies: on the seed set it needed twenty questions for a
    persona whose answer required about nine, and truncating at fifteen dropped a scheme
    she genuinely qualified for.

    So the primary key is instead how close each scheme is to being *confirmed* — the
    number of its clauses still unknown. Attributes belonging to a scheme two answers from
    a positive verdict come before attributes belonging to one that needs eight. Ties break
    by resolving power, then by how intrusive the question is, then by name for
    reproducibility.
    """
    spec = kb.spec
    power = resolving_power(kb, profile)
    best: dict[str, tuple[int, int, int, str]] = {}

    for scheme in kb:
        if scheme.verdict(profile) is not Verdict.UNKNOWN:
            continue
        unknown = {
            predicate.attr
            for predicate in scheme.decide(profile).unknown_predicates()
            if spec[predicate.attr].elicitable and profile.get(predicate.attr) is None
        }
        distance = len(unknown)
        for attr in unknown:
            key = (distance, -power.get(attr, 0), _ask_cost(spec, attr), attr)
            if attr not in best or key < best[attr]:
                best[attr] = key

    return [attr for attr, _ in sorted(best.items(), key=lambda item: item[1])]


# ------------------------------------------------------------ oracle question set


def oracle_question_sequence(
    kb: SchemeKB,
    known: Mapping[str, Any],
    full_profile: Mapping[str, Any],
    *,
    max_questions: int | None = None,
) -> list[str]:
    """Greedy shortest sequence of questions that settles every scheme.

    Uses the persona's true answers, so this is an oracle: it is the *benchmark's*
    notion of "how few questions were needed", not something a system could compute.
    Greedy set-cover is not guaranteed optimal, so treat the result as an upper bound
    on the true minimum — which keeps the reported overhead ratio conservative.
    """
    spec = kb.spec
    state = dict(known)
    asked: list[str] = []

    # The cap is a safety stop, not a policy. Pinned at a literal it silently truncates
    # once the KB grows past what that number covers, and a truncated oracle sequence
    # does not fail — it just makes `oracle_n_questions` saturate, which quietly turns
    # the denominator of the reported question-overhead ratio into a lie. Bounding it by
    # the vocabulary instead means it can only bind when a sequence would repeat itself,
    # which cannot happen: every iteration consumes one previously-unasked attribute.
    if max_questions is None:
        max_questions = len(spec.elicitable_names())

    settled_target = {s.id for s in kb if s.verdict(full_profile) is not Verdict.UNKNOWN}

    for _ in range(max_questions):
        outstanding = [
            s for s in kb
            if s.id in settled_target and s.verdict(state) is Verdict.UNKNOWN
        ]
        if not outstanding:
            break

        powers = resolving_power(SchemeKB({s.id: s for s in outstanding}, spec), state)
        # Only ask about attributes the persona can actually answer.
        answerable = {a: n for a, n in powers.items() if full_profile.get(a) is not None}
        if not answerable:
            break

        best = max(answerable.items(), key=lambda kv: (kv[1], -_ask_cost(spec, kv[0]), kv[0]))[0]
        asked.append(best)
        state[best] = full_profile[best]
        state.update(spec.derive(state))

    return asked


def _ask_cost(spec: AttributeSpec, attr: str) -> int:
    """Tie-breaker: prefer low-sensitivity questions when two resolve equally many schemes."""
    return {"low": 0, "medium": 1, "high": 2}.get(spec[attr].sensitivity, 1)


def minimal_confirming_questions(
    kb: SchemeKB, known: Mapping[str, Any], full_profile: Mapping[str, Any]
) -> list[str]:
    """The fewest questions needed to produce the *correct answer* — a different target.

    :func:`oracle_question_sequence` asks enough to settle every scheme in the KB, which
    on even a ten-scheme KB runs to a dozen questions and would be an absurd thing to put
    a citizen through. But settling everything is not what the task requires. Schemes that
    remain UNDETERMINED are reported as not-eligible, which is already the right output for
    all the ones the person does not qualify for. What must actually be established is the
    positive set: enough to make each *genuinely eligible* scheme evaluate TRUE.

    So this is the operational target, and it is much smaller. It is computed by taking the
    attributes each eligible scheme still needs and then removing, one at a time, any whose
    absence does not break the confirmation — a delta-debugging pass, greedy and therefore
    an upper bound on the true minimum.

    Report both: the gap between them is itself a result about how much of an eligibility
    interview is spent ruling things out rather than ruling them in.
    """
    spec = kb.spec
    target = [s for s in kb if s.verdict(full_profile) is Verdict.TRUE]
    if not target:
        return []

    needed: set[str] = set()
    for scheme in target:
        for attr in referenced_attributes(scheme.eligibility):
            if known.get(attr) is None and full_profile.get(attr) is not None and spec[attr].elicitable:
                needed.add(attr)

    def confirms_all(attrs: set[str]) -> bool:
        probe = dict(known)
        for attr in attrs:
            probe[attr] = full_profile[attr]
        probe.update(spec.derive(probe))
        return all(s.verdict(probe) is Verdict.TRUE for s in target)

    if not confirms_all(needed):
        # A derived attribute or an unanswerable slot blocks confirmation; report what we have.
        return sorted(needed)

    # Drop the most burdensome questions first, so what survives is the least intrusive set.
    for attr in sorted(needed, key=lambda a: (-_ask_cost(spec, a), a)):
        if confirms_all(needed - {attr}):
            needed.discard(attr)
    return sorted(needed)


# ----------------------------------------------------------------- ground truth


@dataclass
class ElicitationGround:
    """Per-persona elicitation ground truth, computed once and reused across systems."""

    persona_id: str
    known_from_query: dict[str, Any] = field(default_factory=dict)
    necessary: set[str] = field(default_factory=set)
    oracle_sequence: list[str] = field(default_factory=list)
    minimal_confirming: list[str] = field(default_factory=list)
    resolvable_without_asking: list[str] = field(default_factory=list)
    undetermined_at_start: list[str] = field(default_factory=list)

    @property
    def oracle_n_questions(self) -> int:
        """Questions needed to settle every scheme — the exhaustive-interview target."""
        return len(self.oracle_sequence)

    @property
    def minimal_n_questions(self) -> int:
        """Questions needed to produce the correct eligible set — the operational target."""
        return len(self.minimal_confirming)

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona_id": self.persona_id,
            "known_from_query": self.known_from_query,
            "necessary": sorted(self.necessary),
            "oracle_sequence": self.oracle_sequence,
            "oracle_n_questions": self.oracle_n_questions,
            "minimal_confirming": self.minimal_confirming,
            "minimal_n_questions": self.minimal_n_questions,
            "resolvable_without_asking": self.resolvable_without_asking,
            "undetermined_at_start": self.undetermined_at_start,
        }


def ground_truth(
    kb: SchemeKB,
    persona_id: str,
    known_from_query: Mapping[str, Any],
    full_profile: Mapping[str, Any],
) -> ElicitationGround:
    """Assemble everything the elicitation metrics need for one persona."""
    known = dict(known_from_query)
    known.update(kb.spec.derive(known))
    start = kb.match(known)
    return ElicitationGround(
        persona_id=persona_id,
        known_from_query=dict(known_from_query),
        necessary=necessary_questions(kb, known),
        oracle_sequence=oracle_question_sequence(kb, known, full_profile),
        minimal_confirming=minimal_confirming_questions(kb, known, full_profile),
        resolvable_without_asking=sorted(start[Verdict.TRUE] + start[Verdict.FALSE]),
        undetermined_at_start=start[Verdict.UNKNOWN],
    )


# ------------------------------------------------------------------- invariants


def assert_monotone(kb: SchemeKB, profile: Mapping[str, Any], order: Sequence[str],
                    full_profile: Mapping[str, Any]) -> None:
    """Check empirically that settled verdicts never flip as information arrives.

    This is the property that licenses the elicitation search to ignore already-settled
    schemes. It holds by construction for Kleene logic; the check exists to catch a
    rule form or normalization step that quietly breaks it.
    """
    state = dict(profile)
    settled: dict[str, Verdict] = {
        s.id: v for s in kb if (v := s.verdict(state)) is not Verdict.UNKNOWN
    }
    for attr in order:
        if full_profile.get(attr) is None:
            continue
        state[attr] = full_profile[attr]
        state.update(kb.spec.derive(state))
        for scheme_id, previous in settled.items():
            now = kb[scheme_id].verdict(state)
            if now is not previous:
                raise AssertionError(
                    f"monotonicity violated: {scheme_id} went {previous.value} -> {now.value} "
                    f"after learning {attr!r}"
                )
        settled.update({
            s.id: v for s in kb if (v := s.verdict(state)) is not Verdict.UNKNOWN
        })
