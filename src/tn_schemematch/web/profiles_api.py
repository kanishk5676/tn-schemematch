"""Routes for saved profiles: people, their facts, and what changed in their eligibility.

Thin, like the rest of the HTTP layer — every route is a projection of :mod:`..vault`.
Errors map one way everywhere: an unknown id is 404 ``no_such_profile``, a write the
vocabulary refuses is 400.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request, send_file

from ..documents import (
    DocumentError,
    apply_reading,
    checklist,
    manual_reading,
    prepare_image,
    read_document,
    unread_reading,
)
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


# ---------------------------------------------------------------------- documents


def held_types(ctx: AppContext, pid: str) -> set[str]:
    """Document types on file for a profile — what the checklist ticks off."""
    return {d["doc_type"] for d in ctx.vault.documents(pid)
            if d["doc_type"] in ctx.documents and d["status"] != "unread"}


def profile_checklist(ctx: AppContext, pid: str,
                      scheme_ids: list[str] | None = None) -> dict[str, Any]:
    if scheme_ids is None:
        result = eligibility(ctx.active, ctx.vault, pid, remember=False)
        scheme_ids = [card["id"] for card in result["eligible"]]
    return checklist(ctx.documents, ctx.active, scheme_ids, held_types(ctx, pid))


def register_document_api(app: Flask, ctx: AppContext) -> None:
    def missing(pid: str):
        return error("no_such_profile", f"no saved profile {pid!r}", 404)

    def reader():
        """The client, if it can read images. CachingClient exposes the capability only
        when the model behind it has it, so one hasattr answers for both."""
        client = ctx.interview.client
        return client if client is not None and hasattr(client, "complete_with_images") else None

    def outcome(pid: str, document: dict[str, Any], reading: dict[str, Any]):
        merged = (apply_reading(ctx.vault, pid, document["id"], reading)
                  if reading["doc_type"] in ctx.documents else
                  {"applied": [], "confirmed": [], "conflicts": []})
        reading["conflicts"] = merged["conflicts"]
        document = ctx.vault.update_document(pid, document["id"], reading=reading)
        return {
            "document": public_document(document),
            "reading": reading,
            **merged,
            "facts": ctx.vault.fact_rows(pid),
            "eligibility": eligibility(ctx.active, ctx.vault, pid),
            "checklist": profile_checklist(ctx, pid),
        }

    @app.get("/api/documents/types")
    def document_types():
        return jsonify({"types": [t.brief() | {"evidences": list(t.evidences)}
                                  for t in ctx.documents.uploadable()],
                        "can_read": reader() is not None})

    @app.post("/api/profiles/<pid>/documents")
    def upload_document(pid: str):
        """Store a photo, read it if a model can, and merge what it says.

        Without a model — or when reading fails — the citizen's own choice of type is
        used, so the checklist still updates. With neither, the file is kept as
        ``unread`` and the page asks what it is.
        """
        try:
            profile = ctx.vault.get_profile(pid)
        except KeyError:
            return missing(pid)
        upload = request.files.get("file")
        if upload is None:
            return error("bad_request", "attach the photo as 'file'", 400)
        chosen = request.form.get("doc_type") or None
        if chosen is not None and (chosen not in ctx.documents
                                   or not ctx.documents[chosen].uploadable):
            return error("bad_document_type", f"unknown document type {chosen!r}", 400)
        try:
            image, media_type, extension = prepare_image(upload.read())
        except DocumentError as exc:
            return error("bad_image", str(exc), exc.status)

        client = reader()
        if client is not None and request.form.get("read", "1") != "0":
            try:
                reading = read_document(client, ctx.spec, ctx.documents, image, media_type,
                                        holder=profile["name"], expected_type=chosen)
                failure = None if reading["doc_type"] != "unknown" else \
                    "the model could not recognise the document"
            except Exception as exc:  # noqa: BLE001 — fall back to the citizen's choice
                reading, failure = unread_reading(), f"{type(exc).__name__}: {exc}"
            if failure is not None:
                reading = (manual_reading(ctx.documents, ctx.spec, chosen, error=failure)
                           if chosen else unread_reading(failure))
        elif chosen:
            reading = manual_reading(ctx.documents, ctx.spec, chosen)
        else:
            return error("needs_type", "No model is available to read the photo, so "
                         "choose what kind of document it is.", 400)
        status = {"model": "read", "manual": "manual"}.get(reading["mode"], "unread")

        document = ctx.vault.add_document(
            pid, doc_type=reading["doc_type"], filename=upload.filename or "photo",
            data=image, media_type=media_type, extension=extension, reading=reading,
            status=status)
        return jsonify(outcome(pid, document, reading)), 201

    @app.post("/api/profiles/<pid>/documents/<doc_id>/type")
    def set_document_type(pid: str, doc_id: str):
        """Correct or supply a document's type by hand. Re-applies its implied facts."""
        doc_type = (request.get_json(silent=True) or {}).get("doc_type")
        try:
            ctx.vault.document(pid, doc_id)
            reading = manual_reading(ctx.documents, ctx.spec, doc_type or "")
        except KeyError:
            return error("no_such_document", "that document does not exist", 404)
        except DocumentError as exc:
            return error("bad_document_type", str(exc), 400)
        document = ctx.vault.update_document(pid, doc_id, doc_type=doc_type,
                                             reading=reading, status="manual")
        return jsonify(outcome(pid, document, reading))

    @app.post("/api/profiles/<pid>/documents/<doc_id>/resolve")
    def resolve_conflict(pid: str, doc_id: str):
        """Settle one disagreement: keep the document's value or the person's own."""
        body = request.get_json(silent=True) or {}
        attr, keep = body.get("attr"), body.get("keep")
        if keep not in {"document", "mine"}:
            return error("bad_request", "'keep' must be 'document' or 'mine'", 400)
        try:
            document = ctx.vault.document(pid, doc_id)
        except KeyError:
            return error("no_such_document", "that document does not exist", 404)
        reading = document["reading"] or {}
        conflict = next((c for c in reading.get("conflicts", []) if c["attr"] == attr), None)
        if conflict is None:
            return error("no_such_conflict", f"no open conflict on {attr!r}", 404)
        if keep == "document":
            ctx.vault.record(pid, attr, conflict["document_value"], source="document",
                             evidence=conflict["evidence"], doc_id=doc_id)
        else:
            ctx.vault.record(pid, attr, conflict["current"], source="confirmed",
                             evidence="kept over a document that disagreed")
        reading["conflicts"] = [c for c in reading["conflicts"] if c["attr"] != attr]
        ctx.vault.update_document(pid, doc_id, reading=reading)
        return jsonify({"resolved": attr, "kept": keep, "facts": ctx.vault.fact_rows(pid),
                        "eligibility": eligibility(ctx.active, ctx.vault, pid)})

    @app.get("/api/profiles/<pid>/documents/<doc_id>/file")
    def document_file(pid: str, doc_id: str):
        try:
            document = ctx.vault.document(pid, doc_id)
        except KeyError:
            return error("no_such_document", "that document does not exist", 404)
        response = send_file(document["stored_path"], mimetype=document["media_type"])
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.delete("/api/profiles/<pid>/documents/<doc_id>")
    def delete_document(pid: str, doc_id: str):
        try:
            ctx.vault.delete_document(pid, doc_id)
        except KeyError:
            return error("no_such_document", "that document does not exist", 404)
        return jsonify({"deleted": doc_id, "checklist": profile_checklist(ctx, pid)})

    @app.get("/api/profiles/<pid>/checklist")
    def get_checklist(pid: str):
        schemes = request.args.get("schemes")
        try:
            return jsonify(profile_checklist(
                ctx, pid, [s for s in schemes.split(",") if s] if schemes else None))
        except KeyError:
            return missing(pid)
