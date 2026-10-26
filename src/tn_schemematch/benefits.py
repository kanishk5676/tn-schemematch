"""What a set of schemes is worth, and which of them can actually be taken together.

Two questions a list of eligible schemes does not answer on its own:

- **Can I have all of these?** Not always. A destitute 65-year-old in Tamil Nadu qualifies
  for the central old-age pension (IGNOAPS) and the Tamil Nadu old-age pension, but the
  second is the state's own implementation of the first: one pension, not two. Listing
  both sends a person to fill in two forms for one benefit. :func:`resolve` finds such
  groups and keeps the combination worth the most; the others are reported, with the
  source's reason, rather than silently dropped.
- **What is it worth?** :func:`totals` adds up recurring cash per year and one-time
  payments separately — a monthly pension and a marriage grant are not the same kind of
  money — and never adds insurance cover to either, because cover is not cash in hand.

Every figure comes from :class:`~tn_schemematch.kb.BenefitValue`, whose amounts are
checked against the sourced ``benefit_prose``. Amounts are the lowest the source states,
so a total is a floor.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Iterable

from .kb import Scheme, SchemeKB, indian_grouping

_PERIOD_TEXT = {"month": "a month", "year": "a year", "once": "once"}
# Brute force over a group of mutually-exclusive schemes is exact and, at this size, free.
_MAX_GROUP = 12


def rupees(amount: float) -> str:
    return f"₹{indian_grouping(amount)}"


def value_text(scheme: Scheme) -> str:
    """'₹1,000 a month', '₹25,000–50,000 once', 'cover of ₹5,00,000' or ''."""
    if scheme.value:
        value = scheme.value
        figure = rupees(value.amount)
        if value.max:
            figure += f"–{indian_grouping(value.max)}"
        text = f"{figure} {_PERIOD_TEXT[value.per]}"
        if value.in_kind:
            text = f"worth {text}"
        return text + (" per family" if value.per_family else "")
    if scheme.cover:
        return f"cover of {rupees(scheme.cover)}"
    return ""


def worth(scheme: Scheme) -> float:
    """A single number to compare schemes by when only one of them can be taken."""
    if scheme.value:
        return scheme.value.yearly or scheme.value.amount
    return scheme.cover or 0.0


def _preference(kb: SchemeKB, ids: Iterable[str]) -> tuple:
    """Higher worth first; on a tie the state's own scheme, which is usually the one that
    pays (Tamil Nadu pays its pensions with the central share inside). A remaining tie
    keeps the first combination found, so the choice is deterministic."""
    chosen = list(ids)
    return (sum(worth(kb[i]) for i in chosen),
            sum(1 for i in chosen if kb[i].level == "state"))


def resolve(kb: SchemeKB, scheme_ids: Iterable[str]) -> dict[str, Any]:
    """Split eligible schemes into those to take and groups where only some can be.

    Returns ``{"take": [...], "groups": [{"ids", "keep", "drop", "reasons"}]}``. ``take``
    holds every scheme outside a group plus the best compatible choice inside each group.
    """
    ids = sorted(set(scheme_ids) & set(kb.schemes))
    exclusions = kb.exclusions()
    # Connected components of the "cannot combine" graph, restricted to these schemes.
    seen: set[str] = set()
    components: list[list[str]] = []
    for start in ids:
        if start in seen:
            continue
        stack, component = [start], []
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            component.append(node)
            stack.extend(o for o in exclusions.get(node, {}) if o in ids and o not in seen)
        components.append(sorted(component))

    take: list[str] = []
    groups: list[dict[str, Any]] = []
    for component in components:
        if len(component) == 1:
            take.extend(component)
            continue
        best: tuple[str, ...] = ()
        if len(component) <= _MAX_GROUP:
            for size in range(len(component), 0, -1):
                for subset in combinations(component, size):
                    compatible = all(b not in exclusions.get(a, {})
                                     for a, b in combinations(subset, 2))
                    if compatible and (not best or _preference(kb, subset) > _preference(kb, best)):
                        best = subset
        else:  # never reached with today's KB; degrade to the single most valuable scheme
            best = (max(component, key=lambda i: _preference(kb, [i])),)
        take.extend(best)
        reasons = sorted({exclusions[a][b] for a, b in combinations(component, 2)
                          if b in exclusions.get(a, {})})
        groups.append({"ids": component, "keep": sorted(best),
                       "drop": [i for i in component if i not in best], "reasons": reasons})
    return {"take": sorted(take), "groups": groups}


def totals(kb: SchemeKB, scheme_ids: Iterable[str], *,
           family_counted: set[str] | None = None) -> dict[str, Any]:
    """What the schemes a person can take are worth, after :func:`resolve`.

    ``family_counted`` is shared across the members of one household: a per-family
    scheme (PM-KISAN, the women's entitlement) is counted for the first member who
    qualifies and shown, but not added again, for the rest.
    """
    resolved = resolve(kb, scheme_ids)
    yearly = one_time = 0.0
    in_kind = 0.0
    counted, shared, unpriced, covers = [], [], [], []
    for scheme_id in resolved["take"]:
        scheme = kb[scheme_id]
        if scheme.cover:
            covers.append({"id": scheme_id, "cover": scheme.cover})
        if not scheme.value:
            if not scheme.cover:
                unpriced.append(scheme_id)
            continue
        if scheme.value.per_family and family_counted is not None:
            if scheme_id in family_counted:
                shared.append(scheme_id)
                continue
            family_counted.add(scheme_id)
        if scheme.value.in_kind:
            in_kind += scheme.value.amount
        elif scheme.value.yearly is not None:
            yearly += scheme.value.yearly
        else:
            one_time += scheme.value.amount
        counted.append(scheme_id)
    return {
        "yearly": yearly,
        "yearly_text": rupees(yearly) if yearly else "",
        "one_time": one_time,
        "one_time_text": rupees(one_time) if one_time else "",
        "in_kind": in_kind,
        "in_kind_text": rupees(in_kind) if in_kind else "",
        "best_cover": max((c["cover"] for c in covers), default=0.0),
        "counted": counted,
        "shared_with_family": shared,
        "unpriced": unpriced,
        "covers": covers,
        "groups": resolved["groups"],
        "take": resolved["take"],
    }


def group_view(kb: SchemeKB, groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Groups with names, for the browser: 'you can take only one of these'."""
    def brief(scheme_id: str) -> dict[str, Any]:
        scheme = kb[scheme_id]
        return {"id": scheme_id, "name": scheme.name, "value_text": value_text(scheme)}
    return [{"keep": [brief(i) for i in group["keep"]],
             "drop": [brief(i) for i in group["drop"]],
             "reasons": group["reasons"]} for group in groups]
