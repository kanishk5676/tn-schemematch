"""Scheme knowledge base: loading, validation, and the two views of a scheme.

Every scheme carries two representations of the same eligibility conditions:

* ``eligibility_prose`` — the wording as published by the issuing department. This is
  the audit trail: a reviewer can read the prose beside the encoded rule and check
  they agree.
* ``eligibility`` — a machine-readable rule (see :mod:`tn_schemematch.rules`) that the
  rule engine evaluates deterministically. Every verdict a citizen sees comes from it.

Provenance is mandatory, not decorative. Welfare rules change — income ceilings get
revised, schemes get renamed or merged — so every scheme records the URL it was read
from, the date it was read, and whether a human has verified the encoded rule against
that source. Only ``status: verified`` schemes may be told to a citizen as "you can
apply"; see :meth:`SchemeKB.verified`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import yaml

from .attributes import AttributeSpec, default_spec
from .rules import Node, RuleError, Verdict, evaluate, parse_rule, referenced_attributes

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_KB_DIR = _REPO_ROOT / "kb" / "schemes"
DEFAULT_JURISDICTIONS_PATH = _REPO_ROOT / "kb" / "spec" / "jurisdictions.yaml"

SCHEME_LEVELS = {"central", "state"}
SCHEME_STATUSES = {"draft", "verified", "deprecated"}
BENEFIT_TYPES = {"cash_transfer", "pension", "subsidy", "insurance", "loan",
                 "in_kind", "scholarship", "housing", "service", "training"}
BENEFIT_PERIODS = {"month", "year", "once"}


class KBError(ValueError):
    """Raised when a scheme file is malformed or fails validation."""


@lru_cache(maxsize=2)
def jurisdictions(path: str | None = None) -> dict[str, dict[str, str]]:
    """Code -> display names, for the text the system writes rather than reads."""
    source = Path(path) if path else DEFAULT_JURISDICTIONS_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    return dict(raw.get("jurisdictions") or {})


@lru_cache(maxsize=2)
def districts_by_state(path: str | None = None) -> dict[str, tuple[str, ...]]:
    """State code -> the `district` values that belong to it."""
    return _by_state("districts", path)


@lru_cache(maxsize=2)
def ration_cards_by_state(path: str | None = None) -> dict[str, tuple[str, ...]]:
    """State code -> the ration-card classes that state issues."""
    return _by_state("ration_cards", path)


def _by_state(key: str, path: str | None) -> dict[str, tuple[str, ...]]:
    source = Path(path) if path else DEFAULT_JURISDICTIONS_PATH
    raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    return {code: tuple(values) for code, values in (raw.get(key) or {}).items()}


def values_in_state(attr: str, state: str | None) -> tuple[str, ...] | None:
    """The values of ``attr`` that exist in ``state``, or ``None`` when every value can.

    A person in Tamil Nadu is never offered Kozhikode as their district, nor Kerala's
    blue card as their ration card.
    """
    table = {"district": districts_by_state, "ration_card_type": ration_cards_by_state}.get(attr)
    if table is None or not state:
        return None
    return table().get(state)


def jurisdiction_name(code: str) -> str:
    """The English display name for a jurisdiction code, or the code if unknown."""
    return (jurisdictions().get(code) or {}).get("name_en", code)


# ------------------------------------------------------------------- provenance


@dataclass(frozen=True)
class Source:
    """One dated citation backing a scheme's encoded rules."""

    url: str
    title: str
    retrieved: date
    publisher: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = {"url": self.url, "title": self.title, "retrieved": self.retrieved.isoformat()}
        if self.publisher:
            out["publisher"] = self.publisher
        if self.note:
            out["note"] = self.note
        return out


# ---------------------------------------------------------------------- benefits


@dataclass(frozen=True)
class BenefitValue:
    """What a scheme pays, as numbers rather than prose.

    ``amount`` is the lowest figure the source states, so a total built from it is a
    floor ("at least") rather than a promise. Every figure here must also appear in the
    scheme's ``benefit_prose`` — :func:`validate_kb` checks it — so an amount is always
    quoted from the dated source, never typed in from memory.
    """

    amount: float
    per: str                        # month | year | once
    max: float | None = None
    per_family: bool = False        # paid once per family, however many members qualify
    in_kind: bool = False           # the figure is the worth of goods, not cash
    note: str = ""

    @property
    def yearly(self) -> float | None:
        """Recurring cash per year, or ``None`` for a one-time payment."""
        if self.per == "month":
            return self.amount * 12
        if self.per == "year":
            return self.amount
        return None

    @property
    def one_time(self) -> float | None:
        return self.amount if self.per == "once" else None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"amount": self.amount, "per": self.per}
        if self.max is not None:
            out["max"] = self.max
        if self.per_family:
            out["per_family"] = True
        if self.in_kind:
            out["in_kind"] = True
        if self.note:
            out["note"] = self.note
        return out


@dataclass(frozen=True)
class ApplicationWindow:
    """A period when applications are accepted, as a dated source states it.

    Windows are only ever copied from a notification — crop-insurance cut-offs, for one,
    are set by each state every season and moved when the monsoon is late — so ``source``
    is required. ``every_year`` repeats the same calendar dates annually.
    """

    opens: date
    closes: date
    source: str
    every_year: bool = False
    note: str = ""

    def next_from(self, today: date) -> tuple[date, date] | None:
        """The window that is open today or opens next, or ``None`` if it has passed."""
        opens, closes = self.opens, self.closes
        if self.every_year:
            years = max(0, today.year - closes.year)
            opens, closes = _shift_years(opens, years), _shift_years(closes, years)
            if closes < today:
                opens, closes = _shift_years(opens, 1), _shift_years(closes, 1)
        return (opens, closes) if closes >= today else None

    def to_dict(self) -> dict[str, Any]:
        return {"opens": self.opens.isoformat(), "closes": self.closes.isoformat(),
                "every_year": self.every_year, "source": self.source, "note": self.note}


def _shift_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


# ----------------------------------------------------------------------- scheme


@dataclass
class Scheme:
    """A single welfare scheme, in both prose and rule form."""

    id: str
    name: str
    level: str                      # central | state
    # Which government runs it. Required iff level == state, empty for central schemes.
    # Kept as an explicit field rather than inferred from the rule: a rule may reach
    # `state` through a disjunction or an `in` list, so reading the jurisdiction back off
    # it is guesswork, and this value is what the UI displays.
    eligibility: Node               # parsed rule AST
    eligibility_prose: str          # verbatim eligibility wording from the source
    jurisdiction: str = ""
    summary: str = ""
    name_ta: str = ""
    authority: str = ""
    sectors: tuple[str, ...] = ()
    benefit_type: str = "service"
    benefit_prose: str = ""
    documents: tuple[str, ...] = ()
    apply_url: str = ""
    status: str = "draft"
    verified_on: date | None = None
    verified_by: str = ""
    sources: tuple[Source, ...] = ()
    notes: str = ""
    name_ml: str = ""
    value: BenefitValue | None = None
    cover: float | None = None      # insurance: the sum insured per year, never summed as cash
    # (other scheme id, reason quoting the source). Symmetric in SchemeKB.exclusions().
    cannot_combine: tuple[tuple[str, str], ...] = ()
    windows: tuple[ApplicationWindow, ...] = ()
    # Plain words for a citizen: {"ta": {"name", "what", "who", "where"}, "en": {...}}.
    # Optional; ``plain_text`` falls back to the official wording when a field is missing.
    plain: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    plain_reviewed: bool = False    # true only after a person has checked the plain text
    raw_rule: Any = None            # the un-parsed rule, for round-tripping
    source_file: Path | None = None

    # -- behaviour ----------------------------------------------------------

    def decide(self, profile: Mapping[str, Any]):
        """Evaluate this scheme's rule against a profile. Returns a ``Trace``."""
        return evaluate(self.eligibility, profile)

    def verdict(self, profile: Mapping[str, Any]) -> Verdict:
        return self.decide(profile).verdict

    @property
    def attributes(self) -> set[str]:
        """Attributes this scheme's rule reads."""
        return referenced_attributes(self.eligibility)

    @property
    def is_verified(self) -> bool:
        return self.status == "verified"

    def plain_text(self, lang: str, part: str) -> str:
        """One plain-language field, in ``lang`` if written, else the nearest fallback.

        ``name`` falls back to the Tamil or official name and ``what`` to the summary, so
        every scheme can be listed and spoken before its plain text exists. ``who`` and
        ``where`` have no honest fallback and come back empty.
        """
        for language in (lang, "en"):
            text = (self.plain.get(language) or {}).get(part)
            if text:
                return text
        if part == "name":
            return (self.name_ta if lang == "ta" and self.name_ta else self.name)
        if part == "what":
            return self.summary or self.benefit_prose
        return ""

    @property
    def has_plain(self) -> bool:
        return bool(self.plain)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "name_ta": self.name_ta,
            "level": self.level,
            "jurisdiction": self.jurisdiction,
            "jurisdiction_name": jurisdiction_name(self.jurisdiction) if self.jurisdiction else "",
            "authority": self.authority,
            "sectors": list(self.sectors),
            "benefit_type": self.benefit_type,
            "summary": self.summary,
            "benefit_prose": self.benefit_prose,
            "eligibility_prose": self.eligibility_prose,
            "eligibility": self.eligibility.to_dict(),
            "documents": list(self.documents),
            "apply_url": self.apply_url,
            "status": self.status,
            "verified_on": self.verified_on.isoformat() if self.verified_on else None,
            "verified_by": self.verified_by,
            "sources": [s.to_dict() for s in self.sources],
            "notes": self.notes,
            "name_ml": self.name_ml,
            "value": self.value.to_dict() if self.value else None,
            "cover": self.cover,
            "cannot_combine_with": [{"id": other, "reason": reason}
                                    for other, reason in self.cannot_combine],
            "windows": [w.to_dict() for w in self.windows],
            "plain": {lang: dict(text) for lang, text in self.plain.items()},
            "plain_reviewed": self.plain_reviewed,
        }


# --------------------------------------------------------------------------- KB


@dataclass
class SchemeKB:
    """A collection of schemes, typed against one attribute spec."""

    schemes: dict[str, Scheme] = field(default_factory=dict)
    spec: AttributeSpec = field(default_factory=default_spec)

    def __iter__(self) -> Iterator[Scheme]:
        return iter(self.schemes.values())

    def __len__(self) -> int:
        return len(self.schemes)

    def __getitem__(self, scheme_id: str) -> Scheme:
        try:
            return self.schemes[scheme_id]
        except KeyError:
            raise KBError(f"no scheme with id {scheme_id!r}") from None

    def __contains__(self, scheme_id: str) -> bool:
        return scheme_id in self.schemes

    def ids(self) -> list[str]:
        return sorted(self.schemes)

    def verified(self) -> "SchemeKB":
        """The release view: verified schemes only."""
        return SchemeKB({k: v for k, v in self.schemes.items() if v.is_verified}, self.spec)

    def active(self) -> "SchemeKB":
        """Schemes that are still open for application.

        Everything a citizen is told is computed over this view. Deprecated schemes stay in
        the KB so the assistant can recognise one when a person names it and say that it
        has closed — sending someone to an office for a discontinued scheme costs them a
        day's wages.
        """
        return SchemeKB(
            {k: v for k, v in self.schemes.items() if v.status != "deprecated"}, self.spec
        )

    def deprecated_ids(self) -> list[str]:
        return sorted(k for k, v in self.schemes.items() if v.status == "deprecated")

    def exclusions(self) -> dict[str, dict[str, str]]:
        """scheme id -> {scheme it cannot be combined with: reason}, made symmetric.

        A pair is written down once, on whichever scheme's source states it; a person
        eligible for both must still hear about it from either side.
        """
        out: dict[str, dict[str, str]] = {}
        for scheme in self:
            for other, reason in scheme.cannot_combine:
                if other not in self.schemes:
                    continue
                out.setdefault(scheme.id, {}).setdefault(other, reason)
                out.setdefault(other, {}).setdefault(scheme.id, reason)
        return out

    def filter(self, *, level: str | None = None, sector: str | None = None) -> "SchemeKB":
        out = {
            k: v for k, v in self.schemes.items()
            if (level is None or v.level == level) and (sector is None or sector in v.sectors)
        }
        return SchemeKB(out, self.spec)

    # -- the core operation -------------------------------------------------

    def match(self, profile: Mapping[str, Any]) -> dict[Verdict, list[str]]:
        """Partition all schemes by verdict against ``profile``.

        With a fully-specified profile this is the final answer for that person. With a
        partial profile it is the state of knowledge mid-conversation, and the
        UNDETERMINED bucket is what elicitation has to shrink.
        """
        buckets: dict[Verdict, list[str]] = {v: [] for v in Verdict}
        for scheme in self:
            buckets[scheme.verdict(profile)].append(scheme.id)
        for key in buckets:
            buckets[key].sort()
        return buckets

    def eligible_ids(self, profile: Mapping[str, Any]) -> list[str]:
        """Schemes the profile definitively qualifies for."""
        return self.match(profile)[Verdict.TRUE]

    def attribute_usage(self) -> dict[str, list[str]]:
        """attribute -> schemes that read it. Useful for coverage reporting."""
        usage: dict[str, list[str]] = {}
        for scheme in self:
            for attr in scheme.attributes:
                usage.setdefault(attr, []).append(scheme.id)
        return {k: sorted(v) for k, v in sorted(usage.items())}

    def coverage_report(self) -> dict[str, Any]:
        """Summary statistics for the KB, shown on /admin and by ``schemematch stats``."""
        usage = self.attribute_usage()
        by_level: dict[str, int] = {}
        by_sector: dict[str, int] = {}
        by_status: dict[str, int] = {}
        by_jurisdiction: dict[str, int] = {}
        for scheme in self:
            by_level[scheme.level] = by_level.get(scheme.level, 0) + 1
            by_status[scheme.status] = by_status.get(scheme.status, 0) + 1
            if scheme.jurisdiction:
                by_jurisdiction[scheme.jurisdiction] = (
                    by_jurisdiction.get(scheme.jurisdiction, 0) + 1)
            for sector in scheme.sectors:
                by_sector[sector] = by_sector.get(sector, 0) + 1
        clause_counts = [
            sum(1 for _ in scheme.eligibility.walk()) for scheme in self
        ] or [0]
        return {
            "n_schemes": len(self),
            "by_level": dict(sorted(by_level.items())),
            "by_jurisdiction": dict(sorted(by_jurisdiction.items(), key=lambda kv: -kv[1])),
            "by_sector": dict(sorted(by_sector.items(), key=lambda kv: -kv[1])),
            "by_status": dict(sorted(by_status.items())),
            "attributes_used": len(usage),
            "attributes_declared": len(self.spec.names()),
            "unused_attributes": sorted(set(self.spec.names()) - set(usage)),
            "mean_rule_nodes": round(sum(clause_counts) / max(len(clause_counts), 1), 2),
            "max_rule_nodes": max(clause_counts),
            "plain": {
                "written": sum(1 for scheme in self if scheme.has_plain),
                "reviewed": sum(1 for scheme in self if scheme.has_plain and scheme.plain_reviewed),
                "active": sum(1 for scheme in self if scheme.status != "deprecated"),
            },
        }

    # -- serialization ------------------------------------------------------

    def to_json(self, path: str | Path) -> Path:
        """Write the flat JSON export — the released artifact form of the KB."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "attribute_spec_version": self.spec.version,
            "generated": datetime.now().date().isoformat(),
            "n_schemes": len(self),
            "schemes": [s.to_dict() for s in sorted(self, key=lambda s: s.id)],
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path


# ---------------------------------------------------------------------- loading


_REQUIRED_FIELDS = ("id", "name", "level", "eligibility", "eligibility_prose")

# The plain-language block a citizen hears. Every field is one short spoken sentence, and
# ``where`` names a kind of office — never an address, which would go stale or be invented.
PLAIN_LANGUAGES = ("ta", "en")
PLAIN_FIELDS = ("name", "what", "who", "where")


def load_scheme(path: str | Path, spec: AttributeSpec | None = None) -> Scheme:
    """Load and validate one scheme YAML file."""
    spec = spec or default_spec()
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise KBError(f"{path.name}: invalid YAML — {exc}") from None
    if not isinstance(raw, Mapping):
        raise KBError(f"{path.name}: expected a mapping at the top level")

    missing = [f for f in _REQUIRED_FIELDS if not raw.get(f)]
    if missing:
        raise KBError(f"{path.name}: missing required field(s) {missing}")

    level = raw["level"]
    if level not in SCHEME_LEVELS:
        raise KBError(f"{path.name}: level must be one of {sorted(SCHEME_LEVELS)}, got {level!r}")

    status = raw.get("status", "draft")
    if status not in SCHEME_STATUSES:
        raise KBError(f"{path.name}: status must be one of {sorted(SCHEME_STATUSES)}, got {status!r}")

    benefit_type = raw.get("benefit_type", "service")
    if benefit_type not in BENEFIT_TYPES:
        raise KBError(
            f"{path.name}: benefit_type must be one of {sorted(BENEFIT_TYPES)}, got {benefit_type!r}"
        )

    # A state scheme must say which state runs it, and it must be a state the vocabulary
    # knows about — otherwise the rule can constrain `state` to a value no persona can
    # ever hold, and the scheme is silently unreachable rather than loudly wrong.
    jurisdiction = str(raw.get("jurisdiction") or "").strip()
    known_states = tuple(spec["state"].domain or ()) if "state" in spec else ()
    if level == "state":
        if not jurisdiction:
            raise KBError(f"{path.name}: a state scheme must declare a jurisdiction")
        if jurisdiction == "other" or (known_states and jurisdiction not in known_states):
            raise KBError(
                f"{path.name}: jurisdiction {jurisdiction!r} is not a value of the `state` "
                f"attribute; add it to kb/spec/attributes.yaml in the same change that "
                f"adds this state's first scheme"
            )
    elif jurisdiction:
        raise KBError(
            f"{path.name}: a central scheme applies nationally and must not declare a "
            f"jurisdiction (got {jurisdiction!r})"
        )

    try:
        rule = parse_rule(raw["eligibility"], spec)
    except RuleError as exc:
        raise KBError(f"{path.name}: {exc}") from None

    sources = tuple(_parse_source(s, path) for s in (raw.get("sources") or []))
    plain, plain_reviewed = _parse_plain(raw.get("plain"), path)
    if status == "verified" and not sources:
        raise KBError(f"{path.name}: a scheme marked 'verified' must cite at least one source")

    cover = raw.get("cover")
    if cover is not None and (isinstance(cover, bool) or not isinstance(cover, (int, float))
                              or cover <= 0):
        raise KBError(f"{path.name}: cover must be a positive number of rupees")
    cannot_combine = []
    for entry in raw.get("cannot_combine_with") or []:
        if not isinstance(entry, Mapping) or not entry.get("id") or not entry.get("reason"):
            raise KBError(f"{path.name}: each cannot_combine_with entry needs an id and a reason")
        if entry["id"] == raw["id"]:
            raise KBError(f"{path.name}: a scheme cannot exclude itself")
        cannot_combine.append((str(entry["id"]), str(entry["reason"]).strip()))

    return Scheme(
        id=str(raw["id"]),
        name=str(raw["name"]),
        name_ta=str(raw.get("name_ta") or ""),
        level=level,
        authority=str(raw.get("authority") or ""),
        sectors=tuple(raw.get("sectors") or ()),
        benefit_type=benefit_type,
        summary=str(raw.get("summary") or "").strip(),
        benefit_prose=str(raw.get("benefit_prose") or "").strip(),
        eligibility_prose=str(raw["eligibility_prose"]).strip(),
        eligibility=rule,
        jurisdiction=jurisdiction,
        documents=tuple(raw.get("documents") or ()),
        apply_url=str(raw.get("apply_url") or ""),
        status=status,
        verified_on=_parse_date(raw.get("verified_on"), path, "verified_on"),
        verified_by=str(raw.get("verified_by") or ""),
        sources=sources,
        notes=str(raw.get("notes") or "").strip(),
        name_ml=str(raw.get("name_ml") or ""),
        value=_parse_value(raw.get("value"), path),
        cover=float(cover) if cover is not None else None,
        cannot_combine=tuple(cannot_combine),
        windows=tuple(_parse_window(w, path) for w in raw.get("windows") or ()),
        plain=plain,
        plain_reviewed=plain_reviewed,
        raw_rule=raw["eligibility"],
        source_file=path,
    )


def _parse_window(raw: Any, path: Path) -> ApplicationWindow:
    if not isinstance(raw, Mapping) or not raw.get("source"):
        raise KBError(f"{path.name}: every application window must cite a source")
    opens = _parse_date(raw.get("opens"), path, "windows[].opens")
    closes = _parse_date(raw.get("closes"), path, "windows[].closes")
    if opens is None or closes is None or closes < opens:
        raise KBError(f"{path.name}: a window needs opens <= closes")
    every_year = bool(raw.get("every_year", False))
    if every_year and (closes - opens).days >= 365:
        raise KBError(f"{path.name}: a yearly window must be shorter than a year")
    return ApplicationWindow(opens=opens, closes=closes, source=str(raw["source"]),
                             every_year=every_year, note=str(raw.get("note") or "").strip())


def _parse_value(raw: Any, path: Path) -> BenefitValue | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise KBError(f"{path.name}: value must be a mapping with amount and per")
    amount, per, top = raw.get("amount"), raw.get("per"), raw.get("max")
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        raise KBError(f"{path.name}: value.amount must be a positive number of rupees")
    if per not in BENEFIT_PERIODS:
        raise KBError(f"{path.name}: value.per must be one of {sorted(BENEFIT_PERIODS)}")
    if top is not None and (isinstance(top, bool) or not isinstance(top, (int, float))
                            or top < amount):
        raise KBError(f"{path.name}: value.max must be a number no smaller than amount")
    return BenefitValue(amount=float(amount), per=per,
                        max=float(top) if top is not None else None,
                        per_family=bool(raw.get("per_family", False)),
                        in_kind=bool(raw.get("in_kind", False)),
                        note=str(raw.get("note") or "").strip())


def _parse_plain(raw: Any, path: Path) -> tuple[dict[str, dict[str, str]], bool]:
    """Validate a scheme's ``plain:`` block. Unknown languages or fields are errors: a typo
    ("wher:") would otherwise leave a citizen hearing nothing about where to go."""
    if raw is None:
        return {}, False
    if not isinstance(raw, Mapping):
        raise KBError(f"{path.name}: plain must be a mapping of language -> fields")
    reviewed = raw.get("reviewed", False)
    if not isinstance(reviewed, bool):
        raise KBError(f"{path.name}: plain.reviewed must be true or false")
    plain: dict[str, dict[str, str]] = {}
    for lang, fields in raw.items():
        if lang == "reviewed":
            continue
        if lang not in PLAIN_LANGUAGES:
            raise KBError(f"{path.name}: plain has unknown language {lang!r}; "
                          f"use {list(PLAIN_LANGUAGES)}")
        if not isinstance(fields, Mapping):
            raise KBError(f"{path.name}: plain.{lang} must be a mapping")
        unknown = set(fields) - set(PLAIN_FIELDS)
        if unknown:
            raise KBError(f"{path.name}: plain.{lang} has unknown field(s) {sorted(unknown)}; "
                          f"use {list(PLAIN_FIELDS)}")
        plain[lang] = {key: str(value).strip() for key, value in fields.items()
                       if value is not None and str(value).strip()}
    return plain, reviewed


def _parse_source(raw: Mapping[str, Any], path: Path) -> Source:
    for required in ("url", "title", "retrieved"):
        if not raw.get(required):
            raise KBError(f"{path.name}: source missing {required!r}")
    return Source(
        url=str(raw["url"]),
        title=str(raw["title"]),
        retrieved=_parse_date(raw["retrieved"], path, "sources[].retrieved"),
        publisher=raw.get("publisher"),
        note=raw.get("note"),
    )


def _parse_date(value: Any, path: Path, field_name: str) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        raise KBError(f"{path.name}: {field_name} must be YYYY-MM-DD, got {value!r}") from None


def load_kb(
    directory: str | Path | None = None,
    spec: AttributeSpec | None = None,
    *,
    verified_only: bool = False,
) -> SchemeKB:
    """Load every ``*.yaml`` scheme under ``directory`` (recursively)."""
    spec = spec or default_spec()
    directory = Path(directory) if directory else DEFAULT_KB_DIR
    if not directory.exists():
        raise KBError(f"KB directory not found: {directory}")

    schemes: dict[str, Scheme] = {}
    for path in sorted(directory.rglob("*.yaml")):
        scheme = load_scheme(path, spec)
        if scheme.id in schemes:
            other = schemes[scheme.id].source_file
            raise KBError(f"duplicate scheme id {scheme.id!r} in {path.name} and {other.name}")
        schemes[scheme.id] = scheme

    kb = SchemeKB(schemes, spec)
    return kb.verified() if verified_only else kb


def validate_kb(kb: SchemeKB) -> list[str]:
    """Structural checks that go beyond per-file parsing. Returns a list of problems.

    The important one is the last: with a *fully* specified profile no scheme may
    return UNDETERMINED. If one does, its rule reads an attribute that personas can
    never supply, and any ground-truth label computed from it would be silently wrong.
    """
    problems: list[str] = []
    spec = kb.spec

    for scheme in kb:
        if not scheme.summary:
            problems.append(f"{scheme.id}: empty summary (the scheme card would be blank)")
        if scheme.status == "verified" and not scheme.verified_on:
            problems.append(f"{scheme.id}: marked verified but has no verified_on date")
        if scheme.level == "state" and "state" not in scheme.attributes:
            problems.append(
                f"{scheme.id}: state scheme whose rule never constrains 'state' — "
                "residents of every other state would wrongly match"
            )
        for attr in scheme.attributes:
            if attr not in spec:
                problems.append(f"{scheme.id}: references undeclared attribute {attr!r}")
        figures = []
        if scheme.value:
            figures += [scheme.value.amount] + ([scheme.value.max] if scheme.value.max else [])
        if scheme.cover:
            figures.append(scheme.cover)
        for figure in figures:
            if not figure_in_text(figure, scheme.benefit_prose):
                problems.append(
                    f"{scheme.id}: the figure {figure:,.0f} is not in benefit_prose — every "
                    f"amount must be quoted from the sourced text")
        for other, _ in scheme.cannot_combine:
            if other not in kb:
                problems.append(f"{scheme.id}: cannot_combine_with names unknown scheme {other!r}")

    # Total-knowledge check
    saturated = _saturated_profile(spec)
    for scheme in kb:
        if scheme.verdict(saturated) is Verdict.UNKNOWN:
            unresolved = sorted(
                p.attr for p in scheme.decide(saturated).unknown_predicates()
            )
            problems.append(
                f"{scheme.id}: UNDETERMINED under a fully-specified profile "
                f"(unresolved: {unresolved})"
            )

    problems += _check_jurisdiction_scoping(kb, saturated)
    return problems


def indian_grouping(amount: float) -> str:
    """12345678 -> '1,23,45,678': the way Indian sources print rupees."""
    digits = str(int(round(amount)))
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return ",".join(([head] if head else []) + groups + [tail])


def figure_in_text(amount: float, text: str) -> bool:
    """Does ``text`` state ``amount`` — as '1,000', '1000', '5 lakh' or '3.50 lakh'?"""
    forms = {indian_grouping(amount), f"{amount:,.0f}", str(int(round(amount)))}
    for unit, size in (("lakh", 1e5), ("crore", 1e7)):
        if amount >= size:
            scaled = amount / size
            forms |= {f"{scaled:g} {unit}", f"{scaled:.2f} {unit}", f"{scaled:.1f} {unit}"}
    # Not part of a longer number: "1,000" must not match inside "11,000" or "1,000,5".
    return any(re.search(rf"(?<![\d.])(?<!\d,){re.escape(form)}(?!,?\d)", text)
               for form in forms)


# Income ceilings and benefit amounts move with every budget and by Government Order in
# between, so a rule last read more than about six months ago may no longer say what the
# scheme does.
STALE_AFTER_DAYS = 180


def stale_schemes(kb: SchemeKB, *, today: date | None = None,
                  max_age_days: int = STALE_AFTER_DAYS) -> list[str]:
    """Warnings for active schemes whose rule has not been checked recently.

    A scheme's age runs from the newer of its latest source retrieval and its human
    verification. These are warnings, not problems: an old source is not a broken rule,
    but it is the first place to look when a scheme may have changed under the KB.
    """
    today = today or date.today()
    warnings: list[str] = []
    for scheme in kb.active():
        checked = [source.retrieved for source in scheme.sources]
        if scheme.verified_on:
            checked.append(scheme.verified_on)
        if not checked:
            warnings.append(f"{scheme.id}: no dated source to age from")
            continue
        last = max(checked)
        age = (today - last).days
        if age > max_age_days:
            warnings.append(f"{scheme.id}: last checked {last.isoformat()}, {age} days ago")
    return warnings


def _check_jurisdiction_scoping(kb: "SchemeKB", saturated: dict[str, Any]) -> list[str]:
    """Prove each state scheme is refuted for a resident of every other state.

    This is the check that stands in for test profiles we have not written. They are all
    Tamil Nadu residents, so a Karnataka scheme copied from a Tamil Nadu
    one that still says ``value: TN`` passes everything else in this file: its rule *does*
    constrain ``state``, no test profile lives in Karnataka so no gold label moves, and the
    gold-set diff is clean. The scheme is simply unreachable, forever, and nothing says so.

    Being a property of the rules rather than of any persona, this holds for every state
    in the vocabulary whether or not any test profile lives there.
    """
    problems: list[str] = []
    spec = kb.spec
    if "state" not in spec:
        return problems
    domain = tuple(spec["state"].domain or ())

    for scheme in kb:
        if scheme.level != "state":
            continue
        if not scheme.jurisdiction:
            problems.append(f"{scheme.id}: state scheme with no jurisdiction")
            continue

        # Negative direction: a resident of any other state must be refuted outright.
        for other in domain:
            if other == scheme.jurisdiction:
                continue
            if scheme.verdict({**saturated, "state": other}) is not Verdict.FALSE:
                problems.append(
                    f"{scheme.id}: declares jurisdiction {scheme.jurisdiction} but is not "
                    f"refuted for a resident of {other!r} — the state clause does not "
                    f"actually scope it"
                )

        # Positive direction: `state` must not be what refutes it at home. Catches the
        # copy-paste — a Karnataka file whose rule still tests `state == TN`.
        home = {**saturated, "state": scheme.jurisdiction}
        if any(pred.attr == "state" for pred in scheme.decide(home).failing_predicates()):
            problems.append(
                f"{scheme.id}: declares jurisdiction {scheme.jurisdiction} but its own "
                f"state clause refutes a resident of {scheme.jurisdiction} — copied from "
                f"another state?"
            )

        if "district" in scheme.attributes:
            own = set(districts_by_state().get(scheme.jurisdiction, ()))
            named = {value for pred in scheme.eligibility.walk()
                     if getattr(pred, "attr", None) == "district"
                     for value in (pred.value if isinstance(pred.value, (list, tuple))
                                   else [pred.value])}
            if not own or named - own:
                problems.append(
                    f"{scheme.id}: names districts outside {scheme.jurisdiction}: "
                    f"{sorted(named - own) or 'no district list for this state'}")

    # The district vocabulary and the per-state lists must be the same set.
    if "district" in spec:
        listed = {d for names in districts_by_state().values() for d in names}
        if listed != set(spec["district"].domain or ()):
            problems.append("kb/spec/jurisdictions.yaml districts do not match the "
                            "`district` attribute's domain")
    return problems


def _saturated_profile(spec: AttributeSpec) -> dict[str, Any]:
    """A profile with every declared attribute set to some in-domain value."""
    profile: dict[str, Any] = {}
    for name, attr in spec.attributes.items():
        if attr.type == "bool":
            profile[name] = False
        elif attr.type == "number":
            lo, hi = attr.domain or (0.0, 1.0)
            profile[name] = float(lo)
        elif attr.type == "enum" and attr.domain:
            profile[name] = attr.domain[0]
    return profile


def iter_scheme_files(directory: str | Path | None = None) -> Iterable[Path]:
    directory = Path(directory) if directory else DEFAULT_KB_DIR
    return sorted(directory.rglob("*.yaml"))
