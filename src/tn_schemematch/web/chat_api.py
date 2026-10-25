"""Routes for the assistant: start a chat, send a message, reload a transcript.

A chat is an ordinary :class:`~.state.Session` — same interview state, same save route —
plus the agent's message history. That is why "save my profile" from the chat and from
the interview page are the same request, and why a chat started from a saved profile
skips everything on file.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from .. import DEFAULT_QUESTION_BUDGET
from ..agent import run_turn
from ..agent_tools import AgentContext
from ..serialize import profile_rows
from .http import error
from .state import AppContext, Session

MAX_MESSAGE_CHARS = 2000


def _sync_from_vault(ctx: AppContext, session: Session) -> None:
    """A chat bound to a saved profile reads it fresh each turn, so a document uploaded
    or a fact edited on the profile page is known to the next reply."""
    if not session.profile_id:
        return
    profile, sources = ctx.vault.profile(session.profile_id)
    session.state.profile = dict(profile)
    session.state.sources.update(sources)


def chat_payload(ctx: AppContext, session: Session, *, transcript: bool = True) -> dict[str, Any]:
    state = session.state
    out: dict[str, Any] = {
        "chat_id": session.id,
        "profile_id": session.profile_id,
        "profile_name": (ctx.vault.get_profile(session.profile_id)["name"]
                         if session.profile_id else None),
        "board": ctx.interview.board(state),
        "profile": profile_rows(ctx.spec, state.profile, state.sources),
    }
    if transcript:
        out["transcript"] = session.transcript
    return out


def register_chat_api(app: Flask, ctx: AppContext) -> None:
    def model():
        client = ctx.interview.client
        return client if client is not None and hasattr(client, "converse") else None

    def no_model():
        return error("no_model", "The assistant needs a model that can use tools. This "
                     "server is running rules-only — the Interview page works without one.",
                     503)

    def load(chat_id: str):
        try:
            return ctx.sessions.get(chat_id), None
        except KeyError:
            return None, error("no_such_chat", "That chat has expired or never existed.", 404)

    @app.post("/api/chat")
    def start_chat():
        if model() is None:
            return no_model()
        profile_id = (request.get_json(silent=True) or {}).get("profile_id")
        seed = None
        if profile_id:
            try:
                seed, _ = ctx.vault.profile(profile_id)
            except KeyError:
                return error("no_such_profile", f"no saved profile {profile_id!r}", 404)
        # A conversation can afford the benchmark's full question budget; it is the person
        # who decides when to stop, not a progress bar.
        state = ctx.interview.start("", max_questions=DEFAULT_QUESTION_BUDGET,
                                    use_ai=False, seed_profile=seed)
        session = ctx.sessions.new(state)
        session.profile_id = profile_id
        return jsonify(chat_payload(ctx, session)), 201

    @app.get("/api/chat/<chat_id>")
    def get_chat(chat_id: str):
        session, failure = load(chat_id)
        if failure:
            return failure
        return jsonify(chat_payload(ctx, session))

    @app.post("/api/chat/<chat_id>/message")
    def send_message(chat_id: str):
        client = model()
        if client is None:
            return no_model()
        session, failure = load(chat_id)
        if failure:
            return failure
        text = str((request.get_json(silent=True) or {}).get("text") or "").strip()
        if not text:
            return error("bad_request", "say something first", 400)
        if len(text) > MAX_MESSAGE_CHARS:
            return error("bad_request", f"messages are limited to {MAX_MESSAGE_CHARS} "
                         "characters", 400)
        # One reply at a time per chat: two interleaved turns would corrupt the history.
        if not session.lock.acquire(blocking=False):
            return error("busy", "Still answering the previous message.", 409)
        try:
            _sync_from_vault(ctx, session)
            agent = AgentContext(
                interview=ctx.interview, state=session.state, documents=ctx.documents,
                vault=ctx.vault if session.profile_id else None,
                profile_id=session.profile_id, previous_eligible=session.last_eligible)
            try:
                turn = run_turn(client, agent, session.chat, text)
            except Exception as exc:  # noqa: BLE001 — a failed call is a message, not a 500
                return error("agent_failed", f"The assistant could not answer: "
                             f"{type(exc).__name__}: {exc}", 503)
            session.last_eligible = agent.previous_eligible
            session.transcript.append({"role": "user", "text": text})
            session.transcript.append({"role": "assistant", **turn})
            return jsonify({**turn, **chat_payload(ctx, session, transcript=False)})
        finally:
            session.lock.release()
