"""Routes for looking ahead: the family, what could be unlocked, and what is coming.

Each is a projection of :mod:`..outlook`, which answers by re-running the rule engine on a
changed profile. Nothing here is stored, so these are safe to call as often as a page
likes.
"""

from __future__ import annotations

from flask import Flask, jsonify

from ..outlook import coming_up, household, unlock
from .http import error
from .state import AppContext


def register_planning_api(app: Flask, ctx: AppContext) -> None:
    def missing(pid: str):
        return error("no_such_profile", f"no saved profile {pid!r}", 404)

    @app.get("/api/profiles/<pid>/unlock")
    def profile_unlock(pid: str):
        try:
            profile, _ = ctx.vault.profile(pid)
        except KeyError:
            return missing(pid)
        return jsonify(unlock(ctx.active, ctx.spec, profile, documents=ctx.documents))

    @app.get("/api/profiles/<pid>/coming-up")
    def profile_coming_up(pid: str):
        try:
            profile, _ = ctx.vault.profile(pid)
        except KeyError:
            return missing(pid)
        return jsonify({"events": coming_up(ctx.active, ctx.spec, profile),
                        "age_known": profile.get("age") is not None})

    @app.get("/api/profiles/<pid>/household")
    def profile_household(pid: str):
        try:
            return jsonify(household(ctx.active, ctx.vault, pid, documents=ctx.documents))
        except KeyError:
            return missing(pid)
