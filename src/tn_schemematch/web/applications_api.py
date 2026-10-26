"""Routes around the application tracker: why rejections happen, complaint letters, the
calendar and the outcome report.

The tracker's own routes — listing and recording an application — are the helper API's
(:mod:`.helper_api`); they store the rule engine's verdict with every change, which is what
lets ``/api/outcomes`` find the rejections that contradict the rules.
"""

from __future__ import annotations

from flask import Flask, jsonify, request

from ..applications import calendar, complaint, outcome_report
from ..vault import APPLICATION_STATUSES
from .helper_api import is_helper
from .http import error
from .state import AppContext


def register_application_api(app: Flask, ctx: AppContext) -> None:
    def lang() -> str:
        value = request.args.get("lang", "en")
        return value if value in {"en", "ta", "ml"} else "en"

    @app.get("/api/rejection-reasons")
    def rejection_reasons():
        return jsonify({"reasons": [r.brief(lang()) for r in ctx.rejections.values()],
                        "statuses": list(APPLICATION_STATUSES)})

    @app.get("/api/profiles/<pid>/applications/<scheme_id>/complaint")
    def application_complaint(pid: str, scheme_id: str):
        try:
            person = ctx.vault.get_profile(pid)
            profile, _ = ctx.vault.profile(pid)
            application = next((a for a in ctx.vault.applications(pid)
                                if a["scheme_id"] == scheme_id), None)
        except KeyError:
            return error("no_such_profile", f"no saved profile {pid!r}", 404)
        if application is None or scheme_id not in ctx.kb:
            return error("no_such_application", "nothing is tracked for that scheme", 404)
        return jsonify(complaint(ctx.kb[scheme_id], ctx.spec, profile, person["name"],
                                 application, ctx.rejections, lang=lang()))

    @app.get("/api/profiles/<pid>/calendar")
    def profile_calendar(pid: str):
        try:
            profile, _ = ctx.vault.profile(pid)
            applications = ctx.vault.applications(pid)
        except KeyError:
            return error("no_such_profile", f"no saved profile {pid!r}", 404)
        return jsonify({"items": calendar(ctx.active, ctx.spec, profile, applications)})

    @app.get("/api/outcomes")
    def outcomes():
        """How applications ended, per scheme — counts only, never who. Helpers only."""
        if not is_helper(ctx):
            return error("login_required", "Log in with the helper PIN to see this.", 401)
        return jsonify(outcome_report(ctx.vault.application_events(), ctx.kb, ctx.rejections))
