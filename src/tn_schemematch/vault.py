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
from .benefits import group_view, totals
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
CREATE TABLE IF NOT EXISTS applications (
    id          TEXT PRIMARY KEY,
    profile_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    scheme_id   TEXT NOT NULL,
    reference   TEXT NOT NULL DEFAULT '',
    office      TEXT NOT NULL DEFAULT '',
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS application_events (
    seq            INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    status         TEXT NOT NULL,
    on_date        TEXT,
    reason         TEXT,
    note           TEXT NOT NULL DEFAULT '',
    verdict        TEXT NOT NULL,
    recorded_at    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_by_application ON application_events (application_id, seq);
CREATE TABLE IF NOT EXISTS camps (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    place       TEXT NOT NULL DEFAULT '',
    held_on     TEXT,
    created_at  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS camp_members (
    camp_id     TEXT NOT NULL REFERENCES camps(id) ON DELETE CASCADE,
    profile_id  TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    added_at    REAL NOT NULL,
    PRIMARY KEY (camp_id, profile_id)
);
CREATE TABLE IF NOT EXISTS consents (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   TEXT NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    notice       TEXT NOT NULL,
    lang         TEXT NOT NULL,
    given_by     TEXT NOT NULL,
    given_at     REAL NOT NULL,
    withdrawn_at REAL
);
-- No foreign key: the record that a profile was deleted must outlive the profile. It
-- holds ids and action names only, never a value about the person.
CREATE TABLE IF NOT EXISTS audit (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    at          REAL NOT NULL,
    actor       TEXT NOT NULL,
    action      TEXT NOT NULL,
    profile_id  TEXT,
    detail      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS audit_by_profile ON audit (profile_id, seq);
CREATE TABLE IF NOT EXISTS api_keys (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    key_hash     TEXT NOT NULL UNIQUE,
    created_at   REAL NOT NULL,
    last_used_at REAL,
    n_calls      INTEGER NOT NULL DEFAULT 0,
    revoked_at   REAL
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
        canonical = self._canonical(attr, value, context=self._context(pid))
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
        facts = sorted(facts, key=lambda f: f[0] != "state")  # the state reads the rest
        context = self._context(pid)
        rows = []
        for attr, value, source, evidence in facts:
            canonical = self._canonical(attr, value, context=context)
            if attr == "state":
                context = {**context, "state": canonical}
            rows.append((attr, canonical, source, evidence))
        written: dict[str, Any] = {}
        for attr, value, source, evidence in rows:
            written[attr] = self.record(pid, attr, value, source=source, evidence=evidence)
        return written

    def _context(self, pid: str) -> dict[str, Any]:
        """What is already known that changes how a value reads (today: the state)."""
        latest = self._latest(pid).get("state")
        return {"state": json.loads(latest["value"])} if latest is not None else {}

    def _canonical(self, attr: str, value: Any, *,
                   context: Mapping[str, Any] | None = None) -> Any:
        if attr not in self.spec:
            raise VaultError(f"unknown attribute {attr!r}")
        if self.spec[attr].is_derived:
            raise VaultError(f"{attr} is derived from other answers and cannot be stored")
        if not self.spec[attr].elicitable:
            raise VaultError(f"{attr} is not something a citizen states")
        if value is None:
            return None
        try:
            return self.spec.canonicalize(attr, value, context=context)
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

    # -------------------------------------------------------------- applications

    def open_application(self, pid: str, scheme_id: str, *, status: str, verdict: str,
                         on_date: str | None = None, reference: str = "",
                         office: str = "", note: str = "") -> dict[str, Any]:
        """Start tracking an application. Its history is an event log, like facts:
        every status change is a new row carrying what the rules said at that moment."""
        self.get_profile(pid)
        aid = uuid.uuid4().hex
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO applications (id, profile_id, scheme_id, reference, office,"
                " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (aid, pid, scheme_id, reference[:60], office[:120], now, now))
        self.add_application_event(pid, aid, status=status, verdict=verdict,
                                   on_date=on_date, note=note)
        return self.application(pid, aid)

    def add_application_event(self, pid: str, aid: str, *, status: str, verdict: str,
                              on_date: str | None = None, reason: str | None = None,
                              note: str = "") -> dict[str, Any]:
        self._row("SELECT id FROM applications WHERE id = ? AND profile_id = ?", aid, pid)
        now = time.time()
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO application_events (application_id, status, on_date, reason,"
                " note, verdict, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (aid, status, on_date, reason, (note or "")[:500], verdict, now))
            self._db.execute("UPDATE applications SET updated_at = ? WHERE id = ?", (now, aid))
        return self.application(pid, aid)

    def application(self, pid: str, aid: str) -> dict[str, Any]:
        row = self._row("SELECT * FROM applications WHERE id = ? AND profile_id = ?", aid, pid)
        with self._lock:
            events = self._db.execute(
                "SELECT * FROM application_events WHERE application_id = ? ORDER BY seq",
                (aid,)).fetchall()
        return _application_dict(row, events)

    def applications(self, pid: str) -> list[dict[str, Any]]:
        self.get_profile(pid)
        with self._lock:
            ids = [r["id"] for r in self._db.execute(
                "SELECT id FROM applications WHERE profile_id = ? ORDER BY updated_at DESC",
                (pid,)).fetchall()]
        return [self.application(pid, aid) for aid in ids]

    def delete_application(self, pid: str, aid: str) -> None:
        self._row("SELECT id FROM applications WHERE id = ? AND profile_id = ?", aid, pid)
        with self._lock, self._db:
            self._db.execute("DELETE FROM applications WHERE id = ?", (aid,))

    def application_events(self) -> list[dict[str, Any]]:
        """Every status change of every application, with its scheme — for the outcome
        report, which counts them and never shows who they belong to."""
        with self._lock:
            rows = self._db.execute(
                "SELECT a.scheme_id, a.id AS application_id, e.status, e.reason, e.verdict,"
                " e.recorded_at FROM application_events e JOIN applications a"
                " ON a.id = e.application_id ORDER BY e.seq").fetchall()
        return [dict(row) for row in rows]

    # --------------------------------------------------------------------- camps

    def create_camp(self, name: str, *, place: str = "", held_on: str | None = None) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise VaultError("a camp needs a name")
        cid = uuid.uuid4().hex
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO camps (id, name, place, held_on, created_at) VALUES (?, ?, ?, ?, ?)",
                (cid, name[:MAX_NAME_LENGTH], (place or "").strip()[:MAX_NAME_LENGTH], held_on,
                 time.time()))
        return self.camp(cid)

    def camp(self, cid: str) -> dict[str, Any]:
        row = self._row("SELECT c.*, (SELECT COUNT(*) FROM camp_members m WHERE m.camp_id = c.id)"
                        " AS n_people FROM camps c WHERE c.id = ?", cid)
        return dict(row)

    def camps(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT c.*, (SELECT COUNT(*) FROM camp_members m WHERE m.camp_id = c.id)"
                " AS n_people FROM camps c ORDER BY c.created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def add_to_camp(self, cid: str, pid: str) -> None:
        self.camp(cid)
        self.get_profile(pid)
        with self._lock, self._db:
            self._db.execute("INSERT OR IGNORE INTO camp_members (camp_id, profile_id, added_at)"
                             " VALUES (?, ?, ?)", (cid, pid, time.time()))

    def camp_members(self, cid: str) -> list[str]:
        self.camp(cid)
        with self._lock:
            rows = self._db.execute("SELECT profile_id FROM camp_members WHERE camp_id = ?"
                                    " ORDER BY added_at", (cid,)).fetchall()
        return [row["profile_id"] for row in rows]

    def profile_ids(self) -> list[str]:
        with self._lock:
            return [r["id"] for r in self._db.execute(
                "SELECT id FROM profiles ORDER BY created_at").fetchall()]

    # ------------------------------------------------------------ consent and audit

    def give_consent(self, pid: str, *, notice: str, lang: str, given_by: str) -> dict[str, Any]:
        self.get_profile(pid)
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO consents (profile_id, notice, lang, given_by, given_at)"
                " VALUES (?, ?, ?, ?, ?)", (pid, notice, lang, given_by, time.time()))
        return self.consent(pid)

    def consent(self, pid: str) -> dict[str, Any] | None:
        """The consent in force, or ``None`` if none was recorded or it was withdrawn."""
        self.get_profile(pid)
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM consents WHERE profile_id = ? ORDER BY seq DESC LIMIT 1",
                (pid,)).fetchone()
        if row is None or row["withdrawn_at"] is not None:
            return None
        return {k: row[k] for k in ("notice", "lang", "given_by", "given_at")}

    def consents(self, pid: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM consents WHERE profile_id = ? ORDER BY seq",
                                    (pid,)).fetchall()
        return [dict(row) for row in rows]

    def log(self, actor: str, action: str, pid: str | None = None, detail: str = "") -> None:
        """Append to the audit log. ``detail`` names what was touched (an attribute, a
        document type), never a value."""
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO audit (at, actor, action, profile_id, detail) VALUES (?, ?, ?, ?, ?)",
                (time.time(), actor[:60], action[:60], pid, (detail or "")[:120]))

    def audit_log(self, pid: str | None = None, *, limit: int = 200) -> list[dict[str, Any]]:
        query, args = "SELECT * FROM audit", []
        if pid is not None:
            query += " WHERE profile_id = ?"
            args.append(pid)
        with self._lock:
            rows = self._db.execute(query + " ORDER BY seq DESC LIMIT ?",
                                    (*args, limit)).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ api keys

    def add_api_key(self, name: str, key_hash: str) -> dict[str, Any]:
        kid = uuid.uuid4().hex[:12]
        with self._lock, self._db:
            self._db.execute("INSERT INTO api_keys (id, name, key_hash, created_at)"
                             " VALUES (?, ?, ?, ?)", (kid, name[:80], key_hash, time.time()))
        return self.api_key(kid)

    def api_key(self, kid: str) -> dict[str, Any]:
        row = self._row("SELECT id, name, created_at, last_used_at, n_calls, revoked_at"
                        " FROM api_keys WHERE id = ?", kid)
        return dict(row)

    def api_key_by_hash(self, key_hash: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT id, name, created_at, last_used_at, n_calls, revoked_at FROM api_keys"
                " WHERE key_hash = ?", (key_hash,)).fetchone()
        return dict(row) if row else None

    def api_keys(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT id, name, created_at, last_used_at, n_calls,"
                                    " revoked_at FROM api_keys ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]

    def touch_api_key(self, kid: str) -> None:
        with self._lock, self._db:
            self._db.execute("UPDATE api_keys SET last_used_at = ?, n_calls = n_calls + 1"
                             " WHERE id = ?", (time.time(), kid))

    def revoke_api_key(self, kid: str) -> dict[str, Any]:
        self.api_key(kid)
        with self._lock, self._db:
            self._db.execute("UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at"
                             " IS NULL", (time.time(), kid))
        return self.api_key(kid)

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


def _application_dict(row: sqlite3.Row, events: list[sqlite3.Row]) -> dict[str, Any]:
    history = [{
        "status": e["status"], "on_date": e["on_date"], "reason": e["reason"],
        "note": e["note"], "verdict": e["verdict"], "recorded_at": e["recorded_at"],
    } for e in events]
    return {
        "id": row["id"],
        "profile_id": row["profile_id"],
        "scheme_id": row["scheme_id"],
        "reference": row["reference"],
        "office": row["office"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "status": history[-1]["status"] if history else None,
        "events": history,
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
    money = totals(active, eligible_ids)
    return {
        "profile_id": pid,
        "board": board(active, profile),
        "eligible": [scheme_summary(active[s]) for s in eligible_ids],
        "near_misses": near_misses(active, profile, vault.spec),
        "n_undetermined": len(buckets[Verdict.UNKNOWN]),
        "changes": changes,
        "money": {key: money[key] for key in (
            "yearly", "yearly_text", "one_time", "one_time_text", "in_kind",
            "in_kind_text", "best_cover", "unpriced")},
        "only_one_of": group_view(active, money["groups"]),
    }
