"""The partner API: other organisations' apps asking the rule engine, keyed and stateless.

An NGO with its own field app should not have to copy forty rule files to know who
qualifies. :func:`check` answers one question — "given these facts, what?" — and stores
nothing: the facts a partner sends are evaluated and dropped. What is kept is only that a
key was used, so a misbehaving key can be seen and revoked.

Keys are shown once when created and stored only as a SHA-256 hash, like a password: a
copy of the vault does not give anyone a working key.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import deque
from typing import Any, Mapping

from .attributes import AttributeSpec
from .benefits import group_view, totals
from .documents import checklist
from .helpers import check_facts
from .kb import SchemeKB
from .outlook import unlock
from .rules import Verdict
from .serialize import near_misses, scheme_summary

KEY_PREFIX = "sm_"
RATE_LIMIT = 60          # requests
RATE_WINDOW = 60.0       # seconds


def new_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(24)


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def create_key(vault: Any, name: str) -> tuple[dict[str, Any], str]:
    """A new key for ``name``. The plaintext is returned once and never stored."""
    name = (name or "").strip()
    if not name:
        raise ValueError("a key needs the name of who it is for")
    key = new_key()
    return vault.add_api_key(name, key_hash(key)), key


def authenticate(vault: Any, header: str | None) -> dict[str, Any] | None:
    """The key record for an ``Authorization: Bearer …`` header, or ``None``."""
    if not header or not header.startswith("Bearer "):
        return None
    key = header[len("Bearer "):].strip()
    if not key.startswith(KEY_PREFIX):
        return None
    record = vault.api_key_by_hash(key_hash(key))
    if record is None or record["revoked_at"] is not None:
        return None
    return record


class RateLimiter:
    """A sliding window per key. In memory, so a restart forgets — fine for a limit whose
    job is to stop a runaway loop, not to bill anyone."""

    def __init__(self, limit: int = RATE_LIMIT, window: float = RATE_WINDOW) -> None:
        self.limit, self.window = limit, window
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key_id: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key_id, deque())
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


def check(active: SchemeKB, spec: AttributeSpec, documents: Any,
          facts: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate a set of facts and return everything the citizen pages would show."""
    values, errors = check_facts(spec, facts)
    profile = {**values, **spec.derive(values)}
    buckets = active.match(profile)
    money = totals(active, buckets[Verdict.TRUE])
    plan = (checklist(documents, active, money["take"], [], state=profile.get("state"))
            if documents is not None else None)
    return {
        "understood": values,
        "not_understood": errors,
        "eligible": [scheme_summary(active[i]) for i in buckets[Verdict.TRUE]],
        "only_one_of": group_view(active, money["groups"]),
        "money": {k: money[k] for k in ("yearly", "yearly_text", "one_time", "one_time_text",
                                         "best_cover")},
        "near_misses": near_misses(active, profile, spec),
        "n_undetermined": len(buckets[Verdict.UNKNOWN]),
        "ask_next": unlock(active, spec, profile, limit=5)["questions"],
        "documents": plan["to_collect"] if plan else [],
        "notice": "Rules are unverified draft data. Confirm at the office before applying.",
    }
