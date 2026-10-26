"""Routes for reaching many people: camps, anonymous reports, partners, and privacy.

Sign-in is the helper API's (:mod:`.helper_api`): camps, reports and the outcome report
are for helpers, and with no ``HELPER_PIN`` set everyone on the machine is one. Each
family's printed page is the application sheet (``/profile/<id>/pack/<scheme>``), so a
camp links to those rather than printing a page of its own.

**Partners** call ``/api/v1/*`` with a key from ``schemematch keys create``.

**Privacy.** Consent is recorded per person against a dated notice; ``/export`` returns
everything held about them; every change to a profile, and every time one is opened, is
written to an audit log by the hook in :func:`register_audit`.
"""

from __future__ import annotations

import re
from functools import wraps
from typing import Any

from flask import Flask, Response, jsonify, render_template, request

from ..helpers import anonymous_report, check_facts, intake_form, person_summary
from ..partners import RateLimiter, authenticate, check
from ..privacy import GIVEN_BY, NOTICE_VERSION, export, notice
from ..serialize import attribute_form, label_for, scheme_summary
from ..vault import VaultError
from .helper_api import claim, is_helper
from .http import error
from .state import AppContext

_PROFILE_PATH = re.compile(r"^/api/profiles/([0-9a-f]{32})(/.*)?$")
_ID = re.compile(r"[0-9a-f]{32}")


def actor(ctx: AppContext) -> str:
    """Who the audit log says did something. With no PIN everyone is a helper, so the
    log says so only when a PIN is actually set."""
    if ctx.auth is not None and ctx.auth.enabled and is_helper(ctx):
        return "helper"
    return "this device"


def register_outreach_api(app: Flask, ctx: AppContext) -> None:
    def helpers_only(view):
        @wraps(view)
        def guarded(*args: Any, **kwargs: Any):
            if not is_helper(ctx):
                return error("login_required", "Log in with the helper PIN to see this.", 401)
            return view(*args, **kwargs)
        return guarded

    def page(template: str, name: str):
        if not is_helper(ctx):
            return render_template("login.html", page=name, helper_link=False)
        return render_template(template, page=name, helper_link=True)

    # -------------------------------------------------------------------- camps

    @app.get("/camp")
    def camp_page():
        return page("camp.html", "camp")

    @app.get("/reports")
    def reports_page():
        return page("reports.html", "reports")

    @app.get("/api/camps")
    @helpers_only
    def list_camps():
        return jsonify({"camps": ctx.vault.camps(), "intake": intake_form(ctx.spec)})

    @app.post("/api/camps")
    @helpers_only
    def create_camp():
        body = request.get_json(silent=True) or {}
        try:
            camp = ctx.vault.create_camp(body.get("name") or "", place=body.get("place") or "",
                                         held_on=body.get("held_on") or None)
        except VaultError as exc:
            return error("bad_camp", str(exc), 400)
        return jsonify(camp), 201

    @app.get("/api/camps/<cid>")
    @helpers_only
    def get_camp(cid: str):
        try:
            camp = ctx.vault.camp(cid)
            members = ctx.vault.camp_members(cid)
        except KeyError:
            return error("no_such_camp", "that camp does not exist", 404)
        return jsonify({"camp": camp, "people": [
            person_summary(ctx.active, ctx.vault, ctx.documents, pid) for pid in members]})

    @app.post("/api/camps/<cid>/people")
    @helpers_only
    def camp_intake(cid: str):
        """Quick intake: a person, a few facts and consent, saved in one step.

        Every fact is checked before anything is written, so a typo cannot leave half a
        person behind.
        """
        body = request.get_json(silent=True) or {}
        try:
            ctx.vault.camp(cid)
        except KeyError:
            return error("no_such_camp", "that camp does not exist", 404)
        if not body.get("consent"):
            return error("consent_required", "Read the notice to the person and record "
                         "their consent before saving.", 400)
        values, errors = check_facts(ctx.spec, body.get("facts") or {})
        if errors:
            return jsonify({"error": {"code": "bad_facts", "message": "Some answers could "
                                      "not be read.", "fields": errors}}), 400
        try:
            person = ctx.vault.create_profile(body.get("name") or "",
                                              relation=body.get("relation") or "",
                                              household=body.get("household_of") or None)
        except KeyError:
            return error("no_such_profile", "that family member does not exist", 404)
        except VaultError as exc:
            return error("bad_profile", str(exc), 400)
        pid = person["id"]
        claim(pid)
        ctx.vault.give_consent(pid, notice=NOTICE_VERSION, lang=body.get("lang") or "en",
                               given_by="helper")
        ctx.vault.record_many(pid, [(attr, value, "form", "") for attr, value in values.items()])
        ctx.vault.add_to_camp(cid, pid)
        ctx.vault.log(actor(ctx), "camp intake", pid, f"camp {cid}")
        return jsonify(person_summary(ctx.active, ctx.vault, ctx.documents, pid)), 201

    # ------------------------------------------------------------------ reports

    @app.get("/api/reports/summary")
    @helpers_only
    def report_summary():
        cid = request.args.get("camp")
        try:
            ids = ctx.vault.camp_members(cid) if cid else ctx.vault.profile_ids()
        except KeyError:
            return error("no_such_camp", "that camp does not exist", 404)
        report = anonymous_report(ctx.active, ctx.vault, ctx.documents, ids)
        report["scope"] = ctx.vault.camp(cid)["name"] if cid else "everyone saved here"
        return jsonify(report)

    # ----------------------------------------------------------------- partners

    limiter = RateLimiter()

    def partner(view):
        @wraps(view)
        def guarded(*args: Any, **kwargs: Any):
            key = authenticate(ctx.vault, request.headers.get("Authorization"))
            if key is None:
                return error("bad_key", "Send a valid key as 'Authorization: Bearer sm_…'.", 401)
            if not limiter.allow(key["id"]):
                return error("rate_limited", "Too many requests; slow down.", 429)
            ctx.vault.touch_api_key(key["id"])
            response = view(*args, **kwargs)
            response.headers["Cache-Control"] = "no-store"
            return response
        return guarded

    @app.post("/api/v1/check")
    @partner
    def partner_check():
        """Facts in, verdicts out. Nothing the partner sends is stored."""
        facts = (request.get_json(silent=True) or {}).get("facts")
        if not isinstance(facts, dict):
            return error("bad_request", "send {\"facts\": {attribute: value, …}}", 400)
        return jsonify(check(ctx.active, ctx.spec, ctx.documents, facts))

    @app.get("/api/v1/schemes")
    @partner
    def partner_schemes():
        return jsonify({"schemes": [scheme_summary(s) for s in ctx.active]})

    @app.get("/api/v1/attributes")
    @partner
    def partner_attributes():
        return jsonify({"attributes": [attribute_form(ctx.spec, n) | {"label": label_for(ctx.spec, n)}
                                       for n in ctx.spec.elicitable_names()]})

    # ------------------------------------------------------------------ privacy

    @app.get("/api/privacy/notice")
    def privacy_notice():
        return jsonify(notice(request.args.get("lang", "en")))

    @app.post("/api/profiles/<pid>/consent")
    def give_consent(pid: str):
        body = request.get_json(silent=True) or {}
        given_by = body.get("given_by") or "self"
        if given_by not in GIVEN_BY:
            return error("bad_request", "given_by must be 'self' or 'helper'", 400)
        try:
            consent = ctx.vault.give_consent(pid, notice=NOTICE_VERSION,
                                             lang=body.get("lang") or "en", given_by=given_by)
        except KeyError:
            return error("no_such_profile", f"no saved profile {pid!r}", 404)
        return jsonify({"consent": consent})

    @app.get("/api/profiles/<pid>/export")
    def export_profile(pid: str):
        """A person's copy of everything held about them (DPDP Act, right to access)."""
        try:
            payload = export(ctx.vault, pid)
        except KeyError:
            return error("no_such_profile", f"no saved profile {pid!r}", 404)
        response = jsonify(payload)
        response.headers["Content-Disposition"] = f'attachment; filename="my-data-{pid[:8]}.json"'
        response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.get("/api/profiles/<pid>/audit")
    def profile_audit(pid: str):
        try:
            ctx.vault.get_profile(pid)
        except KeyError:
            return error("no_such_profile", f"no saved profile {pid!r}", 404)
        return jsonify({"log": ctx.vault.audit_log(pid)})


def register_audit(app: Flask, ctx: AppContext) -> None:
    """Write every change to a saved profile, and every time one is opened, to the log.

    One hook rather than a line in every route, so a route added later cannot forget.
    Only ids and the route are kept — "POST /facts", never the fact.
    """
    @app.after_request
    def audit(response: Response) -> Response:
        match = _PROFILE_PATH.match(request.path)
        if match is None or response.status_code >= 400:
            return response
        pid, rest = match.group(1), _ID.sub(":id", match.group(2) or "/")
        quiet_reads = request.method == "GET" and rest not in {"/", "/export", "/documents/:id/file"}
        if quiet_reads or rest == "/audit":
            return response
        action = {"GET /": "opened profile", "DELETE /": "deleted profile",
                  "GET /export": "downloaded data", "POST /consent": "recorded consent",
                  "GET /documents/:id/file": "viewed a document"}.get(
                      f"{request.method} {rest}", f"{request.method} {rest}")
        detail = ""
        if request.method == "POST" and rest == "/facts":
            detail = str((request.get_json(silent=True) or {}).get("attr") or "")[:60]
        ctx.vault.log(actor(ctx), action, pid, detail)
        return response
