"""TN-SchemeMatch (Udhavi): find the welfare schemes a Tamil Nadu family can get, in their own words."""

from .attributes import AttributeSpec, SchemaError, default_spec, load_spec
from .kb import KBError, Scheme, SchemeKB, load_kb, load_scheme, validate_kb
from .rules import Verdict, evaluate, parse_rule

__version__ = "0.1.0"

__all__ = [
    "AttributeSpec",
    "SchemaError",
    "default_spec",
    "load_spec",
    "KBError",
    "Scheme",
    "SchemeKB",
    "load_kb",
    "load_scheme",
    "validate_kb",
    "Verdict",
    "evaluate",
    "parse_rule",
    "__version__",
]

# How many questions a conversation may ask before giving up.
#
# It is a function of the KB, not a taste: it has to cover the *minimal confirming*
# question set, which grows with the number of schemes a person might plausibly qualify
# for. It went 20 -> 40 when the KB went 10 -> 41. Re-derive it, don't guess it —
# tests/test_interview.py runs every test profile at this budget and fails if one
# is left unresolved.
#
# Distinct from the live web interview's budget, which is deliberately shorter (a citizen
# on a screen will not answer forty questions) and honest about the consequence: schemes
# left undetermined are reported as not eligible.
DEFAULT_QUESTION_BUDGET = 40
