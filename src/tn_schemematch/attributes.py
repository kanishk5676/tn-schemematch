"""Attribute vocabulary, typing, and normalization.

The attribute space is declared in ``kb/spec/attributes.yaml`` and loaded here.
Everything downstream — scheme rules, test profiles, saved citizen profiles, and the
facts the assistant records — is typed against this vocabulary, so a rule can never
reference an attribute the product does not define.

The normalizer exists because code-mixed queries carry quantities in whatever unit
the speaker thinks in ("rendu ekkar", "2 acre", "80 cent", "month-ku 8000") and
categories in whatever surface form they use ("adi dravidar", "SC", "ஆதிதிராவிடர்").
Comparing those against a threshold requires canonicalization first; that step is
precisely what the RAG baseline skips.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

# --------------------------------------------------------------------------- paths

_PKG_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PKG_ROOT.parent.parent
DEFAULT_SPEC_PATH = _REPO_ROOT / "kb" / "spec" / "attributes.yaml"


class SchemaError(ValueError):
    """Raised when the attribute spec or a value violates the declared vocabulary."""


# ---------------------------------------------------------------------- data model


@dataclass(frozen=True)
class Attribute:
    """One typed slot in the normalized attribute space."""

    name: str
    type: str  # number | enum | bool
    description: str = ""
    unit: str | None = None
    domain: tuple[Any, ...] | None = None  # (min, max) for number; values for enum
    aliases: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    aliases_text: tuple[str, ...] = ()
    derived_from: str | None = None
    elicitable: bool = True
    sensitivity: str = "low"

    @property
    def is_derived(self) -> bool:
        return self.derived_from is not None

    def values(self) -> tuple[Any, ...]:
        """Candidate values for enum/bool attributes (used by the elicitation search)."""
        if self.type == "bool":
            return (True, False)
        if self.type == "enum":
            return tuple(self.domain or ())
        return ()

    def validate(self, value: Any) -> Any:
        """Type- and domain-check a canonical value. Returns it unchanged if valid."""
        if value is None:
            return None
        if self.type == "bool":
            if not isinstance(value, bool):
                raise SchemaError(f"{self.name}: expected bool, got {value!r}")
            return value
        if self.type == "number":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SchemaError(f"{self.name}: expected number, got {value!r}")
            if self.domain:
                lo, hi = self.domain
                if not (lo <= value <= hi):
                    raise SchemaError(
                        f"{self.name}: {value} outside declared domain [{lo}, {hi}]"
                    )
            return float(value)
        if self.type == "enum":
            if value not in (self.domain or ()):
                raise SchemaError(
                    f"{self.name}: {value!r} not in domain {list(self.domain or ())}"
                )
            return value
        raise SchemaError(f"{self.name}: unknown type {self.type!r}")


@dataclass(frozen=True)
class DerivationBin:
    max: float | None
    value: Any


@dataclass
class AttributeSpec:
    """The loaded attribute vocabulary."""

    version: str
    updated: str
    attributes: dict[str, Attribute]
    derivations: dict[str, dict[str, Any]]
    units: dict[str, dict[str, float]]

    # -- lookup -------------------------------------------------------------

    def __contains__(self, name: str) -> bool:
        return name in self.attributes

    def __getitem__(self, name: str) -> Attribute:
        try:
            return self.attributes[name]
        except KeyError:
            raise SchemaError(f"unknown attribute {name!r}") from None

    def names(self) -> list[str]:
        return list(self.attributes)

    def elicitable_names(self) -> list[str]:
        return [n for n, a in self.attributes.items() if a.elicitable and not a.is_derived]

    # -- normalization ------------------------------------------------------

    def canonicalize(self, name: str, raw: Any) -> Any:
        """Map a raw surface value to the canonical value for ``name``.

        Accepts values already canonical, alias strings (English, romanized Tamil,
        or Tamil script), booleans in several surface forms, and numeric strings
        with unit suffixes.
        """
        attr = self[name]
        if raw is None:
            return None

        if attr.type == "bool":
            return _to_bool(raw, attr.name)

        if attr.type == "number":
            if isinstance(raw, (int, float)) and not isinstance(raw, bool):
                return attr.validate(float(raw))
            value = parse_quantity(str(raw), self.units.get(attr.unit or "", {}))
            if value is None:
                raise SchemaError(f"{name}: cannot parse quantity from {raw!r}")
            return attr.validate(value)

        if attr.type == "enum":
            if raw in (attr.domain or ()):
                return raw
            key = _fold(str(raw))
            # exact canonical match, case-insensitively
            for canon in attr.domain or ():
                if _fold(str(canon)) == key:
                    return canon
            # alias match
            for canon, forms in attr.aliases.items():
                for form in forms:
                    if _fold(form) == key:
                        return canon
            # substring alias match, longest alias first so "sugar card" beats "card".
            # Abbreviations of one or two characters are excluded, for the same reason
            # _mentions disables prefix matching on them: an unanchored "m" matches inside
            # "pombala" and "amma", and "ma"/"be" match inside "male", so a free-text answer
            # in romanized Tamil silently canonicalizes to the wrong value instead of
            # failing. They still resolve through the exact-alias loop above.
            candidates: list[tuple[int, Any]] = []
            for canon, forms in attr.aliases.items():
                for form in forms:
                    folded = _fold(form)
                    if len(folded) <= 2:
                        continue
                    if folded and folded in key:
                        candidates.append((len(folded), canon))
            if candidates:
                return max(candidates)[1]
            raise SchemaError(f"{name}: no canonical value for {raw!r}")

        raise SchemaError(f"{name}: unknown type {attr.type!r}")

    def normalize_profile(self, raw: Mapping[str, Any], *, derive: bool = True) -> dict[str, Any]:
        """Canonicalize every value in a raw profile, then fill derived attributes."""
        out: dict[str, Any] = {}
        for name, value in raw.items():
            if name not in self.attributes:
                raise SchemaError(f"unknown attribute {name!r} in profile")
            if value is None:
                continue
            out[name] = self.canonicalize(name, value)
        if derive:
            out.update(self.derive(out))
        return out

    def derive(self, profile: Mapping[str, Any]) -> dict[str, Any]:
        """Compute derived attributes from the base ones present in ``profile``."""
        derived: dict[str, Any] = {}
        for target, spec in self.derivations.items():
            source = spec["from"]
            if source not in profile or profile[source] is None:
                continue
            value = profile[source]
            if "bins" in spec:
                derived[target] = _apply_bins(value, spec["bins"])
            else:
                derived[target] = _eval_derivation(spec["rule"], value)
        return derived


# ------------------------------------------------------------------- normalizers

_BOOL_TRUE = {
    "true", "yes", "y", "1", "irukku", "இருக்கு", "undu", "உண்டு", "aam", "ஆம்", "have", "has",
}
_BOOL_FALSE = {
    "false", "no", "n", "0", "illa", "இல்ல", "இல்லை", "illai", "none", "not", "dont have",
}


def _to_bool(raw: Any, name: str) -> bool:
    if isinstance(raw, bool):
        return raw
    key = _fold(str(raw))
    if key in _BOOL_TRUE:
        return True
    if key in _BOOL_FALSE:
        return False
    raise SchemaError(f"{name}: cannot read {raw!r} as a boolean")


def _fold(text: str) -> str:
    """Casefold, strip punctuation and collapse whitespace, preserving Tamil script."""
    text = unicodedata.normalize("NFC", str(text)).casefold().strip()
    text = re.sub(r"[^\w\s஀-௿]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_MAGNITUDES: dict[str, float] = {
    "thousand": 1e3, "k": 1e3, "ayiram": 1e3, "ஆயிரம்": 1e3,
    "lakh": 1e5, "lac": 1e5, "lakhs": 1e5, "laksham": 1e5, "லட்சம்": 1e5, "latcham": 1e5,
    "crore": 1e7, "cr": 1e7, "கோடி": 1e7, "kodi": 1e7,
}

_LAND_UNITS: dict[str, str] = {
    "acre": "acres", "acres": "acres", "ekkar": "acres", "ஏக்கர்": "acres", "ekar": "acres",
    "hectare": "hectares", "hectares": "hectares", "ha": "hectares", "ஹெக்டேர்": "hectares",
    "cent": "cents", "cents": "cents", "சென்ட்": "cents",
    "ground": "grounds", "grounds": "grounds", "graund": "grounds",
    "sqft": "square_feet", "sq ft": "square_feet", "square feet": "square_feet",
}

_PER_MONTH = {"month", "monthly", "per month", "manthly", "maasam", "மாசம்", "மாதம்", "maatham", "pm"}


def _mentions(tokens: list[str], phrase: str) -> bool:
    """Does the folded token list contain ``phrase``?

    Word-boundary regexes are unusable here. Tamil words routinely end in a consonant
    carrying a pulli (U+0BCD), a combining mark that Python's ``\\b`` does not treat as a
    word character — so ``\\bலட்சம்\\b`` never matches the very strings it was written for.
    Token comparison sidesteps the issue. Prefix matching handles Tamil's agglutination
    ("maasathukku" for "maasam"), but is disabled for one- and two-character
    abbreviations, where it would match far too much ("k" inside "kadai").
    """
    phrase = _fold(phrase)
    if not phrase:
        return False
    if " " in phrase:
        return phrase in " ".join(tokens)
    if len(phrase) <= 2:
        return phrase in tokens
    return any(token == phrase or token.startswith(phrase) for token in tokens)


def parse_quantity(text: str, unit_table: Mapping[str, float]) -> float | None:
    """Parse a free-text quantity into the canonical unit of ``unit_table``.

    ``unit_table`` maps a source unit name to its multiplier toward the canonical unit
    (see the ``units:`` block of the attribute spec). Handles Indian digit grouping
    ("1,00,000"), magnitude words in English, romanized Tamil and Tamil script, land-unit
    conversion, and monthly-to-annual conversion for money.
    """
    normalized = unicodedata.normalize("NFC", str(text)).casefold()
    # Indian digit grouping: 1,00,000 -> 100000. Done before folding, which drops commas.
    normalized = re.sub(r"(?<=\d),(?=\d)", "", normalized)

    match = re.search(r"\d+(?:\.\d+)?", normalized)
    if not match:
        return None
    number = float(match.group(0))
    tokens = _fold(normalized).split()

    magnitude_applied = False
    for word, factor in _MAGNITUDES.items():
        if _mentions(tokens, word):
            number *= factor
            magnitude_applied = True
            break

    # Land units
    for word, canonical in _LAND_UNITS.items():
        if canonical in unit_table and _mentions(tokens, word):
            return number * unit_table[canonical]

    # Money: monthly figures annualize
    if "INR_per_month" in unit_table:
        if any(_mentions(tokens, w) for w in _PER_MONTH):
            return number * unit_table["INR_per_month"] / unit_table.get("INR_per_year", 1)
        return number

    # Fallback: an explicit unit name from the table appears in the text.
    # Skipped once a magnitude word has been applied — several unit tables name their
    # units "lakh" and "crore", and applying both would multiply the figure twice.
    if not magnitude_applied:
        for unit_name, factor in unit_table.items():
            if _mentions(tokens, unit_name.replace("_", " ")):
                return number * factor
    return number


def _apply_bins(value: float, bins: Iterable[Mapping[str, Any]]) -> Any:
    for b in bins:
        upper = b.get("max")
        if upper is None or value <= float(upper):
            return b["value"]
    raise SchemaError(f"no derivation bin matched value {value!r}")


_DERIVATION_PATTERN = re.compile(
    r"^value\s*(==|!=|>=|<=|>|<)\s*(-?\d+(?:\.\d+)?|'[^']*'|\"[^\"]*\")$"
)


def _eval_derivation(rule: str, value: Any) -> bool:
    """Evaluate a derivation predicate without ``eval``.

    Only the tiny grammar ``value <op> <literal>`` is supported, deliberately: the
    attribute spec is a data file, and a data file should not be able to execute code.
    """
    match = _DERIVATION_PATTERN.match(rule.strip())
    if not match:
        raise SchemaError(f"unsupported derivation rule {rule!r}")
    op, literal = match.groups()
    if literal.startswith(("'", '"')):
        operand: Any = literal[1:-1]
    else:
        operand = float(literal)
        value = float(value)
    ops = {
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
    }
    return bool(ops[op](value, operand))


# ------------------------------------------------------------------------ loading


def load_spec(path: str | Path | None = None) -> AttributeSpec:
    """Load and validate the attribute vocabulary."""
    path = Path(path) if path else DEFAULT_SPEC_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    attributes: dict[str, Attribute] = {}
    for name, body in (raw.get("attributes") or {}).items():
        atype = body.get("type")
        if atype not in {"number", "enum", "bool"}:
            raise SchemaError(f"{name}: unsupported type {atype!r}")
        domain = body.get("domain")
        if atype == "number":
            if not (isinstance(domain, list) and len(domain) == 2):
                raise SchemaError(f"{name}: number attributes need domain [min, max]")
            domain = (float(domain[0]), float(domain[1]))
        elif atype == "enum":
            if not domain:
                raise SchemaError(f"{name}: enum attributes need a domain list")
            domain = tuple(domain)
        else:
            domain = None
        aliases = {k: tuple(v) for k, v in (body.get("aliases") or {}).items()}
        if atype == "enum":
            unknown = set(aliases) - set(domain or ())
            if unknown:
                raise SchemaError(f"{name}: aliases for values outside domain: {sorted(unknown)}")
        attributes[name] = Attribute(
            name=name,
            type=atype,
            description=(body.get("description") or "").strip(),
            unit=body.get("unit"),
            domain=domain,
            aliases=aliases,
            aliases_text=tuple(body.get("aliases_text") or ()),
            derived_from=body.get("derived_from"),
            elicitable=bool(body.get("elicitable", True)),
            sensitivity=body.get("sensitivity", "low"),
        )

    derivations = raw.get("derivations") or {}
    for target, spec in derivations.items():
        if target not in attributes:
            raise SchemaError(f"derivation targets unknown attribute {target!r}")
        if spec.get("from") not in attributes:
            raise SchemaError(f"derivation for {target!r} reads unknown attribute {spec.get('from')!r}")
        if "bins" not in spec and "rule" not in spec:
            raise SchemaError(f"derivation for {target!r} needs either 'bins' or 'rule'")

    return AttributeSpec(
        version=str(raw.get("version", "0")),
        updated=str(raw.get("updated", "")),
        attributes=attributes,
        derivations=derivations,
        units=raw.get("units") or {},
    )


@lru_cache(maxsize=4)
def default_spec() -> AttributeSpec:
    """Cached loader for the bundled attribute spec."""
    return load_spec()
