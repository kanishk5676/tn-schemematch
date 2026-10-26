"""Routes for the assistant: start a chat, answer, hear the result, switch modes.

A chat is an ordinary :class:`~.state.Session` — same interview state, same save route —
held in one of two modes:

- **agent** — the person speaks freely and a model with tools works out what they meant
  (:mod:`tn_schemematch.agent`). Needs a key and credit.
- **guided** — the assistant asks one question at a time in fixed Tamil or English words
  and the person answers by button, number or voice (:mod:`tn_schemematch.guided`). Needs
  nothing.

A chat starts in guided mode when there is no model or today's budget is spent, and moves
to guided mode by itself — in the middle of a conversation — when the model fails, the
credit runs out or the cap is reached. The person sees one line saying so, never an error.

Every turn that settles anything carries ``spoken``: the result as the rule engine states
it (:mod:`tn_schemematch.spoken`), for the page to read aloud.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from .. import DEFAULT_QUESTION_BUDGET
from ..agent import run_turn
from ..agent_tools import AgentContext
from ..guided import answer as guided_answer
from ..guided import opening as guided_opening
from ..guided import BUTTONS, phrase, question_card
from ..serialize import near_misses, profile_rows
from ..spoken import spoken_result
from ..systems.budget import BudgetExceeded, ModelUnavailable
from .http import error
from .state import AppContext, Session

MAX_MESSAGE_CHARS = 2000
LANGUAGES = ("ta", "en")

AGENT_GREETING = {
    "ta": "வணக்கம்! நான் உதவி. உங்களைப் பற்றிச் சொல்லுங்கள் — வயது, வேலை, குடும்பம், ஊர். உங்களுக்குக் கிடைக்கும் அரசுத் திட்டங்களைக் கண்டுபிடிக்கிறேன்.",
    "en": "Hello! I am Udhavi. Tell me about yourself — your age, work, family and village — and I will find the government schemes you can get.",
}


def _sync_from_vault(ctx: AppContext, session: Session) -> None:
    """A chat bound to a saved profile reads it fresh each turn, so a document uploaded
    or a fact edited on the profile page is known to the next reply."""
    if not session.profile_id:
        return
    profile, sources = ctx.vault.profile(session.profile_id)
    session.state.profile = dict(profile)
    session.state.sources.update(sources)


def _held(ctx: AppContext, session: Session) -> set[str]:
    if not session.profile_id:
        return set()
    return {d["doc_type"] for d in ctx.vault.documents(session.profile_id)
            if d["doc_type"] in ctx.documents and d["status"] != "unread"}


def result_payload(ctx: AppContext, session: Session, lang: str) -> dict[str, Any]:
    """The result as the person hears it, plus the cards it was built from."""
    profile = session.state.profile
    near = [n["id"] for n in near_misses(ctx.active, profile, ctx.spec)]
    return spoken_result(ctx.active, profile, lang, documents=ctx.documents,
                         held=_held(ctx, session), near_ids=near)


def chat_payload(ctx: AppContext, session: Session, *, transcript: bool = True) -> dict[str, Any]:
    state = session.state
    out: dict[str, Any] = {
        "chat_id": session.id,
        "profile_id": session.profile_id,
        "profile_name": (ctx.vault.get_profile(session.profile_id)["name"]
                         if session.profile_id else None),
        "mode": session.mode,
        "lang": session.lang,
        "reason": session.reason,
        "board": ctx.interview.board(state),
        "profile": profile_rows(ctx.spec, state.profile, state.sources),
    }
    if session.mode == "guided":
        attr = ctx.interview.next_question(state)
        out["question"] = (question_card(ctx.questions, ctx.interview, state, attr, session.lang)
                           if attr else None)
        out["done"] = attr is None
    if transcript:
        out["transcript"] = session.transcript
    return out


def register_chat_api(app: Flask, ctx: AppContext) -> None:
    def model():
        """The tool-using client if it can be used right now, and why not if it cannot."""
        client = ctx.interview.client
        if client is None or not hasattr(client, "converse"):
            return None, "no_model"
        meter = getattr(client, "meter", None)
        if meter is not None:
            try:
                meter.check()
            except BudgetExceeded:
                return None, "daily_budget"
        return client, None

    def load(chat_id: str):
        try:
            return ctx.sessions.get(chat_id), None
        except KeyError:
            return None, error("no_such_chat", "That chat has expired or never existed.", 404)

    def language(body: dict[str, Any], session: Session | None = None) -> str:
        lang = body.get("lang") or (session.lang if session else "ta")
        return lang if lang in LANGUAGES else "ta"

    def to_guided(session: Session, reason: str, *, lead: str | None = None) -> dict[str, Any]:
        """Carry on without the model, from wherever the conversation has got to."""
        session.mode, session.reason = "guided", reason
        state = session.state
        attr = ctx.interview.next_question(state)
        lead = lead or phrase("out_of_credit", session.lang)
        if attr is None:
            turn = {"reply": lead, "say": lead, "question": None, "done": True}
        else:
            card = question_card(ctx.questions, ctx.interview, state, attr, session.lang)
            turn = {"reply": f"{lead} {card['text']}", "say": f"{lead} {card['text']}",
                    "question": card, "done": False}
        return turn

    def write_through(session: Session, before: dict[str, Any], text: str, source: str) -> None:
        """A guided answer in a chat bound to a saved profile is saved as it is given."""
        if not session.profile_id:
            return
        for attr, value in session.state.profile.items():
            if ctx.spec[attr].is_derived or before.get(attr) == value:
                continue
            ctx.vault.record(session.profile_id, attr, value, source=source, evidence=text)
            session.state.sources[attr] = source

    @app.post("/api/chat")
    def start_chat():
        body = request.get_json(silent=True) or {}
        profile_id = body.get("profile_id")
        seed = None
        if profile_id:
            try:
                seed, _ = ctx.vault.profile(profile_id)
            except KeyError:
                return error("no_such_profile", f"no saved profile {profile_id!r}", 404)
        # A conversation can afford the full question budget; it is the person who decides
        # when to stop, not a progress bar.
        state = ctx.interview.start("", max_questions=DEFAULT_QUESTION_BUDGET,
                                    use_ai=False, seed_profile=seed)
        session = ctx.sessions.new(state)
        session.profile_id = profile_id
        session.lang = language(body)
        client, why = model()
        if client is None or body.get("mode") == "guided":
            session.mode, session.reason = "guided", why or "chosen"
            turn = guided_opening(ctx.questions, ctx.interview, state, session.lang,
                                  returning=bool(seed))
        else:
            session.mode, session.reason = "agent", None
            greeting = AGENT_GREETING[session.lang]
            turn = {"reply": greeting, "say": greeting, "question": None, "done": False}
        session.transcript.append({"role": "assistant", "text": turn["reply"],
                                   "say": turn["say"], "mode": session.mode})
        return jsonify({**chat_payload(ctx, session), "turn": turn}), 201

    @app.get("/api/chat/<chat_id>")
    def get_chat(chat_id: str):
        session, failure = load(chat_id)
        if failure:
            return failure
        return jsonify(chat_payload(ctx, session))

    @app.get("/api/chat/<chat_id>/result")
    def chat_result(chat_id: str):
        """"What can I get?" at any moment — read from the rules, never from the model."""
        session, failure = load(chat_id)
        if failure:
            return failure
        _sync_from_vault(ctx, session)
        lang = language(dict(request.args), session)
        return jsonify(result_payload(ctx, session, lang))

    @app.post("/api/chat/<chat_id>/mode")
    def switch_mode(chat_id: str):
        session, failure = load(chat_id)
        if failure:
            return failure
        body = request.get_json(silent=True) or {}
        session.lang = language(body, session)
        wanted = body.get("mode")
        if wanted == "guided":
            turn = to_guided(session, "chosen", lead=phrase("ack", session.lang))
        elif wanted == "agent":
            client, why = model()
            if client is None:
                return error(why or "no_model", "The model is not available right now.", 409)
            session.mode, session.reason = "agent", None
            greeting = AGENT_GREETING[session.lang]
            turn = {"reply": greeting, "say": greeting, "question": None, "done": False}
        else:
            return error("bad_request", "mode must be 'agent' or 'guided'", 400)
        session.transcript.append({"role": "assistant", "text": turn["reply"],
                                   "say": turn["say"], "mode": session.mode})
        return jsonify({**chat_payload(ctx, session, transcript=False), "turn": turn})

    @app.post("/api/chat/<chat_id>/message")
    def send_message(chat_id: str):
        session, failure = load(chat_id)
        if failure:
            return failure
        body = request.get_json(silent=True) or {}
        session.lang = language(body, session)
        text = str(body.get("text") or "").strip()
        if len(text) > MAX_MESSAGE_CHARS:
            return error("bad_request", f"messages are limited to {MAX_MESSAGE_CHARS} "
                         "characters", 400)
        if not text and "value" not in body and not body.get("skip"):
            return error("bad_request", "say something first", 400)
        # One reply at a time per chat: two interleaved turns would corrupt the history.
        if not session.lock.acquire(blocking=False):
            return error("busy", "Still answering the previous message.", 409)
        try:
            _sync_from_vault(ctx, session)
            if session.mode == "agent":
                return agent_turn(session, text)
            return guided_turn(session, body, text)
        finally:
            session.lock.release()

    def agent_turn(session: Session, text: str):
        if not text:
            return error("bad_request", "say something first", 400)
        client, why = model()
        notice = None
        if client is not None:
            agent = AgentContext(
                interview=ctx.interview, state=session.state, documents=ctx.documents,
                vault=ctx.vault if session.profile_id else None,
                profile_id=session.profile_id, previous_eligible=session.last_eligible)
            try:
                turn = run_turn(client, agent, session.chat, text)
            except ModelUnavailable as exc:
                why = exc.reason
            except Exception as exc:  # noqa: BLE001 — a failed call is a mode switch, not a 500
                why, notice = "agent_failed", f"{type(exc).__name__}: {exc}"
            else:
                session.last_eligible = agent.previous_eligible
                if any(step["tool"] == "check_eligibility" for step in turn["steps"]):
                    turn["spoken"] = result_payload(ctx, session, session.lang)["text"]
                turn["say"] = turn["reply"]
                session.transcript.append({"role": "user", "text": text})
                session.transcript.append({"role": "assistant", **turn})
                return jsonify({**turn, **chat_payload(ctx, session, transcript=False)})
        # No model, or it just failed: the same conversation carries on in guided mode.
        turn = to_guided(session, why or "no_model")
        session.transcript.append({"role": "user", "text": text})
        session.transcript.append({"role": "assistant", "text": turn["reply"],
                                   "say": turn["say"], "mode": "guided"})
        return jsonify({**turn, "switched": True, "notice": notice,
                        **chat_payload(ctx, session, transcript=False)})

    def guided_turn(session: Session, body: dict[str, Any], text: str):
        state = session.state
        attr = body.get("attr") or ctx.interview.next_question(state)
        if attr is None:
            return jsonify({"reply": phrase("done", session.lang), "question": None,
                            "done": True, "result": result_payload(ctx, session, session.lang),
                            **chat_payload(ctx, session, transcript=False)})
        before = dict(state.profile)
        if body.get("skip"):
            turn = guided_answer(ctx.questions, ctx.interview, state, session.lang,
                                 attr=attr, skip=True)
            said = BUTTONS["skip"][session.lang]
        elif "value" in body and not text:
            turn = guided_answer(ctx.questions, ctx.interview, state, session.lang,
                                 attr=attr, value=body["value"])
            said = str(body.get("label") or body["value"])
        else:
            turn = guided_answer(ctx.questions, ctx.interview, state, session.lang,
                                 attr=attr, text=text)
            said = text
        if turn.get("error") == "stale":
            return error("stale_question", "That question was already answered.", 409)
        write_through(session, before, said, "said" if text else "form")
        if turn["done"]:
            turn["result"] = result_payload(ctx, session, session.lang)
            turn["spoken"] = turn["result"]["text"]
        session.transcript.append({"role": "user", "text": said})
        session.transcript.append({"role": "assistant", "text": turn["reply"],
                                   "say": turn["say"], "mode": "guided"})
        return jsonify({**turn, **chat_payload(ctx, session, transcript=False)})
