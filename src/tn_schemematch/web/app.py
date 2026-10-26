"""The HTTP layer.

Thin by construction: every route is a projection of something the library already
computes. Nothing here decides eligibility, ranks a question, or normalizes a value — it
serializes what :mod:`tn_schemematch.interview` and :mod:`tn_schemematch.serialize`
return. That is the same division of labour the pipeline itself argues for, one level up.

The app factory takes injected ``kb`` / ``spec`` / ``client`` so the whole API can be
tested offline against a ``ScriptedClient``, with no key and no network.
"""

from __future__ import annotations

import json
import os
import secrets
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, redirect, render_template, request

from ..attributes import default_spec
from ..documents import MAX_UPLOAD_BYTES, load_documents
from ..elicitation import resolving_power
from ..interview import Interview
from ..kb import DEFAULT_KB_DIR, load_kb
from ..rules import Verdict
from ..serialize import filter_cards, scheme_detail, scheme_summary
from ..systems.base import LLMClient
from ..vault import DEFAULT_VAULT_DIR, VaultError
from .http import error as _error
from .applications_api import register_application_api
from .chat_api import register_chat_api
from .helper_api import pin_hash, register_audit, register_helper_api
from .planning_api import register_planning_api
from .profiles_api import register_document_api, register_profile_api
from .state import AppContext, SessionStore

# The repo root is derived from the KB's own default, never recomputed here:
# Path(__file__).parent.parent.parent resolves to src/ from this file, not the repo root.
RUNS_DIR = DEFAULT_KB_DIR.parent.parent / "data" / "runs"

SAMPLE_QUERIES = [
    {"label": "Farmer, two acres",
     "query": "enakku ration card irukku, vivasayi, rendu ekkar nilam — enna scheme kedaikum?"},
    {"label": "Widow in Madurai",
     "query": "naan widow, 55 vayasu, Madurai la irukken. enna udhavi kidaikum?"},
    {"label": "Daughter in school",
     "query": "en ponnu 12th padikkira, government school, enna scholarship irukku?"},
    {"label": "Farm worker in Palakkad (Malayalam)",
     "query": "njan oru karshaka thozhilali aanu, 64 vayassu, Palakkad. yellow card und. "
              "kollam 72000 roopa varumanam. pension kittumo?"},
    {"label": "Tailor in Salem (English)",
     "query": "I am a 34 year old tailor in Salem, I have a shop but no land. "
              "What can I apply for?"},
]


def _personas(ctx: AppContext):
    """Load the benchmark on first use only — 247 YAML files is ~0.8s, and most sessions
    never touch it."""
    if getattr(ctx, "_personas", None) is None:
        from ..personas import load_personas
        ctx._personas = load_personas(None, ctx.spec)
    return ctx._personas


def create_app(*, kb=None, spec=None, client: LLMClient | None = None,
               max_questions: int = 15, debug: bool = False,
               vault_dir: str | Path | None = None, documents=None,
               helper_pin: str | None = None) -> Flask:
    app = Flask(__name__)
    app.json.sort_keys = False
    # Signs the helper's session cookie. A fresh one per start signs everyone out on a
    # restart, which is the safe default; set SCHEMEMATCH_SECRET to keep sessions.
    app.secret_key = os.environ.get("SCHEMEMATCH_SECRET") or secrets.token_hex(32)
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    pin = helper_pin if helper_pin is not None else os.environ.get("HELPER_PIN")
    app.config["HELPER_PIN_HASH"] = pin_hash(pin) if pin else None
    # A little over the image limit, so the module's own check answers with a clear message
    # and Flask's 413 only catches what is grossly oversized.
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES + 512 * 1024
    if debug:
        # Otherwise an edited interview.js keeps serving from cache at 1am.
        app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

    spec = spec or default_spec()
    kb = kb if kb is not None else load_kb(None, spec)
    interview = Interview(kb=kb, spec=spec, client=client)

    ctx = AppContext(
        kb=kb, spec=spec, interview=interview,
        sessions=SessionStore(),
        scheme_cards=[scheme_summary(s) for s in kb.active()],
        model_name=getattr(client, "name", None) or "none (rules only)",
        vault_dir=Path(vault_dir) if vault_dir else DEFAULT_VAULT_DIR,
        documents=documents or load_documents(spec),
    )
    app.extensions["schemematch"] = ctx
    app.config["MAX_QUESTIONS"] = max_questions

    _register_pages(app, ctx)
    _register_session_api(app, ctx)
    _register_catalogue_api(app, ctx)
    register_profile_api(app, ctx)
    register_document_api(app, ctx)
    register_chat_api(app, ctx)
    register_planning_api(app, ctx)
    register_helper_api(app, ctx)
    register_application_api(app, ctx)
    register_audit(app, ctx)

    @app.errorhandler(413)
    def too_large(_exc):
        return _error("too_large", "That file is too big — photos must be under 10 MB.", 413)

    return app


# ------------------------------------------------------------------------- helpers


def _turn_payload(ctx: AppContext, session) -> dict[str, Any]:
    """Everything the browser needs to render the next turn."""
    iv, state = ctx.interview, session.state
    attr = iv.next_question(state)
    return {
        "board": iv.board(state),
        "question": iv.question_payload(state, attr) if attr else None,
        "progress": iv.progress(state),
        "done": attr is None,
    }


# --------------------------------------------------------------------------- pages


def _register_pages(app: Flask, ctx: AppContext) -> None:
    def page(template: str, name: str, **extra: Any):
        return render_template(template, model=ctx.model_name, n_schemes=len(ctx.active),
                               page=name, **extra)

    @app.get("/")
    def assistant():
        # Old demo links were /?persona=p001; the replay lives on the interview page now.
        if request.args.get("persona"):
            return redirect(f"/interview?persona={request.args['persona']}")
        return page("assistant.html", "assistant",
                    has_agent=hasattr(ctx.interview.client, "converse"))

    @app.get("/interview")
    def interview_page():
        return page("interview.html", "interview")

    @app.get("/profile")
    def profile_page():
        return page("profile.html", "profile",
                    can_read=hasattr(ctx.interview.client, "complete_with_images"))

    @app.get("/schemes")
    def schemes_page():
        return page("schemes.html", "schemes")

    @app.get("/dashboard")
    def dashboard_page():
        return page("dashboard.html", "dashboard")


# ----------------------------------------------------------------------- interview


def _register_session_api(app: Flask, ctx: AppContext) -> None:
    iv = ctx.interview

    @app.post("/api/session")
    def start_session():
        body = request.get_json(silent=True) or {}
        persona_id = body.get("persona")
        max_questions = int(body.get("max_questions") or app.config["MAX_QUESTIONS"])

        if persona_id:
            # Replay: answer the whole interview from a benchmark persona's true profile.
            # No typing, no model, no network — the rehearsable path when a demo has to
            # work regardless of the room's wifi.
            try:
                persona = _personas(ctx)[persona_id]
            except Exception:
                return _error("bad_persona", f"no persona {persona_id!r}", 404)
            state = iv.start(persona.queries.get("code_mixed", ""),
                             max_questions=max(max_questions, 40), use_ai=False)
            while True:
                attr = iv.next_question(state)
                if attr is None:
                    break
                value = persona.profile.get(attr)
                if value is None:
                    iv.skip(state, attr)
                else:
                    iv.answer_value(state, attr, value)
            state.finished = True
        else:
            # A saved profile seeds the interview, so nothing on file is asked again.
            profile_id = body.get("profile_id")
            seed = None
            if profile_id:
                try:
                    seed, _ = ctx.vault.profile(profile_id)
                except KeyError:
                    return _error("no_such_profile", f"no saved profile {profile_id!r}", 404)
            state = iv.start(
                (body.get("query") or "").strip(),
                max_questions=max_questions,
                use_ai=bool(body.get("use_ai", True)),
                seed_profile=seed,
            )
        session = ctx.sessions.new(state)
        session.profile_id = None if persona_id else body.get("profile_id")
        return jsonify({
            "session_id": session.id,
            "profile_id": session.profile_id,
            "query": state.query,
            # The UI hides model-only affordances rather than offering them and 503ing.
            "has_model": iv.client is not None,
            "extraction": {
                "used_ai": state.used_ai,
                "latency_ms": state.extraction_ms,
                "raw": state.raw_extraction,
                "normalized": [
                    row for row in _profile_rows(ctx, state) if not row["derived"]
                ],
                "derived": [row for row in _profile_rows(ctx, state) if row["derived"]],
                "rejected": state.rejected,
                "error": state.extraction_error,
            },
            **_turn_payload(ctx, session),
        }), 201

    def _profile_rows(ctx: AppContext, state):
        from ..serialize import profile_rows
        return profile_rows(ctx.spec, state.profile, state.sources)

    def _load(session_id: str):
        try:
            return ctx.sessions.get(session_id), None
        except KeyError:
            return None, _error("no_such_session",
                                "That interview has expired or never existed.", 404)

    @app.post("/api/session/<session_id>/answer")
    def answer(session_id: str):
        session, failure = _load(session_id)
        if failure:
            return failure
        body = request.get_json(silent=True) or {}
        attr = body.get("attr")
        if not attr:
            return _error("bad_request", "an 'attr' is required", 400)

        if "text" in body:
            outcome = iv.answer_text(session.state, attr, str(body["text"]))
        elif "value" in body:
            outcome = iv.answer_value(session.state, attr, body["value"])
        else:
            return _error("bad_request", "supply either 'value' or 'text'", 400)

        if outcome.source == "rejected":
            code = ("derived_attribute" if "derived" in (outcome.message or "")
                    else "bad_attribute")
            return _error(code, outcome.message or "rejected", 400)

        from ..serialize import format_value
        return jsonify({
            "accepted": outcome.accepted,
            "attr": outcome.attr,
            "value": outcome.value,
            "display": format_value(ctx.spec, outcome.attr, outcome.value)
            if outcome.value is not None else None,
            "source": outcome.source,
            "settled": outcome.settled,
            "message": outcome.message,
            **_turn_payload(ctx, session),
        })

    @app.post("/api/session/<session_id>/skip")
    def skip(session_id: str):
        session, failure = _load(session_id)
        if failure:
            return failure
        attr = (request.get_json(silent=True) or {}).get("attr")
        if not attr:
            return _error("bad_request", "an 'attr' is required", 400)
        outcome = iv.skip(session.state, attr)
        return jsonify({"accepted": True, "attr": outcome.attr, "source": "skipped",
                        "settled": 0, "message": None, **_turn_payload(ctx, session)})

    @app.post("/api/session/<session_id>/finish")
    @app.get("/api/session/<session_id>/result")
    def result(session_id: str):
        session, failure = _load(session_id)
        if failure:
            return failure
        session.state.finished = True
        return jsonify({"session_id": session.id, **iv.results(session.state)})

    @app.post("/api/session/<session_id>/save")
    def save(session_id: str):
        """Write what this interview learned into a saved profile (new or existing).

        Facts that came *from* the profile are not written back, so saving twice does not
        grow the log with copies; everything else keeps the source it was learned by.
        """
        session, failure = _load(session_id)
        if failure:
            return failure
        body = request.get_json(silent=True) or {}
        pid = body.get("profile_id") or session.profile_id
        state = session.state
        try:
            if pid:
                ctx.vault.get_profile(pid)
            else:
                pid = ctx.vault.create_profile(body.get("name") or "",
                                               relation=body.get("relation") or "")["id"]
            facts = [
                (attr, value, state.sources.get(attr, "form"),
                 state.query if state.sources.get(attr) == "query" else "")
                for attr, value in state.profile.items()
                if not ctx.spec[attr].is_derived and state.sources.get(attr) != "saved"
            ]
            ctx.vault.record_many(pid, facts)
        except KeyError:
            return _error("no_such_profile", f"no saved profile {pid!r}", 404)
        except VaultError as exc:
            return _error("bad_profile", str(exc), 400)
        session.profile_id = pid
        for attr, *_ in facts:
            state.sources[attr] = "saved"
        return jsonify({"profile_id": pid, "saved": len(facts),
                        "profile": ctx.vault.get_profile(pid)})

    @app.get("/api/session/<session_id>/explain/<scheme_id>")
    def explain(session_id: str, scheme_id: str):
        session, failure = _load(session_id)
        if failure:
            return failure
        if scheme_id not in ctx.kb:
            return _error("bad_scheme", f"no scheme {scheme_id!r}", 404)
        if iv.client is None:
            return _error("no_model",
                          "This server is running rules-only, so there is no model to "
                          "phrase an explanation.", 503)

        language = request.args.get("lang") if request.args.get("lang") in {"ta", "ml"} else "en"
        cache_key = f"{scheme_id}:{language}"
        if cache_key not in session.explanations:
            from .explain import explain_trace
            scheme = ctx.kb[scheme_id]
            try:
                session.explanations[cache_key] = explain_trace(
                    iv.client, scheme, scheme.decide(session.state.profile),
                    ctx.spec, language=language)
            except Exception as exc:  # noqa: BLE001
                return _error("explain_failed", f"{type(exc).__name__}: {exc}", 503)
        return jsonify({"scheme_id": scheme_id, "lang": language,
                        "text": session.explanations[cache_key]})

    @app.post("/api/session/<session_id>/compare")
    def compare(session_id: str):
        session, failure = _load(session_id)
        if failure:
            return failure
        if iv.client is None:
            return _error("no_model", "This server is running rules-only.", 503)
        if session.comparison is None:
            from .compare import compare_against_direct
            try:
                session.comparison = compare_against_direct(
                    iv.client, ctx.kb, ctx.spec, session.state)
            except Exception as exc:  # noqa: BLE001
                return _error("compare_failed", f"{type(exc).__name__}: {exc}", 503)
        return jsonify(session.comparison)


# ----------------------------------------------------------------------- catalogue


def _register_catalogue_api(app: Flask, ctx: AppContext) -> None:
    @app.get("/api/samples")
    def samples():
        return jsonify({"samples": SAMPLE_QUERIES})

    @app.get("/api/personas")
    def personas():
        try:
            people = _personas(ctx)
        except Exception as exc:  # noqa: BLE001
            return jsonify({"personas": [], "error": str(exc)})
        chosen = [p for p in people if not p.id.startswith("g")][:8]
        return jsonify({"personas": [
            {"id": p.id, "sketch": p.persona_sketch.strip().splitlines()[0],
             "query": p.queries.get("code_mixed", "")}
            for p in chosen]})

    @app.get("/api/schemes")
    def schemes():
        cards = filter_cards(ctx.scheme_cards, level=request.args.get("level"),
                             sector=request.args.get("sector"), query=request.args.get("q"))
        sectors: dict[str, int] = {}
        for card in ctx.scheme_cards:
            for name in card["sectors"]:
                sectors[name] = sectors.get(name, 0) + 1
        return jsonify({
            "schemes": cards,
            "total": len(ctx.scheme_cards),
            "facets": {
                "levels": sorted({c["level"] for c in ctx.scheme_cards}),
                "sectors": sorted(sectors.items(), key=lambda kv: (-kv[1], kv[0])),
            },
        })

    @app.get("/api/schemes/<scheme_id>")
    def scheme(scheme_id: str):
        if scheme_id not in ctx.kb:
            return _error("bad_scheme", f"no scheme {scheme_id!r}", 404)
        profile: dict[str, Any] = {}
        session_id = request.args.get("session")
        if session_id:
            try:
                profile = ctx.sessions.get(session_id).state.profile
            except KeyError:
                profile = {}
        return jsonify(scheme_detail(ctx.kb[scheme_id], ctx.spec, profile))

    @app.get("/api/stats")
    def stats():
        spec = ctx.spec
        by_type: dict[str, int] = {}
        by_sensitivity: dict[str, int] = {}
        for name in spec.names():
            by_type[spec[name].type] = by_type.get(spec[name].type, 0) + 1
            sens = spec[name].sensitivity
            by_sensitivity[sens] = by_sensitivity.get(sens, 0) + 1

        usage = sorted(ctx.kb.active().attribute_usage().items(),
                       key=lambda kv: (-len(kv[1]), kv[0]))[:20]
        return jsonify({
            "kb": ctx.kb.coverage_report(),
            "model": ctx.model_name,
            "spec": {
                "version": spec.version, "updated": spec.updated,
                "n_attributes": len(spec.names()),
                "n_elicitable": len(spec.elicitable_names()),
                "n_derived": sum(1 for n in spec.names() if spec[n].is_derived),
                "by_type": by_type, "by_sensitivity": by_sensitivity,
            },
            "attribute_usage": [{"attr": a, "n_schemes": len(ids)} for a, ids in usage],
            "runs": _read_runs(),
        })

    @app.get("/api/health")
    def health():
        return jsonify({"ok": True, "schemes": len(ctx.active),
                        "model": ctx.model_name, "sessions": len(ctx.sessions)})


def _read_runs() -> list[dict[str, Any]]:
    """Scored experiment runs, if any exist. A malformed run is skipped, never a 500."""
    runs: list[dict[str, Any]] = []
    if not RUNS_DIR.exists():
        return runs
    for directory in sorted(RUNS_DIR.iterdir(), reverse=True):
        report = directory / "report.json"
        if not report.is_file():
            continue
        try:
            data = json.loads(report.read_text())
        except (OSError, ValueError):
            continue
        rows = []
        for key, metrics in (data.get("summary") or {}).items():
            system, _, condition = key.partition("|")
            rows.append({
                "system": system, "condition": condition,
                "n_runs": metrics.get("n_runs"), "n_errors": metrics.get("n_errors"),
                # Metric names come from eval/runner.summarize; `fpr` and `harmful_fpr`
                # are deliberately reported beside F1 rather than folded into it.
                **{m: (metrics.get(m) or {}).get("mean")
                   for m in ("precision", "recall", "f1", "fpr", "harmful_fpr",
                             "exact_match", "n_questions")},
            })
        runs.append({
            "dir": directory.name,
            "generated": data.get("generated"),
            "metadata": data.get("metadata", {}),
            "systems": rows,
            "rq2": data.get("rq2_codemix_delta") or {},
        })
    return runs
