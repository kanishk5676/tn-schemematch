"""Behavioural probes: systems whose failure mode is known exactly.

None of these is a model. Each is a deliberately-shaped reasoner that fails in one
specific, named way, and together they answer a question that has to be settled *before*
spending money on real models:

    Do the metrics detect the things they claim to detect?

If a system that ignores every numeric threshold scores the same as one that applies them,
the false-positive rate is not measuring threshold reasoning, and no number of real model
runs will fix that. Running these first is cheap, deterministic, and turns the metric suite
from an assumption into something that has been checked.

They serve a second purpose afterwards. Once a real model has been run, its metric profile
can be read against these reference points: a model whose numbers resemble
``TopicalSystem``'s is doing retrieval and calling it matching; one resembling
``ThresholdBlindSystem`` is applying categorical gates but not numeric ones. That is a more
useful diagnosis than "F1 was 0.62".

``NoElicitationSystem`` is the one that is not a probe but a genuine ablation for the paper:
the grounding pipeline forbidden to ask anything, answering from the query alone. The gap
between it and the full pipeline is what elicitation is worth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..attributes import AttributeSpec
from ..kb import Scheme, SchemeKB
from ..personas import Persona
from ..rules import Const, Node, Not, Predicate, Verdict, transform
from .base import MatchResult, timed
from .retrieval import BM25Retriever

__all__ = [
    "OracleSystem",
    "AbstainSystem",
    "TopicalSystem",
    "ThresholdBlindSystem",
    "ExclusionBlindSystem",
    "NoElicitationSystem",
    "reference_suite",
]


@dataclass
class OracleSystem:
    """Always correct. The upper bound; any metric that punishes this is misdefined."""

    kb: SchemeKB
    name: str = "probe:oracle"

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        with timed() as clock:
            returned = persona.gold_eligible(kb)
        return MatchResult(persona.id, condition, self.name, model="none",
                           returned=returned, retrieved=kb.active().ids(),
                           latency_s=clock.elapsed)


@dataclass
class AbstainSystem:
    """Always returns nothing.

    The adversary for any harm metric defined as a rate over returned items: it commits
    zero false positives by never answering. If it posts a good false-positive score, the
    metric rewards silence and needs the abstention guard that ``false_positive_rate``
    implements by returning ``None``.
    """

    kb: SchemeKB
    name: str = "probe:abstain"

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        return MatchResult(persona.id, condition, self.name, model="none",
                           returned=[], retrieved=kb.active().ids())


@dataclass
class TopicalSystem:
    """Returns whatever retrieval surfaced. Retrieval mistaken for matching — RQ1's null.

    This is the behaviour the project exists to argue against, made concrete. It should
    show high retrieval recall alongside a high false-positive rate; if it does not, the
    retrieval-vs-matching gap is not measuring what its name says.
    """

    kb: SchemeKB
    top_k: int = 5
    name: str = field(init=False)

    def __post_init__(self) -> None:
        self.retriever = BM25Retriever(self.kb.active())
        self.name = f"probe:topical[k={self.top_k}]"

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        with timed() as clock:
            retrieved = self.retriever.retrieve(persona.query(condition), self.top_k)
        return MatchResult(persona.id, condition, self.name, model="none",
                           returned=sorted(retrieved), retrieved=retrieved,
                           latency_s=clock.elapsed)


# ----------------------------------------------------- rule-ablation probes


@dataclass
class _AblatedRuleSystem:
    """Shared machinery: evaluate the KB with some class of clause disabled."""

    kb: SchemeKB
    name: str = "probe:ablated"

    def _ablate(self, rule: Node, spec: AttributeSpec) -> Node:  # pragma: no cover
        raise NotImplementedError

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        active = kb.active()
        returned: list[str] = []
        with timed() as clock:
            for scheme in active:
                broken = self._ablate(scheme.eligibility, kb.spec)
                if broken.evaluate(persona.profile).verdict is Verdict.TRUE:
                    returned.append(scheme.id)
        return MatchResult(persona.id, condition, self.name, model="none",
                           returned=sorted(returned), retrieved=active.ids(),
                           final_profile=dict(persona.profile), latency_s=clock.elapsed)


@dataclass
class ThresholdBlindSystem(_AblatedRuleSystem):
    """Applies categorical constraints; treats every numeric comparison as satisfied.

    The specific failure RULEARENA reports and RQ1 replicates: the system knows a scheme is
    for women in Tamil Nadu, and does not notice that the income ceiling rules this person
    out. Because it only ever *relaxes* clauses, its errors are false positives by
    construction — so the false-positive rate must rise here or it is not sensitive to
    threshold reasoning.
    """

    name: str = "probe:threshold_blind"

    def _ablate(self, rule: Node, spec: AttributeSpec) -> Node:
        def relax(node: Node) -> Node:
            if isinstance(node, Predicate) and spec[node.attr].type == "number":
                return Const(Verdict.TRUE)
            return node

        return transform(rule, relax)


@dataclass
class ExclusionBlindSystem(_AblatedRuleSystem):
    """Applies positive conditions; ignores every ``not:`` block.

    Missing exclusions are the highest-risk encoding error and the highest-risk reasoning
    error, for the same reason: they only ever produce false positives. Someone is told
    they qualify because nothing checked that they pay income tax.
    """

    name: str = "probe:exclusion_blind"

    def _ablate(self, rule: Node, spec: AttributeSpec) -> Node:
        def drop(node: Node) -> Node:
            return Const(Verdict.TRUE) if isinstance(node, Not) else node

        return transform(rule, drop)


# ------------------------------------------------------------ real ablation


@dataclass
class NoElicitationSystem:
    """The grounding pipeline, forbidden to ask anything.

    Not a probe — a paper ablation. It decides from the facts the query happens to state,
    which is what a single-turn system does. The gap between this and the full pipeline is
    the value of asking, stated as a number.

    Note what it does *not* do: it never guesses. Schemes left undetermined are reported as
    not-eligible, so its errors are false negatives, not false positives. That asymmetry is
    the point — a grounded system that cannot ask becomes conservative, whereas a prose-based
    system that cannot ask becomes confident.
    """

    kb: SchemeKB
    name: str = "ablation:no_elicitation"

    def run(self, persona: Persona, condition: str, kb: SchemeKB | None = None) -> MatchResult:
        kb = kb or self.kb
        active = kb.active()
        with timed() as clock:
            profile = dict(persona.known_profile())
            profile.update(kb.spec.derive(profile))
            returned = active.eligible_ids(profile)
        return MatchResult(persona.id, condition, self.name, model="none",
                           returned=returned, retrieved=active.ids(),
                           extracted_profile=dict(profile), final_profile=dict(profile),
                           latency_s=clock.elapsed)


def reference_suite(kb: SchemeKB) -> list[Any]:
    """The full set of model-free reference points, in the order they belong in a table."""
    return [
        OracleSystem(kb),
        NoElicitationSystem(kb),
        ThresholdBlindSystem(kb),
        ExclusionBlindSystem(kb),
        TopicalSystem(kb),
        AbstainSystem(kb),
    ]
