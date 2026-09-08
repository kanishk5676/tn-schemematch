"""TN-SchemeMatch: eligibility matching for Indian welfare schemes under code-mixed queries."""

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
