"""Looking past today's list: what a person could unlock, and the family together.

Each view answers its question the same way the rest of the project does — by running the
rule engine on a changed profile — so nothing here is a guess:

- :func:`unlock` asks "what if you did this?" for the facts a person can change by acting
  (``action`` in the vocabulary: open a bank account, get a family card), and "what are
  we still missing?" for the unanswered questions that hold back the most money.
- :func:`household` puts a family's members side by side, counting a per-family scheme
  once however many members qualify for it. What opens with age comes from
  :func:`~tn_schemematch.pack.coming_up`.
"""

from __future__ import annotations

from typing import Any, Mapping

from .attributes import AttributeSpec
from .benefits import group_view, rupees, totals, worth
from .kb import SchemeKB
from .rules import Verdict
from .serialize import label_for, question_text, scheme_summary

def _base(spec: AttributeSpec, profile: Mapping[str, Any]) -> dict[str, Any]:
    """The stated facts only; derived ones are recomputed after every change."""
    return {k: v for k, v in profile.items() if k in spec and not spec[k].is_derived}


def _changed(spec: AttributeSpec, base: Mapping[str, Any],
             changes: Mapping[str, Any]) -> dict[str, Any]:
    profile = {**base, **changes}
    profile.update(spec.derive(profile))
    return profile


def _brief(active: SchemeKB, scheme_ids) -> list[dict[str, Any]]:
    return [scheme_summary(active[i]) for i in sorted(scheme_ids)]


def _money_key(active: SchemeKB, scheme_ids) -> tuple:
    money = totals(active, scheme_ids)
    return (money["yearly"], money["one_time"] + money["in_kind"], len(scheme_ids))


# ------------------------------------------------------------------------- unlock


def unlock(active: SchemeKB, spec: AttributeSpec, profile: Mapping[str, Any], *,
           documents: Any = None, limit: int = 6) -> dict[str, Any]:
    """Things to do and questions to answer, each ranked by the money behind it."""
    now = set(active.match(profile)[Verdict.TRUE])
    base = _base(spec, profile)

    actions = []
    for name, attr in spec.attributes.items():
        if attr.action is None or attr.is_derived:
            continue
        current = profile.get(name)
        if current is None:
            continue  # not known yet: that is a question, below, not an action
        if any(profile.get(other) not in values
               for other, values in (attr.action.get("only_if") or {}).items()):
            continue
        if attr.type == "bool":
            targets = [True] if current is False else []
        else:
            reachable_from = attr.action.get("from")
            if reachable_from and current not in reachable_from:
                continue
            targets = [v for v in attr.domain or () if v != current
                       and v not in (reachable_from or ())]
        gained: set[str] = set()
        for value in targets:
            after = active.match(_changed(spec, base, {name: value}))[Verdict.TRUE]
            gained |= set(after) - now
        if not gained:
            continue
        money = totals(active, gained)
        entry = {
            "attr": name,
            "text": attr.action["text"],
            "document": attr.action.get("document"),
            "online": attr.action.get("online"),
            "schemes": _brief(active, gained),
            "yearly_text": money["yearly_text"],
            "one_time_text": money["one_time_text"],
            "_key": _money_key(active, gained),
        }
        if documents is not None and entry["document"]:
            entry["guide"] = documents.guide(entry["document"], profile.get("state"))
        actions.append(entry)
    actions.sort(key=lambda e: e["_key"], reverse=True)

    # Questions: an unknown fact read by schemes that are still undetermined.
    at_stake: dict[str, set[str]] = {}
    for scheme_id in active.match(profile)[Verdict.UNKNOWN]:
        for pred in active[scheme_id].decide(profile).unknown_predicates():
            if pred.attr in spec and spec[pred.attr].elicitable \
                    and not spec[pred.attr].is_derived:
                at_stake.setdefault(pred.attr, set()).add(scheme_id)
    questions = []
    for name, scheme_ids in at_stake.items():
        money = totals(active, scheme_ids)
        questions.append({
            "attr": name,
            "label": label_for(spec, name),
            "question": question_text(spec[name]),
            "n_schemes": len(scheme_ids),
            "scheme_names": [active[i].name for i in sorted(scheme_ids)],
            "yearly_text": money["yearly_text"],
            "_key": (sum(worth(active[i]) for i in scheme_ids), len(scheme_ids)),
        })
    questions.sort(key=lambda q: q["_key"], reverse=True)

    for entry in actions + questions:
        entry.pop("_key")
    return {"actions": actions[:limit], "questions": questions[:limit]}


# ---------------------------------------------------------------------- household


def household(active: SchemeKB, vault: Any, pid: str, *,
              documents: Any = None) -> dict[str, Any]:
    """Every member of ``pid``'s household, with one total for the family."""
    from .documents import checklist
    from .pack import closing, coming_up

    person = vault.get_profile(pid)
    members = sorted(vault.profiles(person["household"]), key=lambda p: p["created_at"])
    counted_for_family: set[str] = set()
    rows = []
    family = {"yearly": 0.0, "one_time": 0.0, "in_kind": 0.0}
    for member in members:
        profile, _ = vault.profile(member["id"])
        eligible = sorted(active.match(profile)[Verdict.TRUE])
        money = totals(active, eligible, family_counted=counted_for_family)
        for key in family:
            family[key] += money[key]
        opening = coming_up(active, profile, vault.spec)
        ending = closing(active, profile, vault.spec)
        missing = 0
        if documents is not None and eligible:
            held = {d["doc_type"] for d in vault.documents(member["id"])
                    if d["status"] != "unread"}
            missing = len(checklist(documents, active, money["take"], held)["to_collect"])
        rows.append({
            **member,
            "n_eligible": len(eligible),
            "eligible": _brief(active, eligible),
            "yearly_text": money["yearly_text"],
            "one_time_text": money["one_time_text"],
            "shared_with_family": [active[i].name for i in money["shared_with_family"]],
            "only_one_of": group_view(active, money["groups"]),
            "coming_up": [{**row, "name": active[row["id"]].name} for row in opening[:3]],
            "closing": [{**row, "name": active[row["id"]].name} for row in ending[:3]],
            "n_documents_to_collect": missing,
        })
    return {
        "household": person["household"],
        "members": rows,
        "total": {**family,
                  "yearly_text": rupees(family["yearly"]) if family["yearly"] else "",
                  "one_time_text": rupees(family["one_time"]) if family["one_time"] else "",
                  "in_kind_text": rupees(family["in_kind"]) if family["in_kind"] else ""},
    }
