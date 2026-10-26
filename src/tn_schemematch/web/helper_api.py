"""Helper mode: a PIN login, the helper's list, and who may see which saved person.

Without a PIN (``HELPER_PIN`` unset) the server behaves as it always has: one machine in
one room, everyone a helper. With a PIN set, saved profiles stop being open to anyone who
knows an id:

- a **helper** logs in with the PIN and sees everyone — the list of families, every
  profile, every application sheet;
- a **citizen** on the assistant sees only the profiles created in their own browser,
  remembered in a signed session cookie; asking for anyone else's is a 401.

The PIN is held only as a salted hash, compared in constant time, and five wrong tries
from one address within ten minutes lock that address out for the rest of the window.
The session cookie is signed with ``SECRET_KEY`` (or a random key per start, which logs
everyone out on restart — safe, if inconvenient).
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict, deque
from typing import Any

from flask import Flask, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

from ..caseload import caseload
from ..vault import VaultError
from .http import error
from .state import AppContext

MAX_TRIES = 5
WINDOW_SECONDS = 600
MAX_OWN = 50

_PROFILE_PATH = re.compile(r"^/(?:api/profiles|profile)/([0-9a-f]{32})(?:/|$)")
# Routes that may name a profile in their JSON body.
_BODY_PROFILE_ROUTES = re.compile(r"^/api/(?:chat|session)(?:/[0-9a-f]{32}/save)?$")


class HelperAuth:
    """A single shared PIN, held as a salted hash."""

    def __init__(self, pin: str | None) -> None:
        pin = (pin or "").strip()
        self._hash = generate_password_hash(pin) if pin else None
        self._failures: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._hash is not None

    def locked_out(self, address: str) -> bool:
        with self._lock:
            tries = self._failures[address]
            while tries and time.time() - tries[0] > WINDOW_SECONDS:
                tries.popleft()
            return len(tries) >= MAX_TRIES

    def check(self, pin: str, address: str) -> bool:
        if not self.enabled:
            return True
        ok = check_password_hash(self._hash, str(pin or ""))
        if not ok:
            with self._lock:
                self._failures[address].append(time.time())
        return ok


# ------------------------------------------------------------------ who may see what


def is_helper(ctx: AppContext) -> bool:
    auth = ctx.auth
    return auth is None or not auth.enabled or session.get("helper") is True


def own_profiles() -> list[str]:
    return list(session.get("own") or [])


def claim(pid: str) -> None:
    """Remember that this browser created ``pid``, so it can keep using it."""
    own = [p for p in own_profiles() if p != pid] + [pid]
    session["own"] = own[-MAX_OWN:]


def can_see(ctx: AppContext, pid: str) -> bool:
    return is_helper(ctx) or pid in own_profiles()


def visible_profiles(ctx: AppContext, profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if is_helper(ctx):
        return profiles
    own = set(own_profiles())
    return [p for p in profiles if p["id"] in own]


# ----------------------------------------------------------------------- routes


def register_helper(app: Flask, ctx: AppContext) -> None:
    def login_required():
        return error("login_required", "Log in with the helper PIN to see this.", 401)

    @app.before_request
    def guard():
        if is_helper(ctx):
            return None
        match = _PROFILE_PATH.match(request.path)
        if match and not can_see(ctx, match.group(1)):
            return login_required()
        if request.path.startswith("/api/helper/") and request.path not in {
                "/api/helper/me", "/api/helper/login", "/api/helper/logout"}:
            return login_required()
        if request.method == "POST" and _BODY_PROFILE_ROUTES.match(request.path):
            pid = (request.get_json(silent=True) or {}).get("profile_id")
            if pid and not can_see(ctx, str(pid)):
                return login_required()
        return None

    @app.get("/api/helper/me")
    def helper_me():
        return jsonify({"pin_required": bool(ctx.auth and ctx.auth.enabled),
                        "helper": is_helper(ctx), "own": own_profiles()})

    @app.post("/api/helper/login")
    def helper_login():
        address = request.remote_addr or "?"
        if ctx.auth is None or not ctx.auth.enabled:
            return jsonify({"helper": True})
        if ctx.auth.locked_out(address):
            return error("too_many_tries", "Too many wrong PINs. Wait ten minutes.", 429)
        pin = (request.get_json(silent=True) or {}).get("pin")
        if not ctx.auth.check(str(pin or ""), address):
            return error("wrong_pin", "That PIN is not right.", 401)
        session["helper"] = True
        session.permanent = False
        return jsonify({"helper": True})

    @app.post("/api/helper/logout")
    def helper_logout():
        session.pop("helper", None)
        return jsonify({"helper": is_helper(ctx)})

    @app.get("/api/helper/overview")
    def helper_overview():
        lang = "en" if request.args.get("lang") == "en" else "ta"
        return jsonify(caseload(ctx.vault, ctx.active, ctx.spec, ctx.documents, lang))

    @app.get("/api/profiles/<pid>/applications")
    def list_applications(pid: str):
        try:
            return jsonify({"applications": ctx.vault.applications(pid)})
        except KeyError:
            return error("no_such_profile", f"no saved profile {pid!r}", 404)

    @app.post("/api/profiles/<pid>/applications")
    def record_application(pid: str):
        """Where an application stands: planned, applied (with date and reference),
        sanctioned or rejected."""
        body = request.get_json(silent=True) or {}
        scheme_id = body.get("scheme_id")
        if scheme_id not in ctx.kb:
            return error("bad_scheme", f"no scheme {scheme_id!r}", 400)
        try:
            row = ctx.vault.set_application(
                pid, scheme_id, status=str(body.get("status") or ""),
                reference=str(body.get("reference") or ""), note=str(body.get("note") or ""),
                applied_on=body.get("applied_on") or None)
        except KeyError:
            return error("no_such_profile", f"no saved profile {pid!r}", 404)
        except VaultError as exc:
            return error("bad_application", str(exc), 400)
        return jsonify(row)

    @app.get("/helper")
    def helper_page():
        return render_template("helper.html", page="helper", helper_link=True)
