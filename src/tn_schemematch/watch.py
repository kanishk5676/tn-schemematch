"""Notice when a scheme's source page changes, so the rule is re-read before it goes stale.

``stale_schemes`` in :mod:`.kb` warns by age alone: a rule read six months ago *may* have
changed. This module checks whether it *did*. It re-fetches every cited source, reduces the
page to its visible text, and compares a fingerprint with the one recorded last time
(``kb/source-hashes.json``). A changed page is a reason for a person to re-read the source
against the rule; an unreachable one is reported but is not a change.

Government pages carry noise — "last updated" stamps, visitor counters — so a changed
fingerprint is a prompt to look, not proof the rule moved. The fingerprint drops dates and
times for that reason.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import urllib.request
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .kb import DEFAULT_KB_DIR, SchemeKB

DEFAULT_BASELINE = DEFAULT_KB_DIR.parent / "source-hashes.json"
USER_AGENT = "TN-SchemeMatch source watcher (+https://github.com/kanishk5676/tn-schemematch)"
MAX_BYTES = 5 * 1024 * 1024

_DROP_BLOCKS = re.compile(r"<(script|style|noscript)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAGS = re.compile(r"<[^>]+>")
_DATES = re.compile(r"\b\d{1,4}[-/.](?:\d{1,2}|[A-Za-z]{3,9})[-/.]\d{1,4}\b|\b\d{1,2}:\d{2}(?::\d{2})?\b")


def page_text(raw: str) -> str:
    """The visible words of a page, with dates and times taken out."""
    text = _TAGS.sub(" ", _DROP_BLOCKS.sub(" ", raw))
    text = _DATES.sub(" ", html.unescape(text))
    return re.sub(r"\s+", " ", text).strip()


def fingerprint(raw: str) -> str:
    return hashlib.sha256(page_text(raw).encode("utf-8")).hexdigest()


def fetch(url: str, *, timeout: float = 20.0) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 — https sources only
        return response.read(MAX_BYTES).decode("utf-8", errors="replace")


def watch(kb: SchemeKB, baseline: dict[str, Any], *,
          fetcher: Callable[[str], str] = fetch) -> list[dict[str, Any]]:
    """One row per cited URL: unchanged, changed, new (no fingerprint yet) or unreachable."""
    cited: dict[str, list[str]] = {}
    for scheme in kb.active():
        for source in scheme.sources:
            cited.setdefault(source.url, []).append(scheme.id)
    rows = []
    for url in sorted(cited):
        row: dict[str, Any] = {"url": url, "schemes": sorted(set(cited[url]))}
        try:
            row["hash"] = fingerprint(fetcher(url))
        except Exception as exc:  # noqa: BLE001 — every failure is a row, never a crash
            row.update(status="unreachable", error=f"{type(exc).__name__}: {exc}"[:200])
            rows.append(row)
            continue
        previous = (baseline.get(url) or {}).get("hash")
        row["status"] = ("new" if previous is None else
                         "unchanged" if previous == row["hash"] else "changed")
        rows.append(row)
    return rows


def load_baseline(path: str | Path | None = None) -> dict[str, Any]:
    path = Path(path or DEFAULT_BASELINE)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def save_baseline(rows: list[dict[str, Any]], baseline: dict[str, Any],
                  path: str | Path | None = None, *, today: date | None = None) -> Path:
    """Record the fingerprints just taken. Unreachable pages keep their old one."""
    stamp = (today or date.today()).isoformat()
    updated = dict(baseline)
    for row in rows:
        if "hash" in row:
            updated[row["url"]] = {"hash": row["hash"], "checked": stamp}
    path = Path(path or DEFAULT_BASELINE)
    path.write_text(json.dumps(dict(sorted(updated.items())), indent=1) + "\n", encoding="utf-8")
    return path
