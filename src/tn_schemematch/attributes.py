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
    # state code -> canonical value -> surface forms that mean it *in that state only*.
    # "White card" is a rice card in Tamil Nadu and the most affluent card in Kerala.
    aliases_by_state: Mapping[str, Mapping[str, tuple[str, ...]]] = field(default_factory=dict)
    aliases_text: tuple[str, ...] = ()
    derived_from: str | None = None
    elicitable: bool = True
    sensitivity: str = "low"
    # Something a person can do to change this fact (open an account, get a card):
    # {text, document?, online?, from?, only_if?}. The unlock view offers only these, and
    # only to someone whose facts match ``only_if``.
    action: Mapping[str, Any] | None = None
    # Counts up by itself each year (age, years registered); the "coming up" view
    # re-runs the rules with these advanced.
    grows_with_time: bool = False

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

    def canonicalize(self, name: str, raw: Any, *,
                     context: Mapping[str, Any] | None = None) -> Any:
        """Map a raw surface value to the canonical value for ``name``.

        Accepts values already canonical, alias strings (English, romanized Tamil or
        Malayalam, Tamil or Malayalam script), booleans in several surface forms, and
        numeric strings with unit suffixes. ``context`` is what is already known about the
        person; its ``state`` selects that state's own aliases, which are tried first.
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
            state = (context or {}).get("state")
            tables = [attr.aliases_by_state[state]] if state in attr.aliases_by_state else []
            tables.append(attr.aliases)
            # alias match, the person's own state first
            for table in tables:
                for canon, forms in table.items():
                    for form in forms:
                        if _fold(form) == key:
                            return canon
            # substring alias match, longest alias first so "sugar card" beats "card".
            # Abbreviations of one or two characters are excluded, for the same reason
            # _mentions disables prefix matching on them: an unanchored "m" matches inside
            # "pombala" and "amma", and "ma"/"be" match inside "male", so a free-text answer
            # in romanized Tamil silently canonicalizes to the wrong value instead of
            # failing. They still resolve through the exact-alias loop above.
            for table in tables:
                candidates: list[tuple[int, Any]] = []
                for canon, forms in table.items():
                    for form in forms:
                        folded = _fold(form)
                        if len(folded) <= 2:
                            continue
                        if folded and folded in key:
                            candidates.append((len(folded), canon))
                if candidates:
                    return max(candidates)[1]
            if any(_fold(form) in key for scoped in attr.aliases_by_state.values()
                   for forms in scoped.values() for form in forms if len(_fold(form)) > 2):
                raise SchemaError(f"{name}: {raw!r} means different things in different "
                                  f"states — the state must be known first")
            raise SchemaError(f"{name}: no canonical value for {raw!r}")

        raise SchemaError(f"{name}: unknown type {attr.type!r}")

    def normalize_profile(self, raw: Mapping[str, Any], *, derive: bool = True) -> dict[str, Any]:
        """Canonicalize every value in a raw profile, then fill derived attributes."""
        out: dict[str, Any] = {}
        # The state first: other values may be read differently depending on it.
        for name, value in sorted(raw.items(), key=lambda kv: kv[0] != "state"):
            if name not in self.attributes:
                raise SchemaError(f"unknown attribute {name!r} in profile")
            if value is None:
                continue
            out[name] = self.canonicalize(name, value, context=out)
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
    "ഉണ്ട്", "athe", "അതെ",
    # Spoken forms, with and without the respectful -ங்க: what a voice answer looks like.
    "aama", "aamaa", "aamam", "aamaam", "aamanga", "aamaanga", "ஆமா", "ஆமாம்", "ஆமாங்க",
    "irukkunga", "இருக்குங்க", "irukkuthu", "இருக்குது", "yes irukku", "yes sir", "yes madam",
    "s", "ok yes",
}
_BOOL_FALSE = {
    "false", "no", "n", "0", "illa", "இல்ல", "இல்லை", "illai", "none", "not", "dont have",
    "ഇല്ല", "alla", "അല്ല",
    "illainga", "illeenga", "இல்லீங்க", "இல்லைங்க", "kidaiyathu", "கிடையாது", "no sir",
    "no madam", "illa sir", "do not have", "nope",
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
    """Casefold, strip punctuation and collapse whitespace, preserving every Indic script.

    ``\\w`` alone is not enough: vowel signs and the virama are combining marks (Unicode
    categories Mn and Mc), which ``\\w`` does not match, so "ലക്ഷം" (lakh) would be cut into
    "ലക ഷ". Keeping all marks keeps Tamil, Malayalam and every other Brahmic script whole.
    """
    text = unicodedata.normalize("NFC", str(text)).casefold().strip()
    # Zero-width joiners are dropped, not spaced: older Malayalam text writes a chillu as
    # consonant + virama + ZWJ, and a space there would split the word.
    text = text.replace("\u200d", "").replace("\u200c", "")
    text = "".join(ch if ch.isspace() or ch.isalnum() or ch == "_"
                   or unicodedata.category(ch).startswith("M") else " " for ch in text)
    return re.sub(r"\s+", " ", text).strip()


_MAGNITUDES: dict[str, float] = {
    "thousand": 1e3, "k": 1e3, "aayiram": 1e3, "ayiram": 1e3, "ஆயிரம்": 1e3, "ആയിരം": 1e3,
    "lakh": 1e5, "lac": 1e5, "lakhs": 1e5, "laksham": 1e5, "லட்சம்": 1e5, "latcham": 1e5,
    "ലക്ഷം": 1e5,
    "crore": 1e7, "cr": 1e7, "கோடி": 1e7, "kodi": 1e7, "കോടി": 1e7,
}

_LAND_UNITS: dict[str, str] = {
    "acre": "acres", "acres": "acres", "ekkar": "acres", "ஏக்கர்": "acres", "ekar": "acres",
    "ഏക്കർ": "acres",
    "hectare": "hectares", "hectares": "hectares", "ha": "hectares", "ஹெக்டேர்": "hectares",
    "ഹെക്ടർ": "hectares",
    # Kerala measures most holdings in cents: "pathu sentu" is ten cents, not ten acres.
    "cent": "cents", "cents": "cents", "சென்ட்": "cents", "sentu": "cents", "സെന്റ്": "cents",
    "ground": "grounds", "grounds": "grounds", "graund": "grounds",
    "sqft": "square_feet", "sq ft": "square_feet", "square feet": "square_feet",
}

_PER_MONTH = {"month", "monthly", "per month", "manthly", "maasam", "மாசம்", "மாதம்", "maatham", "pm",
              "masam", "മാസം", "പ്രതിമാസം"}

# Electricity in Tamil Nadu is billed every two months, so that is the figure people know.
_TWO_MONTHS = re.compile(
    r"(?:^|\s)(?:2|rendu|randu|irandu|two|ரெண்டு|இரண்டு)\s*"
    r"(?:maas|masa|maat|month|மாச|மாத)\S*|(?:^|\s)bi\s?monthly")

# Number words, for answers spoken rather than typed: "rendu ekkar", "aimbathu aayiram",
# "அறுபது வயசு". Forms ending in "-" match as a prefix, which catches Tamil's combining
# forms and case endings ("iruvathi", "இருபதுக்கு") without listing every inflection.
_UNIT_WORDS: tuple[tuple[float, tuple[str, ...]], ...] = (
    (0, ("zero", "poojyam", "poojiyam", "pujyam", "பூஜ்யம்", "பூஜ்ஜியம்", "nil")),
    (0.25, ("kaal", "கால்", "quarter")),
    (0.5, ("arai", "அரை", "half")),
    (1, ("oru", "onnu", "ondru", "onru", "ஒரு", "ஒன்னு", "ஒன்று", "one")),
    (1.5, ("onnara", "onrara", "ஒன்றரை", "ஒண்ணரை")),
    (2, ("rendu", "randu", "irandu", "ரெண்டு", "இரண்டு", "two")),
    (2.5, ("rendara", "irandara", "இரண்டரை", "ரெண்டரை")),
    (3, ("moonu", "munu", "moondru", "மூணு", "மூன்று", "three")),
    (4, ("naalu", "nalu", "naangu", "நாலு", "நான்கு", "four")),
    (5, ("anju", "ainthu", "aindhu", "அஞ்சு", "ஐந்து", "five")),
    (6, ("aaru", "ஆறு", "six")),
    (7, ("ezhu", "yezhu", "elu", "ஏழு", "seven")),
    (8, ("ettu", "எட்டு", "eight")),
    (9, ("onbathu", "onbadhu", "ஒன்பது", "nine")),
    (10, ("pathu", "paththu", "பத்து", "ten")),
    (11, ("pathinonnu", "pathinondru", "பதினொன்று", "eleven")),
    (12, ("pannendu", "pannirandu", "பன்னிரண்டு", "twelve")),
    (13, ("pathimoonu", "பதிமூன்று", "thirteen")),
    (14, ("pathinaalu", "பதினான்கு", "fourteen")),
    (15, ("pathinanju", "பதினைந்து", "fifteen")),
    (16, ("pathinaaru", "பதினாறு", "sixteen")),
    (17, ("pathinezhu", "பதினேழு", "seventeen")),
    (18, ("pathinettu", "பதினெட்டு", "eighteen")),
    (19, ("pathonbathu", "பத்தொன்பது", "nineteen")),
)
_TENS: tuple[tuple[float, tuple[str, ...]], ...] = (
    (20, ("iruvath", "irupath", "இருபத", "twenty")),
    (30, ("muppath", "முப்பத", "thirty")),
    (40, ("naarpath", "narpath", "நாற்பத", "forty")),
    (50, ("aimbath", "ambath", "ஐம்பத", "fifty")),
    (60, ("arupath", "aruvath", "அறுபத", "sixty")),
    (70, ("ezhupath", "ezhuvath", "எழுபத", "seventy")),
    (80, ("enbath", "embath", "எண்பத", "eighty")),
    (90, ("thonnoor", "thonnur", "தொண்ணூ", "ninety")),
)
# What follows a tens stem inside one Tamil-script word: இருபத்தைந்து is இருபத + ்தைந்து.
_TENS_TAIL_TA = {
    "்தொன்று": 1, "்தொன்னு": 1, "்திரண்டு": 2, "்தி ரெண்டு": 2, "்துமூன்று": 3,
    "்துமூணு": 3, "்துநான்கு": 4, "்துநாலு": 4, "்தைந்து": 5, "்தஞ்சு": 5, "்தாறு": 6,
    "்தேழு": 7, "்தெட்டு": 8, "்தொன்பது": 9,
}
# The stem a unit takes before ஆயிரம் / aayiram: ஐந்தாயிரம் is ஐந்த + ாயிரம், 5 x 1000.
_THOUSAND_STEMS = {
    "or": 1, "rend": 2, "irand": 2, "moov": 3, "moo": 3, "naal": 4, "naang": 4, "anj": 5,
    "aindh": 5, "ainth": 5, "aar": 6, "ezh": 7, "ett": 8, "onbath": 9, "onbadh": 9,
    "path": 10, "ஓர": 1, "இரண்ட": 2, "ரெண்ட": 2, "மூவ": 3, "நால": 4, "நான்க": 4,
    "ஐந்த": 5, "அஞ்ச": 5, "ஆற": 6, "ஏழ": 7, "எட்ட": 8, "ஒன்பத": 9, "பத்த": 10,
}
_THOUSAND_SUFFIXES = ("aayiram", "ayiram", "ாயிரம்")
_HUNDRED = ("nooru", "நூறு", "hundred")


def _number_word(token: str) -> float | None:
    """The value of one number word, or ``None``."""
    for value, forms in _UNIT_WORDS:
        if token in forms:
            return value
    for value, stems in _TENS:
        for stem in stems:
            if token.startswith(stem):
                rest = token[len(stem):]
                for tail, unit in _TENS_TAIL_TA.items():
                    if rest.startswith(tail):
                        return value + unit
                # Romanized: "irupathanju", or "aruvathi rendu" (the unit is the next word).
                for candidate in (rest, rest[1:]):
                    for unit, forms in _UNIT_WORDS[3:]:
                        if candidate in forms:
                            return value + unit
                return value
    return None


def _magnitude_word(token: str) -> float | None:
    if token in _HUNDRED:
        return 100.0
    for word, factor in _MAGNITUDES.items():
        if token == word or (len(word) > 2 and token.startswith(word)):
            return factor
    return None


def _compound_thousand(token: str) -> float | None:
    """ஐந்தாயிரம், anjaayiram, iruvathaayiram: a number fused with "thousand"."""
    for suffix in _THOUSAND_SUFFIXES:
        position = token.find(suffix)
        if position > 0:
            stem = token[:position]
            value = _THOUSAND_STEMS.get(stem)
            if value is None:
                value = _number_word(stem) or _number_word(stem + "u")
            if value:
                return value * 1000
    return None


def parse_number_words(text: str) -> float | None:
    """Read a number written in words — Tamil script, Tanglish or English.

    Values add within a group and a magnitude word closes the group, so "oru lakh aimbathu
    aayiram" is 1 x 100000 + 50 x 1000. Returns ``None`` when no number word is present,
    so a sentence with no quantity in it is never read as zero.
    """
    total, current, seen = 0.0, 0.0, False
    for token in _fold(text).split():
        compound = _compound_thousand(token)
        if compound is not None:
            total += current + compound
            current, seen = 0.0, True
            continue
        value = _number_word(token)
        if value is not None:
            current += value
            seen = True
            continue
        factor = _magnitude_word(token)
        if factor is not None:
            total += (current or 1) * factor
            current, seen = 0.0, True
    if not seen:
        return None
    return total + current


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

    # A two-month bill: note it, then drop the phrase so its "2" is not read as the figure.
    two_monthly = False
    if "units_per_year" in unit_table and _TWO_MONTHS.search(_fold(normalized)):
        two_monthly = True
        normalized = _TWO_MONTHS.sub(" ", _fold(normalized))

    tokens = _fold(normalized).split()
    match = re.search(r"\d+(?:\.\d+)?", normalized)
    magnitude_applied = False
    if match:
        number = float(match.group(0))
        for word, factor in _MAGNITUDES.items():
            if _mentions(tokens, word):
                number *= factor
                magnitude_applied = True
                break
    else:
        # No digits: a spoken answer. Magnitude words are part of the reading already.
        words = parse_number_words(normalized)
        if words is None:
            return None
        number, magnitude_applied = words, True

    if two_monthly:
        return number * 6

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
        by_state = {state: {k: tuple(v) for k, v in (table or {}).items()}
                    for state, table in (body.get("aliases_by_state") or {}).items()}
        if atype == "enum":
            unknown = set(aliases).union(*(set(t) for t in by_state.values())) - set(domain or ())
            if unknown:
                raise SchemaError(f"{name}: aliases for values outside domain: {sorted(unknown)}")
        elif by_state:
            raise SchemaError(f"{name}: only a category can have state-specific aliases")
        action = body.get("action")
        if action is not None:
            if not isinstance(action, Mapping) or not action.get("text"):
                raise SchemaError(f"{name}: action needs a text")
            if atype not in {"bool", "enum"}:
                raise SchemaError(f"{name}: only yes/no and category facts can have an action")
            outside = set(action.get("from") or ()) - set(domain or ())
            if outside:
                raise SchemaError(f"{name}: action.from values outside domain: {sorted(outside)}")
            action = dict(action)
        if body.get("grows_with_time") and atype != "number":
            raise SchemaError(f"{name}: only a number can grow with time")
        attributes[name] = Attribute(
            name=name,
            type=atype,
            description=(body.get("description") or "").strip(),
            unit=body.get("unit"),
            domain=domain,
            aliases=aliases,
            aliases_by_state=by_state,
            aliases_text=tuple(body.get("aliases_text") or ()),
            derived_from=body.get("derived_from"),
            elicitable=bool(body.get("elicitable", True)),
            sensitivity=body.get("sensitivity", "low"),
            action=action,
            grows_with_time=bool(body.get("grows_with_time", False)),
        )

    derivations = raw.get("derivations") or {}
    for target, spec in derivations.items():
        if target not in attributes:
            raise SchemaError(f"derivation targets unknown attribute {target!r}")
        if spec.get("from") not in attributes:
            raise SchemaError(f"derivation for {target!r} reads unknown attribute {spec.get('from')!r}")
        if "bins" not in spec and "rule" not in spec:
            raise SchemaError(f"derivation for {target!r} needs either 'bins' or 'rule'")

    states = set(attributes["state"].domain or ()) if "state" in attributes else set()
    for name, attr in attributes.items():
        if set(attr.aliases_by_state) - states:
            raise SchemaError(f"{name}: aliases_by_state names states outside `state`: "
                              f"{sorted(set(attr.aliases_by_state) - states)}")
        for other, values in ((attr.action or {}).get("only_if") or {}).items():
            if other not in attributes or not set(values) <= set(attributes[other].domain or ()):
                raise SchemaError(f"{name}: action.only_if names {other!r} or values outside it")

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
