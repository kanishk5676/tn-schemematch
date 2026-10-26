"""The helper's view: every saved person, and what each one needs next.

In a village one person often helps many — an e-Sevai operator, an anganwadi or ASHA
worker, a panchayat volunteer. What they need is not a list of people but a list of next
steps: who has papers still to collect for a scheme they can get, who is one condition
away from one, whose application has gone quiet, who turns sixty next year. This module
works that out from the vault, with the rule engine deciding every scheme, and sorts the
list so the most actionable person is at the top.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any, Mapping

from .attributes import AttributeSpec
from .documents import DocumentVocabulary, checklist
from .kb import SchemeKB
from .pack import coming_up
from .rules import Verdict
from .serialize import near_misses
from .spoken import spoken_name

# An application with no news for this long is worth a visit to the office.
FOLLOW_UP_DAYS = 30
# How far ahead "coming up" looks on the helper's list.
SOON_YEARS = 2


def _days_since(applied_on: str | None, updated_at: float, today: date) -> int:
    if applied_on:
        try:
            return (today - date.fromisoformat(applied_on)).days
        except ValueError:
            pass
    return int((time.time() - updated_at) // 86400)


def person_row(vault: Any, active: SchemeKB, spec: AttributeSpec,
               documents: DocumentVocabulary, profile_row: Mapping[str, Any], lang: str,
               *, today: date | None = None) -> dict[str, Any]:
    """One person's line on the helper's list."""
    today = today or date.today()
    pid = profile_row["id"]
    profile, _ = vault.profile(pid)
    eligible = sorted(active.match(profile)[Verdict.TRUE])
    held = {d["doc_type"] for d in vault.documents(pid)
            if d["doc_type"] in documents and d["status"] != "unread"}
    plan = checklist(documents, active, eligible, held)
    to_collect = [(e.get("label_ta") if lang == "ta" else None) or e["label"]
                  for e in plan["to_collect"]]
    near = [{"id": n["id"], "name": spoken_name(active[n["id"]], lang),
             "missing": n["missing"]["human"]}
            for n in near_misses(active, profile, spec)]
    soon = [{"id": row["id"], "name": spoken_name(active[row["id"]], lang),
             "in_years": row["in_years"], "at_age": row["at_age"]}
            for row in coming_up(active, profile, spec, years=SOON_YEARS)]
    conflicts = sum(1 for d in vault.documents(pid)
                    if (d["reading"] or {}).get("conflicts"))
    applications = []
    for app in vault.applications(pid):
        days = _days_since(app["applied_on"], app["updated_at"], today)
        applications.append({
            **app,
            "name": spoken_name(active[app["scheme_id"]], lang)
            if app["scheme_id"] in active else app["scheme_id"],
            "days": days,
            "follow_up": app["status"] == "applied" and days >= FOLLOW_UP_DAYS,
        })
    applied = {a["scheme_id"] for a in applications}
    ready = [s["id"] for s in plan["schemes"] if s["ready"] and s["id"] not in applied]
    return {
        **dict(profile_row),
        "eligible": [{"id": sid, "name": spoken_name(active[sid], lang),
                      "applied": sid in applied} for sid in eligible],
        "n_eligible": len(eligible),
        "to_collect": to_collect,
        "ready_to_apply": ready,
        "near": near,
        "soon": soon,
        "conflicts": conflicts,
        "applications": applications,
        "follow_up": [a for a in applications if a["follow_up"]],
        "n_facts": profile_row.get("n_facts", 0),
    }


def _priority(row: Mapping[str, Any]) -> tuple:
    """Most actionable first: a stalled application, a document dispute, papers to
    collect for a scheme they can get, a scheme ready to apply for, one condition away,
    something opening soon. Within a band, the most recently touched first."""
    return (
        not row["follow_up"],
        not row["conflicts"],
        not (row["to_collect"] and row["n_eligible"]),
        not row["ready_to_apply"],
        not row["near"],
        not row["soon"],
        -row.get("updated_at", 0),
    )


def caseload(vault: Any, active: SchemeKB, spec: AttributeSpec,
             documents: DocumentVocabulary, lang: str = "ta", *,
             today: date | None = None) -> dict[str, Any]:
    """Every saved person, most actionable first, with totals for the top of the page."""
    rows = [person_row(vault, active, spec, documents, p, lang, today=today)
            for p in vault.profiles()]
    rows.sort(key=_priority)
    return {
        "people": rows,
        "totals": {
            "people": len(rows),
            "households": len({r["household"] for r in rows}),
            "schemes_found": sum(r["n_eligible"] for r in rows),
            "papers_missing": sum(1 for r in rows if r["to_collect"] and r["n_eligible"]),
            "follow_up": sum(len(r["follow_up"]) for r in rows),
            "applied": sum(1 for r in rows for a in r["applications"]
                           if a["status"] in {"applied", "sanctioned"}),
        },
    }
