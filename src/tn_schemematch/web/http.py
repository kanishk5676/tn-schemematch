"""The error envelope every API route returns: ``{"error": {"code", "message"}}``.

Shared so the route modules agree on it; the browser's ``api.js`` turns it into a thrown
Error carrying ``code``, and branches on the code rather than the status.
"""

from __future__ import annotations

from flask import jsonify


def error(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status
