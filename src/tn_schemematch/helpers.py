"""For the people who help many others: camps, printed sheets and anonymous reports.

In a village one person often screens dozens of families in a day — an e-Sevai or Akshaya
operator, an anganwadi worker, an NSS volunteer. They need three things the citizen pages
do not give them:

- **Quick intake.** A handful of facts that decide most schemes (:data:`QUICK_INTAKE`),
  saved as a person in one step and added to the day's camp.
- **Each family's papers to hand over**: the application sheet for every scheme they can
  get (:mod:`.pack`), linked from their line in the camp's queue.
- **A report a panchayat or NGO can see** without seeing anyone (:func:`anonymous_report`):
  counts only, and any count from 1 to 4 shown as "<5", so a small group cannot be picked
  out. Five is the threshold most official small-area statistics use.
"""

from __future__ import annotations

from collections import Counter
from typing import Any, Iterable, Mapping

from .attributes import AttributeSpec, SchemaError
from .benefits import rupees, totals
from .documents import checklist
from .kb import SchemeKB
from .rules import Verdict
from .serialize import attribute_form, label_for

# The facts that settle the most schemes for the least asking, in the order a helper asks
# them; everything else can be added later on the person's profile. Measured, not guessed:
# over the 249 test profiles the first eleven confirm 15% of the eligibilities a full
# profile does, and the next six (chosen greedily by that same count) raise it to 78%.
# The income-tax question adds little there but is asked by every Kerala pension, which
# the mostly Tamil Nadu profiles under-weight.
QUICK_INTAKE = ("state", "district", "age", "gender", "marital_status", "occupation",
                "annual_family_income", "ration_card_type", "land_owned_acres",
                "disability_percent", "social_category",
                "residence_type", "house_ownership", "has_aadhaar", "has_bank_account",
                "is_bpl", "receives_other_pension", "is_income_tax_payer")
SUPPRESS_BELOW = 5


def intake_form(spec: AttributeSpec) -> list[dict[str, Any]]:
    return [attribute_form(spec, name) | {"label": label_for(spec, name)}
            for name in QUICK_INTAKE if name in spec]


def check_facts(spec: AttributeSpec, facts: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Canonicalize a batch of stated facts, state first. Returns (values, errors) — a
    bad value is reported against its attribute, never guessed."""
    values: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for attr, raw in sorted(facts.items(), key=lambda kv: kv[0] != "state"):
        if raw is None or raw == "":
            continue
        if attr not in spec or spec[attr].is_derived or not spec[attr].elicitable:
            errors[attr] = "not something a person states"
            continue
        try:
            values[attr] = spec.canonicalize(attr, raw, context=values)
        except SchemaError as exc:
            errors[attr] = str(exc)
    return values, errors


def _held(vault: Any, pid: str) -> set[str]:
    return {d["doc_type"] for d in vault.documents(pid) if d["status"] != "unread"}


def person_summary(active: SchemeKB, vault: Any, documents: Any, pid: str) -> dict[str, Any]:
    """One line of a camp's queue: who, how many schemes, worth what, what to collect."""
    person = vault.get_profile(pid)
    profile, _ = vault.profile(pid)
    eligible = active.match(profile)[Verdict.TRUE]
    money = totals(active, eligible)
    to_collect = checklist(documents, active, money["take"], _held(vault, pid),
                           state=profile.get("state"))["to_collect"] if documents else []
    return {
        **person,
        "n_eligible": len(eligible),
        "schemes": [{"id": i, "name": active[i].name} for i in money["take"]],
        "yearly_text": money["yearly_text"],
        "one_time_text": money["one_time_text"],
        "documents_to_collect": [entry["label"] for entry in to_collect],
        "n_undetermined": len(active.match(profile)[Verdict.UNKNOWN]),
    }


def _suppress(count: int, k: int) -> int | str:
    return f"<{k}" if 0 < count < k else count


def anonymous_report(active: SchemeKB, vault: Any, documents: Any,
                     profile_ids: Iterable[str], *, k: int = SUPPRESS_BELOW) -> dict[str, Any]:
    """Counts across a group of people, with small counts suppressed.

    The useful number for a panchayat is the gap: people the rules say qualify for a
    scheme who have not applied for it. That is what ``not_applied`` counts.
    """
    ids = list(profile_ids)
    if len(ids) < k:
        return {"n_people": _suppress(len(ids), k), "suppressed": True, "k": k,
                "message": f"Fewer than {k} people — nothing is shown, so no one can be "
                           f"recognised from the numbers."}
    eligible_count: Counter[str] = Counter()
    applied_count: Counter[str] = Counter()
    documents_needed: Counter[str] = Counter()
    districts: Counter[str] = Counter()
    yearly_unclaimed = 0.0
    for pid in ids:
        profile, _ = vault.profile(pid)
        districts[profile.get("district") or "not stated"] += 1
        eligible = active.match(profile)[Verdict.TRUE]
        take = totals(active, eligible)["take"]
        applied = {a["scheme_id"] for a in vault.applications(pid)
                   if a["status"] != "planned"}
        eligible_count.update(take)
        applied_count.update(set(take) & applied)
        unclaimed = [i for i in take if i not in applied]
        yearly_unclaimed += totals(active, unclaimed)["yearly"]
        if documents is not None:
            plan = checklist(documents, active, take, _held(vault, pid), state=profile.get("state"))
            documents_needed.update(entry["label"] for entry in plan["to_collect"])
    schemes = []
    for scheme_id, n in eligible_count.most_common():
        schemes.append({
            "scheme_id": scheme_id, "name": active[scheme_id].name,
            "eligible": _suppress(n, k),
            "applied": _suppress(applied_count[scheme_id], k),
            "not_applied": _suppress(n - applied_count[scheme_id], k),
        })
    return {
        "n_people": len(ids),
        "suppressed": False,
        "k": k,
        "schemes": schemes,
        "documents_needed": [{"label": label, "people": _suppress(n, k)}
                             for label, n in documents_needed.most_common(10)],
        "districts": [{"district": d, "people": _suppress(n, k)}
                      for d, n in districts.most_common()],
        "yearly_unclaimed_text": rupees(yearly_unclaimed) if yearly_unclaimed else "",
    }
