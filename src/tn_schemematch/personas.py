"""Test profiles: whole people, with the answer the rule engine must give for each.

A test profile (called a *persona* in the code and the data files) is a complete attribute
profile plus the first sentence that person might say, in code-mixed Tamil-English and in
English. ``stated_in_query`` records which facts that sentence reveals.

They are regression tests for the rules. Ground truth is *computed*, never written by
hand: the eligible set is whatever the rule engine returns for the full profile over
active schemes. So a rule change that silently drops someone from a scheme shows up as a
moved gold label in ``scripts/gold_diff.py`` before it reaches a citizen.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Mapping

import yaml

from .attributes import AttributeSpec, SchemaError, default_spec
from .elicitation import ElicitationGround, ground_truth
from .kb import SchemeKB
from .rules import Const, Not, Verdict, transform

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_PERSONA_DIR = _REPO_ROOT / "data" / "personas"

CONDITIONS = ("code_mixed", "english")


class PersonaError(ValueError):
    """Raised when a persona file is malformed or inconsistent with the vocabulary."""


# --------------------------------------------------------------------- annotation


@dataclass
class Annotation:
    """Human validation record for a persona's queries."""

    author: str = ""
    validated_by: str = ""
    validated_on: str = ""
    codemix_naturalness: int | None = None   # 1-5, native-speaker rating
    profile_plausibility: int | None = None  # 1-5, is this a realistic citizen
    parallel_faithful: bool | None = None    # do both variants reveal the same facts
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "validated_by": self.validated_by,
            "validated_on": self.validated_on,
            "codemix_naturalness": self.codemix_naturalness,
            "profile_plausibility": self.profile_plausibility,
            "parallel_faithful": self.parallel_faithful,
            "notes": self.notes,
        }


# ------------------------------------------------------------------------ persona


@dataclass
class Persona:
    """One citizen profile with its paired code-mixed and English queries."""

    id: str
    profile: dict[str, Any]              # full, normalized attribute profile
    queries: dict[str, str]              # condition -> query text
    stated_in_query: tuple[str, ...] = ()  # attributes the query actually reveals
    persona_sketch: str = ""             # one-line human description, for error analysis
    annotation: Annotation = field(default_factory=Annotation)
    source_file: Path | None = None

    # -- derived views ------------------------------------------------------

    def known_profile(self) -> dict[str, Any]:
        """What a perfect extractor would recover from the query, and nothing more."""
        return {a: self.profile[a] for a in self.stated_in_query if a in self.profile}

    def gold_eligible(self, kb: SchemeKB) -> list[str]:
        """The ground-truth eligible set: active schemes satisfied by the full profile."""
        return kb.active().eligible_ids(self.profile)

    def gold_ineligible(self, kb: SchemeKB) -> list[str]:
        return kb.active().match(self.profile)[Verdict.FALSE]

    def elicitation_ground(self, kb: SchemeKB) -> ElicitationGround:
        return ground_truth(kb.active(), self.id, self.known_profile(), self.profile)

    def query(self, condition: str) -> str:
        if condition not in self.queries:
            raise PersonaError(f"{self.id}: no query for condition {condition!r}")
        return self.queries[condition]

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "persona_sketch": self.persona_sketch,
            "profile": self.profile,
            "queries": self.queries,
            "stated_in_query": list(self.stated_in_query),
            "annotation": self.annotation.to_dict(),
        }


# --------------------------------------------------------------------- collection


@dataclass
class PersonaSet:
    """A loaded collection of personas."""

    personas: dict[str, Persona] = field(default_factory=dict)
    spec: AttributeSpec = field(default_factory=default_spec)

    def __iter__(self) -> Iterator[Persona]:
        return iter(self.personas.values())

    def __len__(self) -> int:
        return len(self.personas)

    def __getitem__(self, persona_id: str) -> Persona:
        try:
            return self.personas[persona_id]
        except KeyError:
            raise PersonaError(f"no persona with id {persona_id!r}") from None

    def ids(self) -> list[str]:
        return sorted(self.personas)

    def gold(self, kb: SchemeKB) -> dict[str, list[str]]:
        """persona id -> ground-truth eligible scheme ids."""
        active = kb.active()
        return {p.id: active.eligible_ids(p.profile) for p in self}

    def summary(self, kb: SchemeKB) -> dict[str, Any]:
        """Distributional statistics reported in the paper's resource section."""
        gold = self.gold(kb)
        sizes = [len(v) for v in gold.values()] or [0]
        grounds = [p.elicitation_ground(kb) for p in self]
        n_questions = [g.oracle_n_questions for g in grounds] or [0]
        revealed = [len(p.stated_in_query) for p in self] or [0]
        scheme_hits: dict[str, int] = {}
        for ids in gold.values():
            for scheme_id in ids:
                scheme_hits[scheme_id] = scheme_hits.get(scheme_id, 0) + 1
        return {
            "n_personas": len(self),
            "mean_gold_set_size": round(sum(sizes) / len(sizes), 2),
            "min_gold_set_size": min(sizes),
            "max_gold_set_size": max(sizes),
            "personas_with_empty_gold_set": sum(1 for s in sizes if s == 0),
            "mean_attributes_revealed_by_query": round(sum(revealed) / len(revealed), 2),
            "mean_oracle_questions": round(sum(n_questions) / len(n_questions), 2),
            "max_oracle_questions": max(n_questions),
            "scheme_frequency": dict(sorted(scheme_hits.items(), key=lambda kv: -kv[1])),
            "schemes_never_eligible": sorted(set(kb.active().ids()) - set(scheme_hits)),
        }

    def to_jsonl(self, path: str | Path, kb: SchemeKB | None = None) -> Path:
        """Export the benchmark in the released one-record-per-line form."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for persona in sorted(self, key=lambda p: p.id):
                record = persona.to_dict()
                if kb is not None:
                    record["gold_eligible"] = persona.gold_eligible(kb)
                    record["gold_ineligible"] = persona.gold_ineligible(kb)
                    record["elicitation"] = persona.elicitation_ground(kb).to_dict()
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path


# ---------------------------------------------------------------------- loading


def load_persona(path: str | Path, spec: AttributeSpec | None = None) -> Persona:
    """Load and normalize one persona file."""
    spec = spec or default_spec()
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, Mapping):
        raise PersonaError(f"{path.name}: expected a mapping at the top level")

    for required in ("id", "profile", "queries"):
        if not raw.get(required):
            raise PersonaError(f"{path.name}: missing required field {required!r}")

    try:
        profile = spec.normalize_profile(raw["profile"])
    except SchemaError as exc:
        raise PersonaError(f"{path.name}: {exc}") from None

    queries = {k: str(v).strip() for k, v in raw["queries"].items() if str(v).strip()}
    unknown_conditions = set(queries) - set(CONDITIONS)
    if unknown_conditions:
        raise PersonaError(
            f"{path.name}: unknown query condition(s) {sorted(unknown_conditions)}; "
            f"expected {list(CONDITIONS)}"
        )
    missing_conditions = set(CONDITIONS) - set(queries)
    if missing_conditions:
        raise PersonaError(
            f"{path.name}: missing query variant(s) {sorted(missing_conditions)} — "
            "every test profile carries both opening sentences"
        )

    stated = tuple(raw.get("stated_in_query") or ())
    for attr in stated:
        if attr not in spec:
            raise PersonaError(f"{path.name}: stated_in_query names unknown attribute {attr!r}")
        if attr not in profile:
            raise PersonaError(
                f"{path.name}: stated_in_query lists {attr!r} but the profile does not set it"
            )

    annotation_raw = raw.get("annotation") or {}
    annotation = Annotation(
        author=str(annotation_raw.get("author") or ""),
        validated_by=str(annotation_raw.get("validated_by") or ""),
        validated_on=str(annotation_raw.get("validated_on") or ""),
        codemix_naturalness=annotation_raw.get("codemix_naturalness"),
        profile_plausibility=annotation_raw.get("profile_plausibility"),
        parallel_faithful=annotation_raw.get("parallel_faithful"),
        notes=str(annotation_raw.get("notes") or ""),
    )

    return Persona(
        id=str(raw["id"]),
        profile=profile,
        queries=queries,
        stated_in_query=stated,
        persona_sketch=str(raw.get("persona_sketch") or "").strip(),
        annotation=annotation,
        source_file=path,
    )


def load_personas(
    directory: str | Path | None = None, spec: AttributeSpec | None = None
) -> PersonaSet:
    """Load every persona YAML under ``directory``."""
    spec = spec or default_spec()
    directory = Path(directory) if directory else DEFAULT_PERSONA_DIR
    if not directory.exists():
        raise PersonaError(f"persona directory not found: {directory}")

    personas: dict[str, Persona] = {}
    for path in sorted(directory.rglob("*.yaml")):
        persona = load_persona(path, spec)
        if persona.id in personas:
            raise PersonaError(f"duplicate persona id {persona.id!r} in {path.name}")
        personas[persona.id] = persona
    return PersonaSet(personas, spec)


def coverage_gaps(personas: PersonaSet, kb: SchemeKB) -> dict[str, list[str]]:
    """Which parts of the rule KB no persona actually exercises.

    A benchmark can look healthy — good spread of gold-set sizes, plausible people — and
    still never test whole classes of rule. The pilot found exactly this: the first four
    personas all satisfied every exclusion clause in the KB, so a system that ignored
    exclusions entirely scored identically to one that applied them, and the
    highest-cost failure mode was invisible.

    Three gaps are reported, each corresponding to a claim the benchmark should support:

    ``uncovered_exclusions``
        ``not:`` clauses that are never the reason a persona fails. Missed exclusions
        produce false positives, so these are the most expensive gaps.
    ``uncovered_schemes``
        schemes no persona is eligible for. Their positive conditions are never confirmed.
    ``untested_attributes``
        attributes the rules read but which take only one value across the whole persona
        set — the constraint is present but never varied, so nothing distinguishes a system
        that checks it from one that assumes it.
    """
    active = kb.active()
    uncovered_exclusions: list[str] = []

    for scheme in active:
        exclusions = [n for n in scheme.eligibility.walk() if isinstance(n, Not)]
        if not exclusions:
            continue
        relaxed = transform(
            scheme.eligibility,
            lambda node: Const(Verdict.TRUE) if isinstance(node, Not) else node,
        )
        blocked_by_exclusion = any(
            scheme.verdict(p.profile) is not Verdict.TRUE
            and relaxed.evaluate(p.profile).verdict is Verdict.TRUE
            for p in personas
        )
        if not blocked_by_exclusion:
            uncovered_exclusions.append(scheme.id)

    eligible_somewhere = {s for ids in personas.gold(kb).values() for s in ids}
    uncovered_schemes = sorted(set(active.ids()) - eligible_somewhere)

    untested: list[str] = []
    for attr in active.attribute_usage():
        values = {
            p.profile.get(attr) for p in personas if p.profile.get(attr) is not None
        }
        if len(values) <= 1:
            untested.append(attr)

    return {
        "uncovered_exclusions": sorted(uncovered_exclusions),
        "uncovered_schemes": uncovered_schemes,
        "untested_attributes": sorted(untested),
    }


def validate_personas(personas: PersonaSet, kb: SchemeKB) -> list[str]:
    """Consistency checks across the persona set. Returns a list of problems.

    The land-split check matters more than it looks: wet and dry land are separate
    attributes because schemes cap them separately, so a persona whose parts do not sum
    to its total would produce ground truth that no real applicant could reproduce.
    """
    problems: list[str] = []
    spec = personas.spec
    active = kb.active()

    for persona in personas:
        # Full profiles must settle every scheme, or the gold label is a guess.
        undetermined = active.match(persona.profile)[Verdict.UNKNOWN]
        if undetermined:
            problems.append(
                f"{persona.id}: profile leaves {undetermined} undetermined — "
                "the profile is incomplete for this KB, so its gold set is unreliable"
            )

        # Queries must not reveal more than the annotation claims.
        if not persona.stated_in_query:
            problems.append(f"{persona.id}: stated_in_query is empty; elicitation metrics need it")

        # Wet + dry land should reconcile with the declared total.
        parts = [persona.profile.get("wetland_acres"), persona.profile.get("dryland_acres")]
        total = persona.profile.get("land_owned_acres")
        if total is not None and all(p is not None for p in parts):
            if abs(sum(parts) - total) > 0.01:
                problems.append(
                    f"{persona.id}: wetland + dryland ({sum(parts)}) != land_owned_acres ({total})"
                )

        for condition in CONDITIONS:
            if condition not in persona.queries:
                problems.append(f"{persona.id}: missing {condition} query variant")

        if persona.annotation.parallel_faithful is False:
            problems.append(
                f"{persona.id}: annotator marked the two variants as not faithful parallels; "
                "re-author the code-mixed variant"
            )

    # A test set where every profile qualifies for everything tests nothing.
    gold = personas.gold(kb)
    if gold:
        all_ids = set(active.ids())
        if all(set(v) == all_ids for v in gold.values()):
            problems.append("every persona has the same gold set — the benchmark cannot discriminate")

    return problems
