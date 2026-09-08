"""The same question, asked of the model directly.

``DirectSystem`` cannot be reused here — it takes a ``Persona`` and drives a simulated
citizen — so this reuses the parts that matter: the prompt the benchmark uses, the scheme
catalogue it sees, and ``coerce_scheme_ids``, which already separates ids that exist from
names the model invented.

What the comparison shows is not that the model is bad. It is that the model cannot show
its work. The grounded column ships a rule trace per scheme; this column ships a list. Any
difference between the two sets is then attributable, and the false positives — schemes
the rules rule out — are the project's headline harm metric made concrete.
"""

from __future__ import annotations

from typing import Any

from ..attributes import AttributeSpec
from ..interview import InterviewState
from ..kb import SchemeKB
from ..rules import Verdict
from ..serialize import format_value, label_for
from ..systems.base import LLMClient, coerce_scheme_ids, parse_json_response, scheme_catalogue
from ..systems.rag_baseline import DIRECT_SYSTEM_PROMPT


def _profile_text(spec: AttributeSpec, state: InterviewState) -> str:
    rows = [
        f"- {label_for(spec, attr)}: {format_value(spec, attr, value)}"
        for attr, value in sorted(state.profile.items())
        if attr in spec and not spec[attr].is_derived
    ]
    return "\n".join(rows) or "(nothing stated)"


def compare_against_direct(client: LLMClient, kb: SchemeKB, spec: AttributeSpec,
                           state: InterviewState) -> dict[str, Any]:
    """Ask the model to name eligible schemes with no rules in the loop."""
    active = kb.active()
    user = "\n".join([
        "SCHEMES:",
        scheme_catalogue(active),
        "",
        f'CITIZEN\'S QUESTION:\n"{state.query}"',
        "",
        "WHAT THEY TOLD US:",
        _profile_text(spec, state),
        "",
        "Answer now with your final JSON. Do not ask questions.",
    ])
    payload = parse_json_response(client.complete(DIRECT_SYSTEM_PROMPT, user, json_mode=True))
    raw = payload.get("eligible_schemes", []) if isinstance(payload, dict) else []
    recognised, hallucinated = coerce_scheme_ids(raw, active)

    grounded = active.eligible_ids(state.profile)
    ruled_out = set(active.match(state.profile)[Verdict.FALSE])

    def card(scheme_id: str) -> dict[str, Any]:
        scheme = active[scheme_id]
        return {"id": scheme.id, "name": scheme.name, "name_ta": scheme.name_ta}

    direct = sorted(set(recognised))
    false_positives = [s for s in direct if s in ruled_out]
    return {
        "grounded": [card(s) for s in grounded],
        "direct": [card(s) for s in direct],
        "agreed": [card(s) for s in direct if s in grounded],
        "false_positives": [card(s) for s in false_positives],
        "missed": [card(s) for s in grounded if s not in direct],
        "hallucinated": hallucinated,
        "reasoning": (payload.get("reasoning") if isinstance(payload, dict) else "") or "",
        "counts": {
            "grounded": len(grounded), "direct": len(direct),
            "false_positives": len(false_positives),
            "missed": len([s for s in grounded if s not in direct]),
            "hallucinated": len(hallucinated),
        },
    }
