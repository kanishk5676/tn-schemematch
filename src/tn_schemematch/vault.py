"""Saved citizen profiles: answer once, reuse everywhere.

An interview forgets everything when the tab closes, so a citizen who comes back next month
— or whose daughter starts college, or who turns sixty — starts from nothing. The vault is
the memory that fixes that. It holds people (grouped into households), every fact they
have stated, and the documents they have uploaded.

Three decisions shape it:

- **Facts are an append-only log, not a row of columns.** Each fact records where it came
  from (said in the query, picked on a form, read off a document) and when. The current
  profile is simply the latest fact per attribute; a ``None`` value retracts one. So the
  question "why does the system think my income is 72,000?" always has an answer, and a
  life event is a new fact rather than an edit that destroys the old one.
- **The vault enforces the same invariants as the interview.** Only elicitable attributes
  are accepted, every value goes through ``spec.canonicalize``, and derived attributes are
  recomputed on read, never stored. Nothing written here can contradict the vocabulary.
- **Eligibility is remembered as a set of ids, so a re-check can say what changed.**
  "You gained the old-age pension; you lost the student scholarship" is more useful after a
  birthday than a fresh list of eight schemes.

Storage is a single SQLite file under ``data/vault/`` (git-ignored) plus uploaded files
beside it. It is local by design: nothing here leaves the machine the server runs on.
There is no authentication — a profile id is a bearer token, like a session id — which is
acceptable for a server bound to 127.0.0.1 and stated, not hidden, in the README.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping

from .attributes import AttributeSpec, SchemaError
from .kb import DEFAULT_KB_DIR, SchemeKB
from .rules import Verdict
from .serialize import board, format_value, label_for, near_misses, scheme_summary

DEFAULT_VAULT_DIR = DEFAULT_KB_DIR.parent.parent / "data" / "vault"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS profiles (
    id            TEXT PRIMARY KEY,
    household     TEXT NOT NULL,
    name          TEXT NOT NULL,
    relation      TEXT NOT NULL DEFAULT '',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    last_eligible TEXT
);
CREATE TABLE IF NOT EXISTS facts (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    attr        TEXT NOT NULL,
    value       TEXT,
    source      TEXT NOT NULL,
    evidence    TEXT NOT NULL DEFAULT '',
    doc_id      TEXT,
    recorded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS facts_by_profile ON facts (profile_id, attr, seq);
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    doc_type    TEXT NOT NULL,
    filename    TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    media_type  TEXT NOT NULL,
    reading     TEXT,
    status      TEXT NOT NULL,
    uploaded_at REAL NOT NULL
);
"""

MAX_NAME_LENGTH = 80


class VaultError(ValueError):
    """A write the vocabulary does not allow. Maps to HTTP 400."""


class Vault:
    """A lock-guarded SQLite store. Unknown ids raise ``KeyError`` (HTTP 404)."""

    def __init__(self, root: str | Path, spec: AttributeSpec) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.files_dir = self.root / "files"
        self.spec = spec
        # Flask's dev server is threaded; one connection behind one lock is simpler and
        # entirely fast enough for a server with a handful of people on it.
        self._db = sqlite3.connect(str(self.root / "vault.db"), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ------------------------------------------------------------------ profiles

    def create_profile(self, name: str, *, household: str | None = None,
                       relation: str = "") -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise VaultError("a profile needs a name")
        if len(name) > MAX_NAME_LENGTH:
            raise VaultError(f"name longer than {MAX_NAME_LENGTH} characters")
        if household is not None:
            self.get_profile(household)  # joining a household means naming a member of it
            household = self._row("SELECT household FROM profiles WHERE id = ?",
                                  household)["household"]
        pid = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO profiles (id, household, name, relation, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (pid, household or pid, name, (relation or "").strip()[:40], now, now))
        return self.get_profile(pid)

    def get_profile(self, pid: str) -> dict[str, Any]:
        row = self._row(
            "SELECT p.*, (SELECT COUNT(DISTINCT attr) FROM facts WHERE profile_id = p.id)"
            " AS n_facts, (SELECT COUNT(*) FROM documents WHERE profile_id = p.id)"
            " AS n_documents FROM profiles p WHERE p.id = ?", pid)
        return _profile_dict(row)

    def profiles(self, household: str | None = None) -> list[dict[str, Any]]:
        query = ("SELECT p.*, (SELECT COUNT(DISTINCT attr) FROM facts WHERE profile_id = p.id)"
                 " AS n_facts, (SELECT COUNT(*) FROM documents WHERE profile_id = p.id)"
                 " AS n_documents FROM profiles p")
        args: tuple[Any, ...] = ()
        if household:
            query += " WHERE p.household = ?"
            args = (household,)
        with self._lock:
            rows = self._db.execute(query + " ORDER BY p.updated_at DESC", args).fetchall()
        return [_profile_dict(row) for row in rows]

    def delete_profile(self, pid: str) -> None:
        """Delete a person, every fact about them, and every file they uploaded."""
        self.get_profile(pid)
        with self._lock, self._db:
            self._db.execute("DELETE FROM profiles WHERE id = ?", (pid,))
        shutil.rmtree(self.files_dir / pid, ignore_errors=True)

    # --------------------------------------------------------------------- facts

    def record(self, pid: str, attr: str, value: Any, *, source: str,
               evidence: str = "", doc_id: str | None = None) -> Any:
        """Append one fact and return its canonical value. ``None`` retracts the fact."""
        self.get_profile(pid)
        canonical = self._canonical(attr, value)
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO facts (profile_id, attr, value, source, evidence, doc_id,"
                " recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (pid, attr, None if canonical is None else json.dumps(canonical),
                 source, (evidence or "")[:500], doc_id, now))
            self._db.execute("UPDATE profiles SET updated_at = ? WHERE id = ?", (now, pid))
        return canonical

    def record_many(self, pid: str,
                    facts: Iterable[tuple[str, Any, str, str]]) -> dict[str, Any]:
        """Record (attr, value, source, evidence) tuples; all are validated before any is
        written, so a bad fact in the middle cannot leave a half-saved profile."""
        rows = [(attr, self._canonical(attr, value), source, evidence)
                for attr, value, source, evidence in facts]
        written: dict[str, Any] = {}
        for attr, value, source, evidence in rows:
            written[attr] = self.record(pid, attr, value, source=source, evidence=evidence)
        return written

    def _canonical(self, attr: str, value: Any) -> Any:
        if attr not in self.spec:
            raise VaultError(f"unknown attribute {attr!r}")
        if self.spec[attr].is_derived:
            raise VaultError(f"{attr} is derived from other answers and cannot be stored")
        if not self.spec[attr].elicitable:
            raise VaultError(f"{attr} is not something a citizen states")
        if value is None:
            return None
        try:
            return self.spec.canonicalize(attr, value)
        except SchemaError as exc:
            raise VaultError(str(exc)) from None

    def _latest(self, pid: str) -> dict[str, sqlite3.Row]:
        self.get_profile(pid)
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM facts WHERE profile_id = ? ORDER BY seq", (pid,)).fetchall()
        latest: dict[str, sqlite3.Row] = {}
        for row in rows:
            latest[row["attr"]] = row
        return {attr: row for attr, row in latest.items() if row["value"] is not None}

    def profile(self, pid: str) -> tuple[dict[str, Any], dict[str, str]]:
        """The current profile (derived attributes filled in) and each value's source."""
        latest = self._latest(pid)
        profile = {attr: json.loads(row["value"]) for attr, row in latest.items()}
        sources = {attr: row["source"] for attr, row in latest.items()}
        derived = self.spec.derive(profile)
        profile.update(derived)
        sources.update({name: "derived" for name in derived})
        return profile, sources

    def fact_rows(self, pid: str) -> list[dict[str, Any]]:
        """The current profile as display rows, each with its provenance."""
        latest = self._latest(pid)
        profile, sources = self.profile(pid)
        rows = []
        for attr in sorted(profile):
            row = latest.get(attr)
            rows.append({
                "attr": attr,
                "label": label_for(self.spec, attr),
                "value": profile[attr],
                "display": format_value(self.spec, attr, profile[attr]),
                "derived": self.spec[attr].is_derived,
                "source": sources[attr],
                "evidence": row["evidence"] if row else "",
                "doc_id": row["doc_id"] if row else None,
                "recorded_at": row["recorded_at"] if row else None,
                "sensitivity": self.spec[attr].sensitivity,
            })
        return rows

    def history(self, pid: str, attr: str | None = None) -> list[dict[str, Any]]:
        self.get_profile(pid)
        query, args = "SELECT * FROM facts WHERE profile_id = ?", [pid]
        if attr:
            query += " AND attr = ?"
            args.append(attr)
        with self._lock:
            rows = self._db.execute(query + " ORDER BY seq", args).fetchall()
        return [{
            "attr": row["attr"],
            "value": None if row["value"] is None else json.loads(row["value"]),
            "source": row["source"],
            "evidence": row["evidence"],
            "doc_id": row["doc_id"],
            "recorded_at": row["recorded_at"],
        } for row in rows]

    # ----------------------------------------------------------------- documents

    def add_document(self, pid: str, *, doc_type: str, filename: str, data: bytes,
                     media_type: str, extension: str, reading: Mapping[str, Any] | None = None,
                     status: str = "stored") -> dict[str, Any]:
        self.get_profile(pid)
        doc_id = uuid.uuid4().hex
        directory = self.files_dir / pid
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{doc_id}.{extension}"
        path.write_bytes(data)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO documents (id, profile_id, doc_type, filename, stored_path,"
                " media_type, reading, status, uploaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (doc_id, pid, doc_type, (filename or "upload")[:120], str(path), media_type,
                 json.dumps(reading, ensure_ascii=False) if reading is not None else None,
                 status, time.time()))
        return self.document(pid, doc_id)

    def update_document(self, pid: str, doc_id: str, *, doc_type: str | None = None,
                        reading: Mapping[str, Any] | None = None,
                        status: str | None = None) -> dict[str, Any]:
        current = self.document(pid, doc_id)
        with self._lock, self._db:
            self._db.execute(
                "UPDATE documents SET doc_type = ?, reading = ?, status = ? WHERE id = ?",
                (doc_type or current["doc_type"],
                 json.dumps(reading, ensure_ascii=False) if reading is not None
                 else (json.dumps(current["reading"], ensure_ascii=False)
                       if current["reading"] is not None else None),
                 status or current["status"], doc_id))
        return self.document(pid, doc_id)

    def document(self, pid: str, doc_id: str) -> dict[str, Any]:
        row = self._row("SELECT * FROM documents WHERE id = ? AND profile_id = ?", doc_id, pid)
        return _document_dict(row)

    def documents(self, pid: str) -> list[dict[str, Any]]:
        self.get_profile(pid)
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM documents WHERE profile_id = ? ORDER BY uploaded_at DESC",
                (pid,)).fetchall()
        return [_document_dict(row) for row in rows]

    def delete_document(self, pid: str, doc_id: str) -> None:
        """Delete the file and its record. Facts read from it stay — a person's income
        does not change because they deleted the photo — but keep the dangling doc_id,
        so the provenance still says the value came from a document."""
        document = self.document(pid, doc_id)
        with self._lock, self._db:
            self._db.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        Path(document["stored_path"]).unlink(missing_ok=True)

    # ---------------------------------------------------------------- eligibility

    def last_eligible(self, pid: str) -> list[str] | None:
        row = self._row("SELECT last_eligible FROM profiles WHERE id = ?", pid)
        return None if row["last_eligible"] is None else json.loads(row["last_eligible"])

    def set_last_eligible(self, pid: str, scheme_ids: Iterable[str]) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE profiles SET last_eligible = ? WHERE id = ?",
                             (json.dumps(sorted(scheme_ids)), pid))

    # -------------------------------------------------------------------- helpers

    def _row(self, query: str, *args: Any) -> sqlite3.Row:
        with self._lock:
            row = self._db.execute(query, args).fetchone()
        if row is None:
            raise KeyError(args[0])
        return row


def _profile_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "household": row["household"],
        "name": row["name"],
        "relation": row["relation"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "n_facts": row["n_facts"],
        "n_documents": row["n_documents"],
    }


def _document_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "doc_type": row["doc_type"],
        "filename": row["filename"],
        "stored_path": row["stored_path"],
        "media_type": row["media_type"],
        "reading": json.loads(row["reading"]) if row["reading"] else None,
        "status": row["status"],
        "uploaded_at": row["uploaded_at"],
    }


# ------------------------------------------------------------------- eligibility


def eligibility(active: SchemeKB, vault: Vault, pid: str, *,
                remember: bool = True) -> dict[str, Any]:
    """Evaluate a saved profile and report what changed since the last check.

    The diff is against the eligible set stored at the previous check, so it answers
    "what did this life event do?" — not "what has ever been true". The first check has no
    baseline and says so rather than reporting every scheme as newly gained.
    """
    profile, _ = vault.profile(pid)
    buckets = active.match(profile)
    eligible_ids = sorted(buckets[Verdict.TRUE])
    previous = vault.last_eligible(pid)

    def card(scheme_id: str) -> dict[str, Any]:
        if scheme_id in active:
            return scheme_summary(active[scheme_id])
        return {"id": scheme_id, "name": scheme_id}  # retired from the KB since last check

    changes = {
        "first_check": previous is None,
        "gained": [card(s) for s in eligible_ids if previous is not None and s not in previous],
        "lost": [card(s) for s in (previous or []) if s not in eligible_ids],
    }
    if remember:
        vault.set_last_eligible(pid, eligible_ids)
    return {
        "profile_id": pid,
        "board": board(active, profile),
        "eligible": [scheme_summary(active[s]) for s in eligible_ids],
        "near_misses": near_misses(active, profile, vault.spec),
        "n_undetermined": len(buckets[Verdict.UNKNOWN]),
        "changes": changes,
    }
