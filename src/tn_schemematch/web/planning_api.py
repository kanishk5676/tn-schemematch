"""Routes for looking ahead: the family, what could be unlocked, and what is coming.

Each is a projection of :mod:`..outlook` or :mod:`..pack`, which answer by re-running the
rule engine on a changed profile: "coming up" is :func:`..pack.coming_up` (what opens with
age) with :func:`..pack.closing` (what stops) beside it. Nothing here is stored, so these
are safe to call as often as a page likes.
"""

from __future__ import annotations

from flask import Flask, jsonify

from ..outlook import household, unlock
from ..pack import closing, coming_up
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

        def named(rows):
            return [{**row, "name": ctx.active[row["id"]].name} for row in rows]
        return jsonify({"opens": named(coming_up(ctx.active, profile, ctx.spec)),
                        "closes": named(closing(ctx.active, profile, ctx.spec)),
                        "age_known": profile.get("age") is not None})

    @app.get("/api/profiles/<pid>/household")
    def profile_household(pid: str):
        try:
            return jsonify(household(ctx.active, ctx.vault, pid, documents=ctx.documents))
        except KeyError:
            return missing(pid)
