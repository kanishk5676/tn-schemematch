"""Eligibility rule language and three-valued evaluator.

Why three-valued. A citizen query is *underspecified*: it mentions two or three
attributes and leaves the rest silent. Two-valued logic has to guess, and guessing
in this domain means either telling someone they qualify when they might not (a
false positive, our headline harm metric) or silently dropping a scheme they may
well be entitled to. Instead we evaluate under Kleene's strong three-valued logic:
a missing attribute makes its comparison UNKNOWN, and UNKNOWN propagates only where
it can still matter — ``AND`` with one FALSE is FALSE regardless, ``OR`` with one
TRUE is TRUE regardless. A scheme therefore lands in one of three buckets:

    ELIGIBLE      the rule is satisfied on what we already know
    INELIGIBLE    the rule is refuted on what we already know
    UNDETERMINED  we must ask for more before we may say either

That third bucket is not a failure state. It is the signal that drives elicitation
(see :mod:`tn_schemematch.elicitation`) and the reason a grounded system can decline
to assert eligibility rather than hallucinate it.

Rule syntax (YAML/JSON, as it appears in a scheme file)::

    eligibility:
      all:
        - {attr: state, op: eq, value: TN}
        - {attr: land_owned_acres, op: lte, value: 5.0}
        - any:
            - {attr: social_category, op: in, value: [SC, ST]}
            - {attr: annual_family_income, op: lte, value: 100000}
        - not: {attr: is_income_tax_payer, op: eq, value: true}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterator, Mapping, Sequence

from .attributes import AttributeSpec, SchemaError

__all__ = [
    "Verdict",
    "Node",
    "Predicate",
    "Const",
    "All",
    "AnyOf",
    "Not",
    "Trace",
    "parse_rule",
    "evaluate",
    "transform",
    "referenced_attributes",
    "numeric_boundaries",
]


class RuleError(ValueError):
    """Raised when a rule is malformed or references an undeclared attribute."""


# ------------------------------------------------------------------ truth values


class Verdict(Enum):
    """Kleene truth value, named for the eligibility domain."""

    TRUE = "eligible"
    FALSE = "ineligible"
    UNKNOWN = "undetermined"

    def __and__(self, other: "Verdict") -> "Verdict":
        if self is Verdict.FALSE or other is Verdict.FALSE:
            return Verdict.FALSE
        if self is Verdict.UNKNOWN or other is Verdict.UNKNOWN:
            return Verdict.UNKNOWN
        return Verdict.TRUE

    def __or__(self, other: "Verdict") -> "Verdict":
        if self is Verdict.TRUE or other is Verdict.TRUE:
            return Verdict.TRUE
        if self is Verdict.UNKNOWN or other is Verdict.UNKNOWN:
            return Verdict.UNKNOWN
        return Verdict.FALSE

    def __invert__(self) -> "Verdict":
        if self is Verdict.TRUE:
            return Verdict.FALSE
        if self is Verdict.FALSE:
            return Verdict.TRUE
        return Verdict.UNKNOWN

    @property
    def is_settled(self) -> bool:
        return self is not Verdict.UNKNOWN


def _v(flag: bool) -> Verdict:
    return Verdict.TRUE if flag else Verdict.FALSE


# ------------------------------------------------------------------- comparisons

_ORDERED_OPS = {"lt", "lte", "gt", "gte"}

_COMPARATORS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "lt": lambda a, b: a < b,
    "lte": lambda a, b: a <= b,
    "gt": lambda a, b: a > b,
    "gte": lambda a, b: a >= b,
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "between": lambda a, b: b[0] <= a <= b[1],
}

OPS = frozenset(_COMPARATORS) | {"is_known", "is_unknown"}


# ------------------------------------------------------------------------- nodes


@dataclass(frozen=True)
class Node:
    """Base class for rule AST nodes."""

    def evaluate(self, profile: Mapping[str, Any]) -> "Trace":  # pragma: no cover
        raise NotImplementedError

    def walk(self) -> Iterator["Node"]:  # pragma: no cover
        raise NotImplementedError

    def to_dict(self) -> Any:  # pragma: no cover
        raise NotImplementedError


@dataclass(frozen=True)
class Const(Node):
    """A fixed verdict. Only used by rule transforms, never authored in a scheme file.

    Ablations need to disable a class of clause — "what if this system ignored every
    numeric threshold?" — without deleting it from the tree and changing the shape of the
    conjunction it sits in. Replacing the clause with a constant keeps the structure intact
    so the ablation isolates exactly one thing.
    """

    verdict: Verdict = None  # type: ignore[assignment]

    def evaluate(self, profile: Mapping[str, Any]) -> "Trace":
        return Trace(self, self.verdict)

    def walk(self) -> Iterator[Node]:
        yield self

    def to_dict(self) -> dict[str, Any]:
        return {"const": self.verdict.value}


@dataclass(frozen=True)
class Predicate(Node):
    """A single typed comparison against one attribute."""

    attr: str
    op: str
    value: Any = None
    note: str | None = None  # optional human-readable gloss, kept for provenance

    def evaluate(self, profile: Mapping[str, Any]) -> "Trace":
        present = self.attr in profile and profile[self.attr] is not None
        if self.op == "is_known":
            return Trace(self, _v(present))
        if self.op == "is_unknown":
            return Trace(self, _v(not present))
        if not present:
            return Trace(self, Verdict.UNKNOWN)
        actual = profile[self.attr]
        try:
            result = _COMPARATORS[self.op](actual, self.value)
        except TypeError as exc:
            raise RuleError(
                f"cannot apply {self.op!r} to {self.attr}={actual!r} vs {self.value!r}"
            ) from exc
        return Trace(self, _v(bool(result)), actual=actual)

    def walk(self) -> Iterator[Node]:
        yield self

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"attr": self.attr, "op": self.op}
        if self.op not in {"is_known", "is_unknown"}:
            out["value"] = list(self.value) if isinstance(self.value, tuple) else self.value
        if self.note:
            out["note"] = self.note
        return out

    def describe(self) -> str:
        if self.op in {"is_known", "is_unknown"}:
            return f"{self.attr} {self.op}"
        symbol = {"eq": "==", "ne": "!=", "lt": "<", "lte": "<=", "gt": ">", "gte": ">="}
        if self.op in symbol:
            return f"{self.attr} {symbol[self.op]} {self.value}"
        if self.op == "between":
            return f"{self.value[0]} <= {self.attr} <= {self.value[1]}"
        return f"{self.attr} {self.op.replace('_', ' ')} {list(self.value)}"


@dataclass(frozen=True)
class All(Node):
    """Conjunction. Empty conjunction is vacuously TRUE."""

    children: tuple[Node, ...]

    def evaluate(self, profile: Mapping[str, Any]) -> "Trace":
        traces = [c.evaluate(profile) for c in self.children]
        verdict = Verdict.TRUE
        for t in traces:
            verdict = verdict & t.verdict
        return Trace(self, verdict, children=traces)

    def walk(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            yield from child.walk()

    def to_dict(self) -> dict[str, Any]:
        return {"all": [c.to_dict() for c in self.children]}


@dataclass(frozen=True)
class AnyOf(Node):
    """Disjunction. Empty disjunction is vacuously FALSE."""

    children: tuple[Node, ...]

    def evaluate(self, profile: Mapping[str, Any]) -> "Trace":
        traces = [c.evaluate(profile) for c in self.children]
        verdict = Verdict.FALSE
        for t in traces:
            verdict = verdict | t.verdict
        return Trace(self, verdict, children=traces)

    def walk(self) -> Iterator[Node]:
        yield self
        for child in self.children:
            yield from child.walk()

    def to_dict(self) -> dict[str, Any]:
        return {"any": [c.to_dict() for c in self.children]}


@dataclass(frozen=True)
class Not(Node):
    """Negation. Exclusion clauses ("must not be an income-tax payer") live here."""

    child: Node

    def evaluate(self, profile: Mapping[str, Any]) -> "Trace":
        inner = self.child.evaluate(profile)
        return Trace(self, ~inner.verdict, children=[inner])

    def walk(self) -> Iterator[Node]:
        yield self
        yield from self.child.walk()

    def to_dict(self) -> dict[str, Any]:
        return {"not": self.child.to_dict()}


# ------------------------------------------------------------------------ traces


@dataclass
class Trace:
    """Evaluation record: which clause produced which verdict, and on what value."""

    node: Node
    verdict: Verdict
    children: list["Trace"] = field(default_factory=list)
    actual: Any = None

    def failing_predicates(self) -> list[Predicate]:
        """Predicates that evaluated FALSE — i.e. the reasons for a rejection."""
        return [t.node for t in self._flatten()
                if isinstance(t.node, Predicate) and t.verdict is Verdict.FALSE]

    def unknown_predicates(self) -> list[Predicate]:
        """Predicates still UNKNOWN — the raw material for elicitation."""
        return [t.node for t in self._flatten()
                if isinstance(t.node, Predicate) and t.verdict is Verdict.UNKNOWN]

    def _flatten(self) -> Iterator["Trace"]:
        yield self
        for child in self.children:
            yield from child._flatten()

    def explain(self, indent: int = 0) -> str:
        pad = "  " * indent
        if isinstance(self.node, Predicate):
            seen = "" if self.actual is None else f"  (observed: {self.actual!r})"
            return f"{pad}[{self.verdict.value}] {self.node.describe()}{seen}"
        if isinstance(self.node, Const):
            return f"{pad}[{self.verdict.value}] (clause disabled by ablation)"
        label = {All: "ALL of", AnyOf: "ANY of", Not: "NOT"}[type(self.node)]
        lines = [f"{pad}[{self.verdict.value}] {label}"]
        lines += [c.explain(indent + 1) for c in self.children]
        return "\n".join(lines)


# ------------------------------------------------------------------------ parser


def parse_rule(spec: Any, attr_spec: AttributeSpec, *, path: str = "eligibility") -> Node:
    """Build a rule AST from its YAML/JSON form, validating against the vocabulary.

    Validation here is what makes the KB trustworthy: a rule cannot reference an
    attribute that does not exist, compare an enum against a value outside its
    domain, or apply an ordering operator to a categorical attribute.
    """
    if isinstance(spec, list):
        # A bare list is read as a conjunction; this is the common case in scheme files.
        return All(tuple(parse_rule(item, attr_spec, path=f"{path}[{i}]")
                         for i, item in enumerate(spec)))

    if not isinstance(spec, Mapping):
        raise RuleError(f"{path}: expected a mapping or list, got {type(spec).__name__}")

    keys = set(spec)
    for combinator, cls in (("all", All), ("any", AnyOf)):
        if combinator in keys:
            if keys - {combinator}:
                raise RuleError(f"{path}: {combinator!r} node cannot carry other keys {sorted(keys)}")
            children = spec[combinator]
            if not isinstance(children, Sequence) or isinstance(children, (str, bytes)):
                raise RuleError(f"{path}.{combinator}: expected a list")
            if not children:
                raise RuleError(f"{path}.{combinator}: empty {combinator} block is ambiguous; remove it")
            return cls(tuple(parse_rule(c, attr_spec, path=f"{path}.{combinator}[{i}]")
                             for i, c in enumerate(children)))

    if "not" in keys:
        if keys - {"not"}:
            raise RuleError(f"{path}: 'not' node cannot carry other keys {sorted(keys)}")
        return Not(parse_rule(spec["not"], attr_spec, path=f"{path}.not"))

    return _parse_predicate(spec, attr_spec, path)


def _parse_predicate(spec: Mapping[str, Any], attr_spec: AttributeSpec, path: str) -> Predicate:
    missing = {"attr", "op"} - set(spec)
    if missing:
        raise RuleError(f"{path}: predicate missing {sorted(missing)}")
    name, op = spec["attr"], spec["op"]
    if op not in OPS:
        raise RuleError(f"{path}: unknown operator {op!r}; expected one of {sorted(OPS)}")
    if name not in attr_spec:
        raise RuleError(f"{path}: rule references undeclared attribute {name!r}")
    attr = attr_spec[name]

    if op in {"is_known", "is_unknown"}:
        return Predicate(name, op, None, spec.get("note"))

    if "value" not in spec:
        raise RuleError(f"{path}: operator {op!r} requires a 'value'")
    raw = spec["value"]

    if op in _ORDERED_OPS and attr.type != "number":
        raise RuleError(
            f"{path}: ordering operator {op!r} applied to {attr.type} attribute {name!r}; "
            "use 'in' / 'eq' for categorical attributes"
        )

    try:
        if op in {"in", "not_in"}:
            if not isinstance(raw, (list, tuple, set)):
                raise RuleError(f"{path}: {op!r} requires a list value")
            value: Any = tuple(attr.validate(attr_spec.canonicalize(name, v)) for v in raw)
            if not value:
                raise RuleError(f"{path}: {op!r} with an empty list is always the same; remove it")
        elif op == "between":
            if not (isinstance(raw, (list, tuple)) and len(raw) == 2):
                raise RuleError(f"{path}: 'between' requires [low, high]")
            low, high = (attr.validate(attr_spec.canonicalize(name, v)) for v in raw)
            if low > high:
                raise RuleError(f"{path}: 'between' bounds inverted ({low} > {high})")
            value = (low, high)
        else:
            value = attr.validate(attr_spec.canonicalize(name, raw))
    except SchemaError as exc:
        raise RuleError(f"{path}: {exc}") from None

    return Predicate(name, op, value, spec.get("note"))


# ---------------------------------------------------------------------- analysis


def evaluate(rule: Node, profile: Mapping[str, Any]) -> Trace:
    """Evaluate ``rule`` against a (possibly partial) normalized profile."""
    return rule.evaluate(profile)


def referenced_attributes(rule: Node) -> set[str]:
    """Every attribute the rule reads."""
    return {n.attr for n in rule.walk() if isinstance(n, Predicate)}


def transform(node: Node, fn) -> Node:
    """Rebuild a rule tree, applying ``fn`` to every node bottom-up.

    ``fn`` receives a node and returns a replacement (or the node unchanged). Used to build
    test profiles that sit exactly one clause away from a scheme, and by tests that need a
    rule with a known, deliberate defect.
    """
    if isinstance(node, All):
        node = All(tuple(transform(child, fn) for child in node.children))
    elif isinstance(node, AnyOf):
        node = AnyOf(tuple(transform(child, fn) for child in node.children))
    elif isinstance(node, Not):
        node = Not(transform(node.child, fn))
    return fn(node)


def numeric_boundaries(rule: Node, attr: str) -> list[float]:
    """Threshold constants the rule uses for ``attr``.

    The elicitation search probes just below, at, and just above each of these
    rather than sampling the whole numeric range: for a rule built from comparisons,
    behaviour only changes at its own thresholds.
    """
    bounds: set[float] = set()
    for node in rule.walk():
        if not isinstance(node, Predicate) or node.attr != attr:
            continue
        if node.op == "between" and isinstance(node.value, tuple):
            bounds.update(float(v) for v in node.value)
        elif isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            bounds.add(float(node.value))
        elif isinstance(node.value, tuple):
            bounds.update(float(v) for v in node.value
                          if isinstance(v, (int, float)) and not isinstance(v, bool))
    return sorted(bounds)
