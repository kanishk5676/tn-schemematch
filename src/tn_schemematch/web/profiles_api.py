"""Routes for saved profiles: people, their facts, and what changed in their eligibility.

Thin, like the rest of the HTTP layer — every route is a projection of :mod:`..vault`.
Errors map one way everywhere: an unknown id is 404 ``no_such_profile``, a write the
vocabulary refuses is 400.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from ..interview import parse_answer
from ..serialize import format_value
from ..vault import VaultError, eligibility
from .http import error
from .state import AppContext


def public_document(document: dict[str, Any]) -> dict[str, Any]:
    """A document record for the browser: the on-disk path stays on the server."""
    out = {k: v for k, v in document.items() if k != "stored_path"}
    out["file_url"] = f"/api/profiles/{document['profile_id']}/documents/{document['id']}/file"
    return out


def profile_payload(ctx: AppContext, pid: str) -> dict[str, Any]:
    vault = ctx.vault
    return {
        "profile": vault.get_profile(pid),
        "facts": vault.fact_rows(pid),
        "documents": [public_document(d) for d in vault.documents(pid)],
        "household": [p for p in vault.profiles(vault.get_profile(pid)["household"])
                      if p["id"] != pid],
    }


def register_profile_api(app: Flask, ctx: AppContext) -> None:
    def missing(pid: str):
        return error("no_such_profile", f"no saved profile {pid!r}", 404)

    @app.get("/api/profiles")
    def list_profiles():
        return jsonify({"profiles": ctx.vault.profiles()})

    @app.post("/api/profiles")
    def create_profile():
        body = request.get_json(silent=True) or {}
        try:
            profile = ctx.vault.create_profile(
                body.get("name") or "", relation=body.get("relation") or "",
                household=body.get("household_of"))
        except KeyError:
            return missing(body.get("household_of"))
        except VaultError as exc:
            return error("bad_profile", str(exc), 400)
        return jsonify(profile), 201

    @app.get("/api/profiles/<pid>")
    def get_profile(pid: str):
        try:
            return jsonify(profile_payload(ctx, pid))
        except KeyError:
            return missing(pid)

    @app.delete("/api/profiles/<pid>")
    def delete_profile(pid: str):
        try:
            ctx.vault.delete_profile(pid)
        except KeyError:
            return missing(pid)
        return jsonify({"deleted": pid})

    @app.post("/api/profiles/<pid>/facts")
    def record_fact(pid: str):
        """One fact — typed, free text, or ``"value": null`` to retract.

        Answers with the updated profile and the eligibility diff, which is what makes a
        life event visible: change "age" to 60 and the response says what was gained.
        """
        body = request.get_json(silent=True) or {}
        attr = body.get("attr")
        if not attr:
            return error("bad_request", "an 'attr' is required", 400)
        if attr not in ctx.spec:
            return error("bad_attribute", f"unknown attribute {attr!r}", 400)
        try:
            ctx.vault.get_profile(pid)
            if "text" in body:
                value, source = parse_answer(ctx.spec, attr, str(body["text"]),
                                             ctx.interview.client)
                if value is None:
                    return error("unparsed", "Could not read that answer.", 400)
                evidence = str(body["text"])
            elif "value" in body:
                value, source, evidence = body["value"], body.get("source") or "form", ""
                if source not in {"form", "document", "confirmed"}:
                    source = "form"
            else:
                return error("bad_request", "supply either 'value' or 'text'", 400)
            stored = ctx.vault.record(pid, attr, value, source=source, evidence=evidence)
        except KeyError:
            return missing(pid)
        except VaultError as exc:
            code = "derived_attribute" if "derived" in str(exc) else "bad_fact"
            return error(code, str(exc), 400)
        return jsonify({
            "fact": {"attr": attr, "value": stored, "source": source,
                     "display": format_value(ctx.spec, attr, stored)},
            "facts": ctx.vault.fact_rows(pid),
            "eligibility": eligibility(ctx.active, ctx.vault, pid),
        })

    @app.get("/api/profiles/<pid>/eligibility")
    def profile_eligibility(pid: str):
        remember = request.args.get("remember", "1") != "0"
        try:
            return jsonify(eligibility(ctx.active, ctx.vault, pid, remember=remember))
        except KeyError:
            return missing(pid)

    @app.get("/api/profiles/<pid>/history")
    def profile_history(pid: str):
        try:
            return jsonify({"history": ctx.vault.history(pid, request.args.get("attr"))})
        except KeyError:
            return missing(pid)
