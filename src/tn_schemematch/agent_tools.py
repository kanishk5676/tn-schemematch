"""The assistant's tools: thin wrappers over code the rest of the project already trusts.

Each tool is a JSON schema the model sees plus a function that runs here. None of them
lets the model decide anything. ``record_facts`` goes through the same canonicalizer as a
typed answer; ``check_eligibility`` is the rule engine; ``next_best_question`` is the
elicitation policy, so the model chooses the *words* of a question, never which question.
What the model contributes is conversation: understanding a messy reply, phrasing a
question kindly, in Tamil or English, and deciding which tool to call next.

Schemas are ``strict``, so a call always matches its schema; every field is therefore
required, with ``""`` meaning "not given". Attribute and scheme ids are enums, so the
model cannot name one that does not exist — the same guarantee the document reader's
schema gives.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Callable

from .documents import DocumentVocabulary, checklist
from .interview import Interview, InterviewState
from .rules import Verdict
from .serialize import (
    decisive_clauses,
    filter_cards,
    format_value,
    label_for,
    near_misses,
    scheme_summary,
    trace_to_dict,
)


class ToolError(ValueError):
    """A call the tool refuses. Returned to the model as an error result, never raised
    to the user: the model reads the message and tries again or explains."""


@dataclass
class AgentContext:
    """Everything a tool may touch during one turn."""

    interview: Interview
    state: InterviewState
    documents: DocumentVocabulary
    vault: Any = None
    profile_id: str | None = None
    # The eligible set at the previous check_eligibility, for "what changed" answers.
    previous_eligible: list[str] | None = None
    # UI actions requested by ``show`` this turn; the page renders them under the reply.
    ui: list[dict[str, Any]] = field(default_factory=list)

    @property
    def active(self):
        return self.interview.active

    @property
    def spec(self):
        return self.interview.spec

    def held_documents(self) -> set[str]:
        if self.vault is None or self.profile_id is None:
            return set()
        return {d["doc_type"] for d in self.vault.documents(self.profile_id)
                if d["doc_type"] in self.documents and d["status"] != "unread"}


# ---------------------------------------------------------------------- schemas


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def build_tools(ctx: AgentContext) -> list[dict[str, Any]]:
    """Tool definitions for the API. Deterministic in order and content, so the prefix
    they form is identical on every call and stays cached."""
    attrs = sorted(ctx.spec.elicitable_names())
    scheme_ids = sorted(ctx.active.ids())
    doc_types = sorted(t.id for t in ctx.documents.uploadable())

    def tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
        return {"name": name, "description": description, "strict": True,
                "input_schema": _object(properties)}

    return [
        tool("get_profile",
             "What is already known about the person: every fact, where it came from, "
             "and which documents are on file. Call this before asking anything.", {}),
        tool("record_facts",
             "Save facts the person stated. Use the attribute's own values where it has "
             "a fixed list; numbers may keep their units (\"2 acres\", \"8000 a month\"). "
             "Rejected values come back with the allowed values — ask again, never guess.",
             {"facts": {"type": "array", "items": _object({
                 "attr": {"type": "string", "enum": attrs},
                 "value": {"type": "string"},
                 "evidence": {"type": "string",
                              "description": "the person's own words this came from"},
             })}}),
        tool("next_best_question",
             "The single most useful thing to ask next, chosen by the eligibility "
             "engine, with how many schemes it could settle. Ask exactly this.", {}),
        tool("skip_question",
             "Record that the person did not want to answer, or does not know, so it "
             "is never asked again.",
             {"attr": {"type": "string", "enum": attrs}}),
        tool("check_eligibility",
             "The rule engine's current verdicts: eligible schemes, schemes missed by "
             "one condition, and what changed since the last check. The only source of "
             "truth about eligibility.", {}),
        tool("explain_scheme",
             "One scheme in detail: its benefit, the verdict for this person, the "
             "conditions that decided it, the documents it needs, and where to apply.",
             {"scheme_id": {"type": "string", "enum": scheme_ids}}),
        tool("search_schemes",
             "Find schemes by topic (\"widow\", \"fisher\", \"scholarship\"). Returns "
             "matches with this person's verdict for each. For browsing only — it does "
             "not check eligibility.",
             {"query": {"type": "string"},
              "level": {"type": "string", "enum": ["any", "central", "state"]}}),
        tool("document_checklist",
             "The documents each eligible scheme needs, which are already uploaded, and "
             "one list of what to collect, most useful first. Pass a scheme_id for one "
             "scheme, or \"\" for every eligible scheme.",
             {"scheme_id": {"type": "string", "enum": scheme_ids + [""]}}),
        tool("show",
             "Put something on the person's screen under your reply: a scheme card "
             "(scheme_id), the document checklist, an upload button (doc_type, or \"\"), "
             "a button to save their profile, a link to their profile page, or the "
             "scheme browser filtered by query.",
             {"component": {"type": "string", "enum": [
                 "scheme_card", "checklist", "upload_document", "save_profile",
                 "profile_page", "schemes_page"]},
              "scheme_id": {"type": "string", "enum": scheme_ids + [""]},
              "doc_type": {"type": "string", "enum": doc_types + [""]},
              "query": {"type": "string"}}),
    ]


# ---------------------------------------------------------------------- tools


def _allowed(ctx: AgentContext, attr: str) -> str:
    spec_attr = ctx.spec[attr]
    if spec_attr.type == "enum":
        return "one of: " + ", ".join(str(v) for v in spec_attr.domain or ())
    if spec_attr.type == "bool":
        return "yes or no"
    low, high = spec_attr.domain or (None, None)
    return f"a number in {spec_attr.unit or 'units'} between {low:g} and {high:g}"


def get_profile(ctx: AgentContext) -> dict[str, Any]:
    state = ctx.state
    facts = [{"attr": attr, "label": label_for(ctx.spec, attr),
              "value": format_value(ctx.spec, attr, value),
              "source": state.sources.get(attr, "unknown")}
             for attr, value in sorted(state.profile.items())]
    out: dict[str, Any] = {"facts": facts, "n_facts": len(facts),
                           "skipped": list(state.skipped), "profile_saved": False}
    if ctx.vault is not None and ctx.profile_id:
        profile = ctx.vault.get_profile(ctx.profile_id)
        out.update(profile_saved=True, name=profile["name"],
                   documents_on_file=sorted(ctx.held_documents()))
    return out


def record_facts(ctx: AgentContext, facts: list[dict[str, str]]) -> dict[str, Any]:
    accepted, rejected = [], []
    for fact in facts:
        attr, value = fact.get("attr", ""), fact.get("value", "")
        outcome = ctx.interview.answer_value(ctx.state, attr, value, source="chat")
        if outcome.source == "rejected":
            rejected.append({"attr": attr, "value": value, "reason": outcome.message,
                             "allowed": _allowed(ctx, attr) if attr in ctx.spec else None})
            continue
        if ctx.vault is not None and ctx.profile_id:
            ctx.vault.record(ctx.profile_id, attr, outcome.value, source="chat",
                             evidence=fact.get("evidence", ""))
        accepted.append({"attr": attr, "saved_as": format_value(ctx.spec, attr, outcome.value),
                         "schemes_settled": outcome.settled})
    return {"accepted": accepted, "rejected": rejected,
            "saved_to_profile": bool(ctx.vault is not None and ctx.profile_id)}


def next_best_question(ctx: AgentContext) -> dict[str, Any]:
    attr = ctx.interview.next_question(ctx.state)
    if attr is None:
        return {"done": True, "message": "Nothing left to ask: every scheme that can be "
                "settled is settled, or the question budget is used up."}
    question = ctx.interview.question_payload(ctx.state, attr)
    return {
        "done": False, "attr": attr, "question": question["question"],
        "answer_format": question["hint"],
        "could_settle_schemes": question["why"]["settles"],
        "sensitive": question["sensitivity"] == "high",
        "asked_so_far": len(ctx.state.asked), "question_budget": ctx.state.max_questions,
    }


def skip_question(ctx: AgentContext, attr: str) -> dict[str, Any]:
    ctx.interview.skip(ctx.state, attr)
    return {"skipped": attr}


def check_eligibility(ctx: AgentContext) -> dict[str, Any]:
    buckets = ctx.active.match(ctx.state.profile)
    eligible = sorted(buckets[Verdict.TRUE])
    out: dict[str, Any] = {
        "eligible": [{"id": s, "name": ctx.active[s].name,
                      "benefit": (ctx.active[s].benefit_prose or "").strip().split("\n")[0]}
                     for s in eligible],
        "missed_by_one_condition": [
            {"id": m["id"], "name": m["name"], "missing": m["missing"]["human"]}
            for m in near_misses(ctx.active, ctx.state.profile, ctx.spec)],
        "n_ruled_out": len(buckets[Verdict.FALSE]),
        "n_undetermined": len(buckets[Verdict.UNKNOWN]),
        "note": "Undetermined schemes are not eligible until their questions are answered. "
                "All rules are unverified draft data.",
    }
    if ctx.previous_eligible is not None:
        out["changes_since_last_check"] = {
            "gained": [ctx.active[s].name for s in eligible if s not in ctx.previous_eligible],
            "lost": [ctx.active[s].name for s in ctx.previous_eligible
                     if s not in eligible and s in ctx.active]}
    ctx.previous_eligible = eligible
    return out


def explain_scheme(ctx: AgentContext, scheme_id: str) -> dict[str, Any]:
    if scheme_id not in ctx.active:
        raise ToolError(f"no active scheme {scheme_id!r}")
    scheme = ctx.active[scheme_id]
    tree = trace_to_dict(scheme.decide(ctx.state.profile), ctx.spec)
    heading = {"eligible": "conditions_met", "ineligible": "conditions_not_met",
               "undetermined": "still_unknown"}[tree["verdict"]]
    return {
        "id": scheme.id, "name": scheme.name, "name_ta": scheme.name_ta,
        "verdict": tree["verdict"], heading: decisive_clauses(tree),
        "benefit": (scheme.benefit_prose or scheme.summary).strip(),
        "documents": list(scheme.documents), "apply_url": scheme.apply_url,
        "rule_status": "draft, not yet verified against the Government Order",
    }


def search_schemes(ctx: AgentContext, query: str, level: str) -> dict[str, Any]:
    buckets = ctx.active.match(ctx.state.profile)
    verdict = {s: v.value for v, ids in buckets.items() for s in ids}
    cards = filter_cards([scheme_summary(s) for s in ctx.active],
                         level=None if level == "any" else level, query=query)
    return {"n_found": len(cards), "schemes": [
        {"id": c["id"], "name": c["name"], "level": c["level"],
         "summary": c["summary"].strip(), "verdict_for_this_person": verdict[c["id"]]}
        for c in cards[:8]]}


def document_checklist(ctx: AgentContext, scheme_id: str) -> dict[str, Any]:
    if scheme_id:
        scheme_ids = [scheme_id]
    else:
        scheme_ids = sorted(ctx.active.match(ctx.state.profile)[Verdict.TRUE])
    result = checklist(ctx.documents, ctx.active, scheme_ids, ctx.held_documents())
    return {
        "profile_saved": bool(ctx.profile_id),
        "schemes": [{
            "name": s["name"], "ready": s["ready"],
            "have": [i["requirement"] for i in s["items"] if i["status"] == "have"],
            "missing": [i["requirement"] for i in s["items"] if i["status"] == "missing"],
            "at_the_office": [i["requirement"] for i in s["items"] if i["status"] == "action"],
        } for s in result["schemes"]],
        "to_collect": [{"document": e["label"], "needed_for_n_schemes": e["n_schemes"]}
                       for e in result["to_collect"]],
    }


def show(ctx: AgentContext, component: str, scheme_id: str, doc_type: str,
         query: str) -> dict[str, Any]:
    if component == "scheme_card":
        if scheme_id not in ctx.active:
            raise ToolError("scheme_card needs a scheme_id")
        scheme = ctx.active[scheme_id]
        card = scheme_summary(scheme)
        card["trace"] = trace_to_dict(scheme.decide(ctx.state.profile), ctx.spec)
        ctx.ui.append({"type": "scheme", "scheme": card})
    elif component == "checklist":
        ids = ([scheme_id] if scheme_id else
               sorted(ctx.active.match(ctx.state.profile)[Verdict.TRUE]))
        ctx.ui.append({"type": "checklist", "checklist": checklist(
            ctx.documents, ctx.active, ids, ctx.held_documents())})
    elif component == "upload_document":
        ctx.ui.append({"type": "upload", "doc_type": doc_type or None,
                       "label": ctx.documents[doc_type].label if doc_type else None,
                       "needs_profile": not ctx.profile_id})
    elif component == "save_profile":
        ctx.ui.append({"type": "save_profile", "saved": bool(ctx.profile_id)})
    elif component == "profile_page":
        href = f"/profile?id={ctx.profile_id}" if ctx.profile_id else "/profile"
        ctx.ui.append({"type": "link", "href": href, "label": "Open my profile"})
    elif component == "schemes_page":
        ctx.ui.append({"type": "link", "label": "Browse schemes",
                       "href": "/schemes" + (f"?q={query}" if query else "")})
    else:
        raise ToolError(f"unknown component {component!r}")
    return {"shown": component}


TOOLS: dict[str, Callable[..., dict[str, Any]]] = {
    "get_profile": get_profile,
    "record_facts": record_facts,
    "next_best_question": next_best_question,
    "skip_question": skip_question,
    "check_eligibility": check_eligibility,
    "explain_scheme": explain_scheme,
    "search_schemes": search_schemes,
    "document_checklist": document_checklist,
    "show": show,
}


def run_tool(ctx: AgentContext, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Dispatch one call. Unknown tools and bad arguments are ``ToolError``s."""
    function = TOOLS.get(name)
    if function is None:
        raise ToolError(f"no tool named {name!r}")
    try:
        bound = inspect.signature(function).bind(ctx, **(arguments or {}))
    except TypeError as exc:
        raise ToolError(f"bad arguments for {name}: {exc}") from None
    return function(*bound.args, **bound.kwargs)


def summarize(name: str, arguments: dict[str, Any], result: dict[str, Any]) -> str:
    """One line for the page's "agent steps" list."""
    if "error" in result:
        return f"error: {result['error']}"
    if name == "record_facts":
        parts = [f"{a['attr']} = {a['saved_as']}" for a in result["accepted"]]
        parts += [f"✕ {r['attr']}" for r in result["rejected"]]
        return ", ".join(parts) or "nothing recorded"
    if name == "next_best_question":
        return ("nothing left to ask" if result["done"] else
                f"{result['attr']} (could settle {result['could_settle_schemes']})")
    if name == "check_eligibility":
        return (f"{len(result['eligible'])} eligible, "
                f"{len(result['missed_by_one_condition'])} near misses, "
                f"{result['n_undetermined']} undetermined")
    if name == "explain_scheme":
        return f"{result['id']}: {result['verdict']}"
    if name == "search_schemes":
        return f"\"{arguments.get('query', '')}\" → {result['n_found']} found"
    if name == "document_checklist":
        return f"{len(result['to_collect'])} document type(s) to collect"
    if name == "get_profile":
        return f"{result['n_facts']} facts known"
    if name == "skip_question":
        return f"skipped {result['skipped']}"
    if name == "show":
        return f"showing {result['shown'].replace('_', ' ')}"
    return "done"
