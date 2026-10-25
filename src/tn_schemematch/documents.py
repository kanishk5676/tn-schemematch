"""Documents: read a photographed certificate, file it, and say what is still missing.

A citizen who has been told "you qualify for six schemes" still has to walk into an office
with the right papers. This module closes that gap in three steps.

1. **Read.** A vision model looks at the photo and reports the document type and the facts
   it states. The reply is constrained by a JSON schema whose ``attr`` field is an enum of
   the vocabulary, so the model cannot even *express* an attribute that does not exist.
2. **Check.** Everything it reports is then re-checked here, deterministically. A fact is
   kept only if this *type* of document can state it (``evidences`` in
   ``kb/spec/documents.yaml``) — a ration card that "says" the holder is SC is discarded —
   and only after the same normalizer that reads typed answers has canonicalized it. ID
   numbers are masked to their last four digits before anything is stored.
3. **Reconcile.** A fact the profile does not have yet is added; one it already has is
   confirmed; one that disagrees is returned as a *conflict* for the citizen to settle. A
   document never silently overwrites what a person said.

This is the project's division of labour applied to paper: the model reads, the rules
decide, and nothing the model says reaches a verdict without passing through the
vocabulary first. With no model at all, the citizen names the document type by hand; the
facts implied by merely holding it are applied and the checklist works unchanged.
"""

from __future__ import annotations

import io
import re
import time
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .attributes import DEFAULT_SPEC_PATH, AttributeSpec, SchemaError, default_spec
from .kb import SchemeKB
from .serialize import first_sentence, format_value, label_for
from .systems.base import parse_json_response

DEFAULT_DOCUMENTS_PATH = DEFAULT_SPEC_PATH.parent / "documents.yaml"

# Uploads above this are refused before any decoding. Phone photos are 2–6 MB.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
# Without Pillow to shrink it, an image is sent as-is, and the API caps a base64 image.
MAX_UNRESIZED_BYTES = 5 * 1024 * 1024
LONG_EDGE_PX = 1600


class DocumentError(ValueError):
    """An upload this module will not process. ``status`` is the HTTP code to answer."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------- vocabulary


@dataclass(frozen=True)
class DocumentType:
    id: str
    kind: str  # document | action
    label: str
    label_ta: str
    evidences: tuple[str, ...]
    implies: Mapping[str, Any]
    matches: tuple[str, ...]

    @property
    def uploadable(self) -> bool:
        return self.kind == "document"

    def brief(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label, "label_ta": self.label_ta}


@dataclass
class DocumentVocabulary:
    version: str
    types: dict[str, DocumentType]
    _by_requirement: dict[str, list[str]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        for doc_type in self.types.values():
            for requirement in doc_type.matches:
                self._by_requirement.setdefault(requirement, []).append(doc_type.id)

    def __contains__(self, type_id: str) -> bool:
        return type_id in self.types

    def __getitem__(self, type_id: str) -> DocumentType:
        return self.types[type_id]

    def uploadable(self) -> list[DocumentType]:
        return [t for t in self.types.values() if t.uploadable]

    def types_for(self, requirement: str) -> list[str]:
        """Every type that satisfies a scheme's requirement string (any one will do)."""
        return list(self._by_requirement.get(requirement, []))

    def readable_attributes(self) -> list[str]:
        return sorted({a for t in self.uploadable() for a in t.evidences})


def load_documents(spec: AttributeSpec, path: str | Path | None = None) -> DocumentVocabulary:
    """Load and validate the document vocabulary against the attribute spec."""
    raw = yaml.safe_load(Path(path or DEFAULT_DOCUMENTS_PATH).read_text(encoding="utf-8"))
    types: dict[str, DocumentType] = {}
    for type_id, body in (raw.get("types") or {}).items():
        kind = body.get("kind")
        if kind not in {"document", "action"}:
            raise SchemaError(f"document type {type_id}: kind must be document or action")
        evidences = tuple(body.get("evidences") or ())
        implies = dict(body.get("implies") or {})
        for attr in (*evidences, *implies):
            if attr not in spec:
                raise SchemaError(f"document type {type_id}: unknown attribute {attr!r}")
            if spec[attr].is_derived or not spec[attr].elicitable:
                raise SchemaError(f"document type {type_id}: {attr} cannot be stated")
        # Implied values are data, so they are canonicalized here once, not trusted.
        implies = {attr: spec.canonicalize(attr, value) for attr, value in implies.items()}
        if kind == "action" and (evidences or implies):
            raise SchemaError(f"document type {type_id}: an action reads no facts")
        types[type_id] = DocumentType(
            id=type_id, kind=kind, label=body["label"], label_ta=body.get("label_ta", ""),
            evidences=evidences, implies=implies, matches=tuple(body.get("matches") or ()))
    return DocumentVocabulary(version=str(raw.get("version", "0")), types=types)


@lru_cache(maxsize=2)
def default_documents() -> DocumentVocabulary:
    return load_documents(default_spec())


def validate_documents(vocab: DocumentVocabulary, kb: SchemeKB) -> list[str]:
    """Every document string any scheme lists must map to at least one type."""
    problems = []
    for scheme in kb:
        for requirement in scheme.documents:
            if not vocab.types_for(requirement):
                problems.append(f"{scheme.id}: document {requirement!r} is not mapped in "
                                f"kb/spec/documents.yaml")
    return problems


# -------------------------------------------------------------------------- images


def _sniff(data: bytes) -> tuple[str, str] | None:
    """(media type, extension) from magic bytes. The filename and the browser's
    Content-Type are both caller-supplied, so neither is trusted."""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg", "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png", "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return None


def prepare_image(data: bytes) -> tuple[bytes, str, str]:
    """Validate an upload and shrink it for the model. Returns (bytes, media type, ext).

    Phone photos carry their rotation in EXIF rather than in the pixels, so the image is
    turned upright first — a sideways certificate reads far worse.
    """
    if not data:
        raise DocumentError("the upload was empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DocumentError("images must be under 10 MB", status=413)
    sniffed = _sniff(data)
    if sniffed is None:
        raise DocumentError("only JPEG, PNG or WebP photos can be read", status=415)
    try:
        from PIL import Image, ImageOps
    except ImportError:
        if len(data) > MAX_UNRESIZED_BYTES:
            raise DocumentError("install Pillow to upload photos over 5 MB", status=413)
        return data, *sniffed
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
        image = image.convert("RGB")
        image.thumbnail((LONG_EDGE_PX, LONG_EDGE_PX))
        out = io.BytesIO()
        image.save(out, format="JPEG", quality=85)
    except Exception as exc:  # noqa: BLE001 — a corrupt image is the uploader's problem
        raise DocumentError(f"could not open that image ({type(exc).__name__})",
                            status=415) from None
    return out.getvalue(), "image/jpeg", "jpg"


# ------------------------------------------------------------------------ masking

# Nine or more digits, optionally grouped by spaces or hyphens: Aadhaar (12), bank
# accounts, phone numbers, ration-card numbers. Eight is deliberately excluded so a date
# written dd-mm-yyyy survives.
_LONG_NUMBER = re.compile(r"\d(?:[ \-]?\d){8,}")


def mask_ids(text: str) -> str:
    """Replace every long number with ``XXXX`` plus its last four digits."""
    def repl(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(0))
        return f"XXXX{digits[-4:]}"
    return _LONG_NUMBER.sub(repl, text or "")


# ------------------------------------------------------------------------ reading

READ_SYSTEM_PROMPT = """\
You read photographs of Indian government documents for a welfare-eligibility assistant \
in Tamil Nadu. Documents may be in Tamil, English, or both.

Your job is to identify the document and copy out facts it actually prints. Rules:
- Choose doc_type from the list given. Use "unknown" if the photo is unreadable or is not \
one of them.
- Report a fact only for the attributes listed for that document type, and only if the \
document states it. Never guess or infer from appearance. An empty facts list is fine.
- Copy each value as printed, with its units ("1,20,000 per annum", "2.5 acres"). For age, \
work out completed years on the date given from the printed date of birth.
- In "evidence", quote the short printed text the value came from.
- Never output a full ID, account, card or phone number. Put only the last four digits of \
the document's own number in id_last4, or "" if there is none.
- The document was uploaded to the profile of the person named. If it is about someone \
else (a child's birth certificate, a parent's certificate, a spouse's death certificate), \
set about_profile_holder to false and return no facts.
- Use "" for any text field the document does not show."""


def reading_schema(vocab: DocumentVocabulary) -> dict[str, Any]:
    """The JSON schema the model's reply must satisfy. ``attr`` is an enum, so an
    attribute outside the vocabulary cannot be produced at all."""
    return {
        "type": "object",
        "properties": {
            "doc_type": {"type": "string",
                         "enum": [t.id for t in vocab.uploadable()] + ["unknown"]},
            "holder_name": {"type": "string"},
            "id_last4": {"type": "string"},
            "issue_date": {"type": "string"},
            "about_profile_holder": {"type": "boolean"},
            "facts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "attr": {"type": "string", "enum": vocab.readable_attributes()},
                        "value": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["attr", "value", "evidence"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["doc_type", "holder_name", "id_last4", "issue_date",
                     "about_profile_holder", "facts"],
        "additionalProperties": False,
    }


def _prompt(vocab: DocumentVocabulary, spec: AttributeSpec, holder: str,
            expected_type: str | None, today: date) -> str:
    lines = [f"DATE: {today.isoformat()}", f"PROFILE HOLDER: {holder or '(unnamed)'}"]
    if expected_type:
        lines.append(f"THE CITIZEN SAYS THIS IS: {vocab[expected_type].label} "
                     "(check — they may be wrong)")
    lines += ["", "DOCUMENT TYPES AND THE FACTS EACH MAY STATE:"]
    for doc_type in vocab.uploadable():
        facts = ", ".join(doc_type.evidences) or "(nothing — just identify it)"
        lines.append(f"- {doc_type.id}: {doc_type.label} — {facts}")
    lines += ["", "WHAT EACH ATTRIBUTE MEANS:"]
    for attr in vocab.readable_attributes():
        meaning = first_sentence(spec[attr].description)
        if spec[attr].type == "enum":
            meaning += f" One of: {', '.join(str(v) for v in spec[attr].domain or ())}."
        lines.append(f"- {attr}: {meaning}")
    return "\n".join(lines)


def _empty_reading(doc_type: str, mode: str, error: str | None = None) -> dict[str, Any]:
    return {"doc_type": doc_type, "mode": mode, "holder_name": "", "id_last4": "",
            "issue_date": "", "about_profile_holder": True, "facts": [], "rejected": [],
            "conflicts": [], "error": error}


def _with_implied(reading: dict[str, Any], vocab: DocumentVocabulary,
                  spec: AttributeSpec) -> dict[str, Any]:
    """Add the facts that follow from holding the document at all."""
    doc_type = reading["doc_type"]
    if doc_type not in vocab or not reading["about_profile_holder"]:
        return reading
    stated = {f["attr"] for f in reading["facts"]}
    for attr, value in vocab[doc_type].implies.items():
        if attr not in stated:
            reading["facts"].append({
                "attr": attr, "value": value, "raw": None, "implied": True,
                "evidence": f"holds a {vocab[doc_type].label.lower()}",
                "label": label_for(spec, attr), "display": format_value(spec, attr, value)})
    return reading


def unread_reading(error: str | None = None) -> dict[str, Any]:
    """A stored photo nobody has identified yet; the page asks the citizen what it is."""
    return _empty_reading("unknown", "unread", error)


def manual_reading(vocab: DocumentVocabulary, spec: AttributeSpec, doc_type: str,
                   error: str | None = None) -> dict[str, Any]:
    """A reading with no model: the type the citizen chose, plus its implied facts."""
    if doc_type not in vocab or not vocab[doc_type].uploadable:
        raise DocumentError(f"unknown document type {doc_type!r}")
    return _with_implied(_empty_reading(doc_type, "manual", error), vocab, spec)


def read_document(client: Any, spec: AttributeSpec, vocab: DocumentVocabulary,
                  image: bytes, media_type: str, *, holder: str = "",
                  expected_type: str | None = None,
                  today: date | None = None) -> dict[str, Any]:
    """Ask a vision model what a document says, then keep only what may be believed."""
    if expected_type is not None and (expected_type not in vocab
                                      or not vocab[expected_type].uploadable):
        raise DocumentError(f"unknown document type {expected_type!r}")
    started = time.time()
    raw_text = client.complete_with_images(
        READ_SYSTEM_PROMPT,
        _prompt(vocab, spec, holder, expected_type, today or date.today()),
        [(media_type, image)], schema=reading_schema(vocab))
    payload = parse_json_response(raw_text)
    if not isinstance(payload, dict):
        raise ValueError(f"reader returned {type(payload).__name__}, expected an object")

    doc_type = payload.get("doc_type")
    if doc_type not in vocab or not vocab[doc_type].uploadable:
        doc_type = "unknown"
    reading = _empty_reading(doc_type, "model")
    reading.update({
        "holder_name": mask_ids(str(payload.get("holder_name") or ""))[:120],
        "id_last4": re.sub(r"\D", "", str(payload.get("id_last4") or ""))[-4:],
        "issue_date": str(payload.get("issue_date") or "")[:40],
        "about_profile_holder": payload.get("about_profile_holder") is not False,
        "expected_type": expected_type,
        "type_mismatch": bool(expected_type and doc_type != expected_type),
        "model": getattr(client, "name", "model"),
        "latency_ms": int((time.time() - started) * 1000),
    })

    allowed = set(vocab[doc_type].evidences) if doc_type in vocab else set()
    for fact in payload.get("facts") or []:
        attr, raw_value = fact.get("attr"), fact.get("value")
        evidence = mask_ids(str(fact.get("evidence") or ""))[:200]
        reason = None
        if not reading["about_profile_holder"]:
            reason = "the document is about someone else"
        elif attr not in allowed:
            reason = (f"a {vocab[doc_type].label.lower()} cannot state this"
                      if doc_type in vocab else "document type not recognised")
        if reason is None:
            try:
                value = spec.canonicalize(attr, raw_value)
            except SchemaError as exc:
                reason = str(exc)
        if reason is not None:
            reading["rejected"].append({"attr": attr, "value": mask_ids(str(raw_value)),
                                        "reason": reason})
            continue
        reading["facts"].append({
            "attr": attr, "value": value, "raw": mask_ids(str(raw_value)), "implied": False,
            "evidence": evidence, "label": label_for(spec, attr),
            "display": format_value(spec, attr, value)})
    return _with_implied(reading, vocab, spec)


# -------------------------------------------------------------------- reconciling


def apply_reading(vault: Any, pid: str, doc_id: str,
                  reading: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Merge a reading into a saved profile without overwriting anything the person said.

    New facts are added and agreeing facts re-recorded with the document as their source
    (a value confirmed by a certificate is worth more than one typed into a box). A
    disagreement is returned as a conflict and written nowhere.
    """
    profile, sources = vault.profile(pid)
    applied, confirmed, conflicts = [], [], []
    for fact in reading["facts"]:
        attr, value = fact["attr"], fact["value"]
        current = profile.get(attr)
        if current is not None and current != value:
            conflicts.append({
                "attr": attr, "label": fact["label"],
                "current": current,
                "current_display": format_value(vault.spec, attr, current),
                "current_source": sources.get(attr),
                "document_value": value, "document_display": fact["display"],
                "evidence": fact["evidence"]})
            continue
        vault.record(pid, attr, value, source="document", evidence=fact["evidence"],
                     doc_id=doc_id)
        (confirmed if current is not None else applied).append(
            {"attr": attr, "label": fact["label"], "display": fact["display"]})
    return {"applied": applied, "confirmed": confirmed, "conflicts": conflicts}


# ---------------------------------------------------------------------- checklist


def checklist(vocab: DocumentVocabulary, active: SchemeKB, scheme_ids: Iterable[str],
              held_types: Iterable[str]) -> dict[str, Any]:
    """What each scheme needs, what is already on file, and one ranked list to collect.

    The combined list is the useful part: "Income certificate — needed for 3 of your
    schemes" is a single trip to the VAO, where three separate checklists hide that.
    """
    held = set(held_types)
    schemes, wanted = [], {}
    for scheme_id in scheme_ids:
        if scheme_id not in active:
            continue
        scheme = active[scheme_id]
        items = []
        for requirement in scheme.documents:
            type_ids = vocab.types_for(requirement)
            is_action = bool(type_ids) and all(not vocab[t].uploadable for t in type_ids)
            have = sorted(t for t in type_ids if t in held)
            status = "action" if is_action else ("have" if have else "missing")
            items.append({"requirement": requirement, "status": status, "have": have,
                          "types": [vocab[t].brief() for t in type_ids]})
            if status == "missing":
                key = tuple(sorted(type_ids))
                entry = wanted.setdefault(key, {
                    "types": [vocab[t].brief() for t in key],
                    "label": " or ".join(vocab[t].label for t in key) or requirement,
                    "label_ta": " / ".join(vocab[t].label_ta for t in key if vocab[t].label_ta),
                    "requirements": [], "schemes": []})
                if requirement not in entry["requirements"]:
                    entry["requirements"].append(requirement)
                if scheme.id not in entry["schemes"]:
                    entry["schemes"].append(scheme.id)
        n_missing = sum(1 for item in items if item["status"] == "missing")
        schemes.append({"id": scheme.id, "name": scheme.name, "name_ta": scheme.name_ta,
                        "apply_url": scheme.apply_url, "items": items,
                        "n_missing": n_missing, "ready": n_missing == 0})
    to_collect = sorted(wanted.values(), key=lambda e: (-len(e["schemes"]), e["label"]))
    for entry in to_collect:
        entry["n_schemes"] = len(entry["schemes"])
    return {"schemes": schemes, "to_collect": to_collect,
            "n_ready": sum(1 for s in schemes if s["ready"])}
