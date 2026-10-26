"""Routes for the application tracker, rejection reasons, complaints and the calendar.

Every status change stores what the rule engine said at that moment, which is what lets
``/api/outcomes`` find the rejections that contradict the rules.
"""

from __future__ import annotations

from typing import Any

from flask import Flask, jsonify, request

from ..applications import (
    STATUSES,
    ApplicationError,
    calendar,
    clean_reference,
    complaint,
    explain_rejection,
    follow_up,
    outcome_report,
    parse_day,
)
from ..benefits import value_text
from .http import error
from .state import AppContext


def register_application_api(app: Flask, ctx: AppContext) -> None:
    def missing(pid: str):
        return error("no_such_profile", f"no saved profile {pid!r}", 404)

    def no_application():
        return error("no_such_application", "that application does not exist", 404)

    def lang() -> str:
        value = request.args.get("lang", "en")
        return value if value in {"en", "ta", "ml"} else "en"

    def verdict_now(pid: str, scheme_id: str) -> str:
        profile, _ = ctx.vault.profile(pid)
        return ctx.kb[scheme_id].decide(profile).verdict.value

    def decorate(pid: str, application: dict[str, Any]) -> dict[str, Any]:
        scheme = ctx.kb[application["scheme_id"]] if application["scheme_id"] in ctx.kb else None
        out = {**application,
               "scheme": {"id": application["scheme_id"],
                          "name": scheme.name if scheme else application["scheme_id"],
                          "name_ta": scheme.name_ta if scheme else "",
                          "value_text": value_text(scheme) if scheme else "",
                          "apply_url": scheme.apply_url if scheme else ""},
               "follow_up": follow_up(application)}
        last = application["events"][-1]
        if scheme and application["status"] == "rejected":
            reason = ctx.rejections.get(last.get("reason") or "other") or ctx.rejections["other"]
            profile, _ = ctx.vault.profile(pid)
            out["rejection"] = explain_rejection(scheme, ctx.spec, profile, reason,
                                                 documents=ctx.documents, lang=lang())
        out["can_complain"] = bool(scheme) and (
            out["follow_up"] is not None
            or (application["status"] == "rejected" and out["rejection"]["appeal"]))
        return out

    @app.get("/api/rejection-reasons")
    def rejection_reasons():
        return jsonify({"reasons": [r.brief(lang()) for r in ctx.rejections.values()],
                        "statuses": list(STATUSES)})

    @app.get("/api/profiles/<pid>/applications")
    def list_applications(pid: str):
        try:
            return jsonify({"applications": [decorate(pid, a)
                                             for a in ctx.vault.applications(pid)]})
        except KeyError:
            return missing(pid)

    @app.post("/api/profiles/<pid>/applications")
    def open_application(pid: str):
        body = request.get_json(silent=True) or {}
        scheme_id = body.get("scheme_id")
        if scheme_id not in ctx.kb:
            return error("bad_scheme", f"no scheme {scheme_id!r}", 404)
        status = body.get("status") or "applied"
        if status not in {"planned", "applied"}:
            return error("bad_status", "a new application is 'planned' or 'applied'", 400)
        try:
            application = ctx.vault.open_application(
                pid, scheme_id, status=status, verdict=verdict_now(pid, scheme_id),
                on_date=parse_day(body.get("on_date")),
                reference=clean_reference(body.get("reference") or ""),
                office=str(body.get("office") or "").strip(), note=str(body.get("note") or ""))
        except KeyError:
            return missing(pid)
        except ApplicationError as exc:
            return error("bad_date", str(exc), 400)
        return jsonify(decorate(pid, application)), 201

    @app.post("/api/profiles/<pid>/applications/<aid>/status")
    def set_status(pid: str, aid: str):
        """A new status. A rejection needs a reason, so it can be explained and counted."""
        body = request.get_json(silent=True) or {}
        status = body.get("status")
        if status not in STATUSES:
            return error("bad_status", f"status must be one of {', '.join(STATUSES)}", 400)
        reason = body.get("reason") or None
        if status == "rejected":
            reason = reason or "no_reason_given"
            if reason not in ctx.rejections:
                return error("bad_reason", f"unknown rejection reason {reason!r}", 400)
        elif reason:
            return error("bad_reason", "only a rejection takes a reason", 400)
        try:
            current = ctx.vault.application(pid, aid)
            application = ctx.vault.add_application_event(
                pid, aid, status=status, reason=reason,
                verdict=verdict_now(pid, current["scheme_id"]) if current["scheme_id"] in ctx.kb
                else "undetermined",
                on_date=parse_day(body.get("on_date")), note=str(body.get("note") or ""))
        except KeyError:
            return no_application()
        except ApplicationError as exc:
            return error("bad_date", str(exc), 400)
        return jsonify(decorate(pid, application))

    @app.delete("/api/profiles/<pid>/applications/<aid>")
    def delete_application(pid: str, aid: str):
        try:
            ctx.vault.delete_application(pid, aid)
        except KeyError:
            return no_application()
        return jsonify({"deleted": aid})

    @app.get("/api/profiles/<pid>/applications/<aid>/complaint")
    def application_complaint(pid: str, aid: str):
        try:
            application = ctx.vault.application(pid, aid)
            person = ctx.vault.get_profile(pid)
            profile, _ = ctx.vault.profile(pid)
        except KeyError:
            return no_application()
        if application["scheme_id"] not in ctx.kb:
            return error("bad_scheme", "that scheme is no longer in the knowledge base", 404)
        return jsonify(complaint(ctx.kb[application["scheme_id"]], ctx.spec, profile,
                                 person["name"], application, ctx.rejections, lang=lang()))

    @app.get("/api/profiles/<pid>/calendar")
    def profile_calendar(pid: str):
        try:
            profile, _ = ctx.vault.profile(pid)
            applications = ctx.vault.applications(pid)
        except KeyError:
            return missing(pid)
        return jsonify({"items": calendar(ctx.active, ctx.spec, profile, applications)})

    @app.get("/api/outcomes")
    @app.config["HELPER_ONLY"]
    def outcomes():
        """How applications ended, per scheme — counts only, never who."""
        return jsonify(outcome_report(ctx.vault.application_events(), ctx.kb, ctx.rejections))
