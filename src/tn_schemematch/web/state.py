"""Server-held interview sessions.

Deliberately in-memory. The whole mutable world is one dict of
:class:`~tn_schemematch.interview.InterviewState` records, each a few dozen scalars, and
the deployment target is one process serving one or two people in a room.

The limitations are real and are stated rather than hidden: sessions do not survive a
restart, they are not shared between workers, and a session id is a bearer token with no
auth behind it. None of that is load-bearing for what this serves, and because
``InterviewState`` is already JSON-serializable, persistence later is ``json.dump`` per
session rather than a change of architecture.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

from pathlib import Path

from ..attributes import AttributeSpec
from ..documents import DocumentVocabulary
from ..interview import Interview, InterviewState
from ..kb import SchemeKB
from ..vault import DEFAULT_VAULT_DIR, Vault


@dataclass
class Session:
    id: str
    state: InterviewState
    created_at: float
    last_seen: float
    # Cached model output, keyed so a re-click on stage never pays for a second call.
    explanations: dict[str, str] = field(default_factory=dict)
    # The saved profile this session reads from and writes back to, if any.
    profile_id: str | None = None
    # Agent sessions only: the API message history (append-only — earlier turns carry
    # thinking blocks that stop being valid if edited) and the transcript the page shows.
    chat: list[dict[str, Any]] = field(default_factory=list)
    transcript: list[dict[str, Any]] = field(default_factory=list)
    last_eligible: list[str] | None = None
    # "agent" (free conversation with the model) or "guided" (fixed questions, no model),
    # the language the assistant speaks, and why the chat is guided if it is.
    mode: str = "guided"
    lang: str = "ta"
    reason: str | None = None
    lock: Any = field(default_factory=threading.Lock, repr=False)


class SessionStore:
    """An LRU-capped, lock-guarded session table.

    Flask's development server is threaded, so two requests can touch the table at once.
    The KB, spec and rule AST need no lock — they are read-only and the AST is frozen —
    but this table is the one genuinely mutable thing in the process.
    """

    def __init__(self, maxsize: int = 200) -> None:
        self._sessions: OrderedDict[str, Session] = OrderedDict()
        self._lock = threading.Lock()
        self._maxsize = maxsize

    def new(self, state: InterviewState) -> Session:
        now = time.time()
        session = Session(id=uuid.uuid4().hex, state=state, created_at=now, last_seen=now)
        with self._lock:
            self._sessions[session.id] = session
            while len(self._sessions) > self._maxsize:
                self._sessions.popitem(last=False)
        return session

    def get(self, session_id: str) -> Session:
        """Raises ``KeyError`` for an unknown or evicted session; the caller maps it to 404."""
        with self._lock:
            session = self._sessions[session_id]
            session.last_seen = time.time()
            self._sessions.move_to_end(session_id)
            return session

    def __len__(self) -> int:
        with self._lock:
            return len(self._sessions)


@dataclass
class AppContext:
    """Everything loaded once at startup and shared read-only across requests."""

    kb: SchemeKB
    spec: AttributeSpec
    interview: Interview
    sessions: SessionStore
    scheme_cards: list[dict[str, Any]]
    model_name: str = "none (rules only)"
    _personas: Any = None
    # The words of every question, for guided mode (kb/spec/questions.yaml).
    questions: Any = None
    # The usage meter the model client reports to, if any.
    meter: Any = None
    documents: DocumentVocabulary | None = None
    vault_dir: Path = DEFAULT_VAULT_DIR
    _vault: Vault | None = None
    _vault_lock: Any = field(default_factory=threading.Lock, repr=False)

    @property
    def active(self) -> SchemeKB:
        return self.interview.active

    @property
    def vault(self) -> Vault:
        """Opened on first use, so a server that never saves a profile never creates a
        database — and a test that never touches profiles never writes to data/."""
        with self._vault_lock:
            if self._vault is None:
                self._vault = Vault(self.vault_dir, self.spec)
            return self._vault
