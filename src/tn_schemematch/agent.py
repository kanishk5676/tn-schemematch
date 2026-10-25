"""The assistant: a conversation that uses tools, and never decides eligibility itself.

The interview page asks the engine's questions one form control at a time. The assistant
holds the same interview as a conversation — in Tamil, English or both — and goes
further: it explains schemes, says which documents to bring, and puts cards, checklists
and upload buttons on screen. It is a model in a loop with nine tools
(:mod:`tn_schemematch.agent_tools`), and each tool is code the rest of the project
already trusts.

Two things keep it honest:

- **It can only reach a verdict through ``check_eligibility``.** The system prompt says
  so, but the stronger guarantee is structural: verdicts exist only in tool results the
  rule engine produced.
- **Every scheme it names is checked after the fact.** :func:`scheme_mentions` finds each
  scheme the reply mentions and attaches the rule engine's verdict for this person. The
  page shows it as a chip beside the text, so a sentence like "you can get the women's
  scheme" next to a red "not eligible" chip is a visible contradiction, not a silent one.

The loop is written out here rather than delegated to an SDK helper for three reasons:
each step is recorded so the page can show what the agent did, steps per message are
capped, and the backend is a protocol (``converse``) so the whole thing runs offline
against a scripted client in tests.

History is append-only. Each response's content goes back exactly as it came, thinking
blocks included; editing an earlier turn would invalidate them.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .agent_tools import AgentContext, ToolError, build_tools, run_tool, summarize
from .kb import SchemeKB
from .rules import Verdict

MAX_STEPS = 8

AGENT_SYSTEM_PROMPT = """\
You are Udhavi (உதவி), an assistant that helps people in Tamil Nadu find the government \
welfare schemes they qualify for and get their documents ready to apply.

A rule engine decides eligibility; you never do. Say someone is eligible for a scheme only \
when check_eligibility lists it as eligible in this conversation. Otherwise say it is not \
confirmed yet. Do not state benefit amounts, rules or required documents from memory: use \
explain_scheme and document_checklist, and say only what they return.

How to hold the conversation:
- Start by calling get_profile, so you never ask for something already known.
- Whenever the person states a fact about themselves, save it with record_facts, quoting \
their words as evidence. If a value is rejected, ask again in simpler words; never invent \
or guess a value.
- To choose what to ask, call next_best_question and ask that question in your own warm, \
simple words. Ask one question per message, and say briefly why it matters (for example \
"this decides 6 schemes"). If they would rather not answer, or do not know, call \
skip_question and move on. Questions about caste, income, health or family are sensitive: \
make clear they can skip them.
- After a few answers, or whenever they ask, call check_eligibility and give a short \
summary: eligible schemes first, then any missed by a single condition.
- Help them prepare. document_checklist says which papers each scheme needs and what is \
already uploaded. Use show to put a scheme card, the checklist, an upload button, a save \
button or a link on their screen instead of describing it at length.
- Reply in the language and script the person uses: Tamil script, Tanglish (Tamil in \
English letters), English, or a mix. Keep replies short — one to four sentences, plain \
words, no tables or long lists.
- The rules are unverified draft data. Before anyone makes a real decision, tell them to \
confirm at an e-Sevai centre or the department office."""


class AgentUnavailable(RuntimeError):
    """The configured client cannot hold a tool-using conversation."""


def _as_param(block: Any) -> dict[str, Any]:
    """A response block as a request param, unchanged apart from dropped nulls."""
    return block.to_dict(exclude_none=True)


def run_turn(client: Any, ctx: AgentContext, history: list[dict[str, Any]], text: str, *,
             max_steps: int = MAX_STEPS) -> dict[str, Any]:
    """Answer one message. Mutates ``history`` (append-only) and ``ctx``.

    Returns the reply text, the steps taken, the schemes the reply mentions with their
    real verdicts, and any UI actions the agent asked for.
    """
    if not hasattr(client, "converse"):
        raise AgentUnavailable("this model backend cannot use tools")
    tools = build_tools(ctx)
    history.append({"role": "user", "content": text})
    steps: list[dict[str, Any]] = []
    reply, capped = "", True

    for _ in range(max_steps):
        response = client.converse(AGENT_SYSTEM_PROMPT, history, tools)
        history.append({"role": "assistant",
                        "content": [_as_param(block) for block in response.content]})
        calls = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason != "tool_use" or not calls:
            reply = "\n\n".join(block.text.strip() for block in response.content
                                if block.type == "text" and block.text.strip())
            capped = False
            break

        results = []
        for call in calls:
            arguments = dict(call.input or {})
            try:
                result, is_error = run_tool(ctx, call.name, arguments), False
            except ToolError as exc:
                result, is_error = {"error": str(exc)}, True
            steps.append({"tool": call.name, "input": arguments, "ok": not is_error,
                          "summary": summarize(call.name, arguments, result)})
            entry = {"type": "tool_result", "tool_use_id": call.id,
                     "content": json.dumps(result, ensure_ascii=False, default=str)}
            if is_error:
                entry["is_error"] = True
            results.append(entry)
        # Every result for one response goes back in a single message.
        history.append({"role": "user", "content": results})

    if capped:
        reply = ("I took too many steps on that one. Could you say it another way? "
                 "/ கொஞ்சம் வேறு மாதிரி சொல்ல முடியுமா?")
    return {
        "reply": reply,
        "steps": steps,
        "capped": capped,
        "mentions": scheme_mentions(reply, ctx.active, ctx.state.profile),
        "ui": list(ctx.ui),
    }


# --------------------------------------------------------------- the guard


def _mention_patterns(active: SchemeKB) -> list[tuple[re.Pattern[str], str]]:
    """Ways a reply can name a scheme: its id, its full English or Tamil name, and the
    acronym in brackets ("PM-KISAN"). ASCII forms must stand alone, so the id "apy" is
    not found inside "happy"."""
    patterns = []
    for scheme in active:
        forms = {scheme.id, scheme.name}
        forms.update(re.findall(r"\(([^)]{2,25})\)", scheme.name))
        for form in sorted(forms, key=len, reverse=True):
            form = form.strip()
            if len(form) < 3:
                continue
            patterns.append((re.compile(r"(?<![\w-])" + re.escape(form) + r"(?![\w-])",
                                        re.IGNORECASE), scheme.id))
        if scheme.name_ta:
            patterns.append((re.compile(re.escape(scheme.name_ta)), scheme.id))
    return patterns


def scheme_mentions(text: str, active: SchemeKB,
                    profile: dict[str, Any]) -> list[dict[str, Any]]:
    """Every scheme a reply names, in order, with the rule engine's verdict for this
    person. This is the check on the model, applied to what it actually said."""
    if not text:
        return []
    patterns = _mention_patterns(active)  # re caches the compiled forms itself
    first_seen: dict[str, int] = {}
    for pattern, scheme_id in patterns:
        match = pattern.search(text)
        if match and (scheme_id not in first_seen or match.start() < first_seen[scheme_id]):
            first_seen[scheme_id] = match.start()
    mentions = []
    for scheme_id in sorted(first_seen, key=first_seen.get):
        verdict = active[scheme_id].verdict(profile)
        mentions.append({"id": scheme_id, "name": active[scheme_id].name,
                         "verdict": verdict.value,
                         "confirmed": verdict is Verdict.TRUE})
    return mentions
