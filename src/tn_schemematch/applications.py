"""After "you are eligible": tracking an application until the money arrives.

Eligibility is half the job. The other half — applying, waiting, being turned away,
asking why — is where most people give up, and it is also where the project learns
whether its rules are right. This module covers four things:

1. **Status.** An application's history is an append-only log (planned → applied →
   approved or rejected → received), and every entry records what the rule engine said
   at that moment. So "we told her she qualified, and the office said no" is a fact the
   system holds, not an anecdote.
2. **Rejections explained.** A rejection is recorded with a reason from
   ``kb/spec/rejections.yaml``. :func:`explain_rejection` puts the scheme's own clauses on
   the facts that reason concerns beside what the person said, and the next steps.
3. **Outcome feedback.** :func:`outcome_report` counts, per scheme, rejections *on
   eligibility grounds* of people the rules called eligible. Each one means the rule or
   the office is wrong. Both need a person to look; this report is how they find out.
4. **Complaint drafts.** :func:`complaint` writes a letter from a template — no model —
   quoting only the clauses the person meets, and only when the rules say they qualify.
   A letter claiming eligibility the rules do not support would be worse than none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping

import yaml

from .attributes import DEFAULT_SPEC_PATH, AttributeSpec, SchemaError
from .kb import Scheme, SchemeKB
from .rules import Predicate, Trace, Verdict
from .serialize import decisive_clauses, describe_clause, format_value, trace_to_dict

DEFAULT_REJECTIONS_PATH = DEFAULT_SPEC_PATH.parent / "rejections.yaml"
DEFAULT_GRIEVANCE_PATH = DEFAULT_SPEC_PATH.parent / "grievance.yaml"

STATUSES = ("planned", "applied", "pending", "approved", "rejected", "received", "withdrawn")
WAITING = {"applied", "pending"}
FOLLOW_UP_AFTER_DAYS = 30
REJECTION_KINDS = {"eligibility", "documents", "process"}
LANGUAGES = ("en", "ta", "ml")

# A twelve-digit number, grouped or not, is an Aadhaar however it got here. Application
# references are kept (a person needs theirs to follow up) but never an Aadhaar.
_AADHAAR = re.compile(r"(?<!\d)\d{4}[ \-]?\d{4}[ \-]?\d{4}(?!\d)")


class ApplicationError(ValueError):
    """A status, reason or date the tracker does not accept. Maps to HTTP 400."""


def clean_reference(text: str) -> str:
    return _AADHAAR.sub("XXXX XXXX XXXX", (text or "").strip())[:60]


def parse_day(text: str | None) -> str | None:
    """A YYYY-MM-DD the person gives, checked; ``None`` when absent."""
    if not text:
        return None
    try:
        return datetime.strptime(str(text), "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise ApplicationError(f"dates are YYYY-MM-DD, got {text!r}") from None


# ------------------------------------------------------------------------ reasons


@dataclass(frozen=True)
class RejectionReason:
    id: str
    label: str
    kind: str
    labels: Mapping[str, str]
    attrs: tuple[str, ...] = ()
    documents: tuple[str, ...] = ()
    appeal: bool = False
    next: tuple[str, ...] = ()

    def brief(self, lang: str = "en") -> dict[str, Any]:
        return {"id": self.id, "label": self.labels.get(lang) or self.label,
                "label_en": self.label, "kind": self.kind, "appeal": self.appeal}


def load_rejections(spec: AttributeSpec, path: str | Path | None = None,
                    document_types: Iterable[str] | None = None) -> dict[str, RejectionReason]:
    raw = yaml.safe_load(Path(path or DEFAULT_REJECTIONS_PATH).read_text(encoding="utf-8"))
    known_documents = set(document_types) if document_types is not None else None
    reasons = {}
    for rid, body in (raw.get("reasons") or {}).items():
        if body.get("kind") not in REJECTION_KINDS:
            raise SchemaError(f"rejection {rid}: kind must be one of {sorted(REJECTION_KINDS)}")
        for attr in body.get("attrs") or ():
            if attr not in spec:
                raise SchemaError(f"rejection {rid}: unknown attribute {attr!r}")
        for doc in body.get("documents") or ():
            if known_documents is not None and doc not in known_documents:
                raise SchemaError(f"rejection {rid}: unknown document type {doc!r}")
        reasons[rid] = RejectionReason(
            id=rid, label=body["label"], kind=body["kind"],
            labels={"en": body["label"], "ta": body.get("label_ta", ""),
                    "ml": body.get("label_ml", "")},
            attrs=tuple(body.get("attrs") or ()), documents=tuple(body.get("documents") or ()),
            appeal=bool(body.get("appeal", False)), next=tuple(body.get("next") or ()))
    if "other" not in reasons:
        raise SchemaError("rejections.yaml must define 'other'")
    return reasons


@lru_cache(maxsize=2)
def grievance_channels(path: str | None = None) -> dict[str, list[dict[str, Any]]]:
    raw = yaml.safe_load(Path(path or DEFAULT_GRIEVANCE_PATH).read_text(encoding="utf-8"))
    return {key: list(value or []) for key, value in (raw.get("channels") or {}).items()}


def channels_for(scheme: Scheme) -> list[dict[str, Any]]:
    channels = grievance_channels()
    key = scheme.jurisdiction if scheme.level == "state" else "central"
    return list(channels.get(key, []))


# -------------------------------------------------------------------- explaining


def _predicates(trace: Trace) -> Iterable[Trace]:
    if isinstance(trace.node, Predicate):
        yield trace
    for child in trace.children:
        yield from _predicates(child)


def explain_rejection(scheme: Scheme, spec: AttributeSpec, profile: Mapping[str, Any],
                      reason: RejectionReason, *, documents: Any = None,
                      lang: str = "en") -> dict[str, Any]:
    """The reason, the rule's clauses on the facts it concerns, and what to do next."""
    trace = scheme.decide(profile)
    clauses = []
    for node in _predicates(trace):
        if node.node.attr not in reason.attrs:
            continue
        clauses.append({
            "attr": node.node.attr,
            "rule": describe_clause(node.node, spec),
            "you_said": format_value(spec, node.node.attr, node.actual)
            if node.actual is not None else None,
            "met": node.verdict.value,
        })
    guides = []
    if documents is not None:
        for doc in reason.documents:
            if doc in documents:
                guides.append({"type": doc, "label": documents[doc].label,
                               "guide": documents.guide(doc, profile.get("state"))})
    disagrees = reason.kind == "eligibility" and trace.verdict is Verdict.TRUE
    return {
        **reason.brief(lang),
        "next": list(reason.next),
        "clauses": clauses,
        "rules_say": trace.verdict.value,
        "disagrees": disagrees,
        "summary": (
            "By the published rule you qualify. The office may have used a different "
            "figure or an outdated rule — you can ask for a review."
            if disagrees else
            "The published rule agrees that one of these conditions is not met."
            if reason.kind == "eligibility" and trace.verdict is Verdict.FALSE else
            "This is about papers or payment, not about whether you qualify."
            if reason.kind != "eligibility" else
            "We do not know enough of your facts to check this against the rule."),
        "guides": guides,
    }


# ------------------------------------------------------------------------ status


def last_date(application: Mapping[str, Any]) -> date:
    """When the latest status took effect: the date the person gave, else when recorded."""
    event = application["events"][-1]
    if event.get("on_date"):
        return date.fromisoformat(event["on_date"])
    return datetime.fromtimestamp(event["recorded_at"]).date()


def follow_up(application: Mapping[str, Any], today: date | None = None) -> dict[str, Any] | None:
    """A nudge when an application has waited too long in one state."""
    today = today or date.today()
    status = application["status"]
    since = last_date(application)
    waited = (today - since).days
    if status in WAITING and waited >= FOLLOW_UP_AFTER_DAYS:
        return {"kind": "no_decision", "days": waited,
                "text": f"No decision {waited} days after applying — ask the office for the status."}
    if status == "approved" and waited >= FOLLOW_UP_AFTER_DAYS:
        return {"kind": "not_paid", "days": waited,
                "text": f"Approved {waited} days ago but not marked received — check your bank "
                        "passbook, then ask the office."}
    return None


def follow_up_due_on(application: Mapping[str, Any]) -> date | None:
    if application["status"] in WAITING or application["status"] == "approved":
        return last_date(application) + timedelta(days=FOLLOW_UP_AFTER_DAYS)
    return None


# ----------------------------------------------------------------------- outcomes


def outcome_report(events: list[Mapping[str, Any]], kb: SchemeKB,
                   reasons: Mapping[str, RejectionReason]) -> dict[str, Any]:
    """Per scheme: how applications ended, and where the office and the rules disagree.

    Counted by each application's latest status. A *disagreement* is a rejection on
    eligibility grounds while the rule engine said eligible — the signal that a rule, or
    an office, needs a person to look at it.
    """
    latest: dict[str, Mapping[str, Any]] = {}
    for event in events:
        latest[event["application_id"]] = event
    schemes: dict[str, dict[str, Any]] = {}
    for event in latest.values():
        row = schemes.setdefault(event["scheme_id"], {
            "scheme_id": event["scheme_id"],
            "name": kb[event["scheme_id"]].name if event["scheme_id"] in kb else event["scheme_id"],
            **{status: 0 for status in STATUSES}, "disagreements": 0, "reasons": {}})
        row[event["status"]] += 1
        if event["status"] == "rejected":
            reason = reasons.get(event["reason"] or "other")
            label = reason.label if reason else event["reason"]
            row["reasons"][label] = row["reasons"].get(label, 0) + 1
            if reason and reason.kind == "eligibility" and event["verdict"] == "eligible":
                row["disagreements"] += 1
    rows = sorted(schemes.values(), key=lambda r: (-r["disagreements"], -r["rejected"],
                                                   r["scheme_id"]))
    return {"schemes": rows,
            "needs_review": [r["scheme_id"] for r in rows if r["disagreements"]],
            "n_applications": len(latest)}


# ---------------------------------------------------------------------- complaints

_TEMPLATES = {
    "en": {
        "to": "To: {to}",
        "subject": "Subject: Application for {scheme} — request for review",
        "opening": "I, {name}, applied for {scheme}{when}{ref}.",
        "when": " on {date}",
        "ref": " (application number {ref})",
        "rejected": "It was rejected.",
        "rejected_reason": "It was rejected, with the reason: \"{reason}\".",
        "waiting": "I have not been told of any decision since then.",
        "not_paid": "It was approved on {date}, but I have not yet received the benefit.",
        "meets": "According to the published eligibility rules for this scheme, I meet these conditions:",
        "ask_review": "I request that my application be reviewed, and that any reason for refusing it be given to me in writing.",
        "ask_reason": "I request that the reason for this decision, and the rule it is based on, be given to me in writing.",
        "ask_status": "I request to be told the status of my application and when a decision will be made.",
        "ask_payment": "I request that the payment be released, or that I be told in writing why it has not been.",
    },
    "ta": {
        "to": "பெறுநர்: {to}",
        "subject": "பொருள்: {scheme} விண்ணப்பம் — மறுபரிசீலனை கோரிக்கை",
        # The scheme's own name usually ends in "திட்டம்", so it is set apart after a colon
        # rather than inflected ("…திட்டம் திட்டத்திற்கு" reads as a stutter).
        "opening": "{name} ஆகிய நான்,{when} பின்வரும் திட்டத்திற்கு விண்ணப்பித்தேன்: {scheme}{ref}.",
        "when": " {date} அன்று",
        "ref": " (விண்ணப்ப எண்: {ref})",
        "rejected": "அது நிராகரிக்கப்பட்டது.",
        "rejected_reason": "அது நிராகரிக்கப்பட்டது (காரணம்: \"{reason}\").",
        "waiting": "அதன் பிறகு எந்த முடிவும் எனக்குத் தெரிவிக்கப்படவில்லை.",
        "not_paid": "{date} அன்று அது அங்கீகரிக்கப்பட்டது, ஆனால் பயன் இன்னும் கிடைக்கவில்லை.",
        "meets": "இந்தத் திட்டத்தின் வெளியிடப்பட்ட தகுதி விதிகளின்படி, நான் பின்வரும் நிபந்தனைகளைப் பூர்த்தி செய்கிறேன்:",
        "ask_review": "எனது விண்ணப்பத்தை மறுபரிசீலனை செய்யுமாறும், மறுப்புக்கான காரணத்தை எழுத்துப்பூர்வமாகத் தெரிவிக்குமாறும் கேட்டுக்கொள்கிறேன்.",
        "ask_reason": "இந்த முடிவுக்கான காரணத்தையும் அது அடிப்படையாகக் கொண்ட விதியையும் எழுத்துப்பூர்வமாகத் தெரிவிக்குமாறு கேட்டுக்கொள்கிறேன்.",
        "ask_status": "எனது விண்ணப்பத்தின் நிலையையும், முடிவு எப்போது எடுக்கப்படும் என்பதையும் தெரிவிக்குமாறு கேட்டுக்கொள்கிறேன்.",
        "ask_payment": "தொகையை விடுவிக்குமாறு, அல்லது ஏன் விடுவிக்கப்படவில்லை என்பதை எழுத்துப்பூர்வமாகத் தெரிவிக்குமாறு கேட்டுக்கொள்கிறேன்.",
    },
    "ml": {
        "to": "സ്വീകർത്താവ്: {to}",
        "subject": "വിഷയം: {scheme} അപേക്ഷ — പുനഃപരിശോധനയ്ക്കുള്ള അപേക്ഷ",
        "opening": "{name} എന്ന ഞാൻ{when} താഴെപ്പറയുന്ന പദ്ധതിക്ക് അപേക്ഷിച്ചു: {scheme}{ref}.",
        "when": " {date}-ന്",
        "ref": " (അപേക്ഷ നമ്പർ: {ref})",
        "rejected": "അത് നിരസിക്കപ്പെട്ടു.",
        "rejected_reason": "അത് നിരസിക്കപ്പെട്ടു (കാരണം: \"{reason}\").",
        "waiting": "അതിനുശേഷം തീരുമാനമൊന്നും എന്നെ അറിയിച്ചിട്ടില്ല.",
        "not_paid": "{date}-ന് അത് അംഗീകരിച്ചു, പക്ഷേ ആനുകൂല്യം ഇതുവരെ ലഭിച്ചിട്ടില്ല.",
        "meets": "ഈ പദ്ധതിയുടെ പ്രസിദ്ധീകരിച്ച യോഗ്യതാ നിബന്ധനകൾ പ്രകാരം ഞാൻ താഴെപ്പറയുന്ന വ്യവസ്ഥകൾ പാലിക്കുന്നു:",
        "ask_review": "എന്റെ അപേക്ഷ പുനഃപരിശോധിക്കണമെന്നും നിരസിക്കാനുള്ള കാരണം രേഖാമൂലം അറിയിക്കണമെന്നും അഭ്യർത്ഥിക്കുന്നു.",
        "ask_reason": "ഈ തീരുമാനത്തിന്റെ കാരണവും അതിന് അടിസ്ഥാനമായ നിയമവും രേഖാമൂലം അറിയിക്കണമെന്ന് അഭ്യർത്ഥിക്കുന്നു.",
        "ask_status": "എന്റെ അപേക്ഷയുടെ നില എന്താണെന്നും തീരുമാനം എപ്പോൾ ഉണ്ടാകുമെന്നും അറിയിക്കണമെന്ന് അഭ്യർത്ഥിക്കുന്നു.",
        "ask_payment": "തുക അനുവദിക്കണമെന്നോ, അനുവദിക്കാത്തതിന്റെ കാരണം രേഖാമൂലം അറിയിക്കണമെന്നോ അഭ്യർത്ഥിക്കുന്നു.",
    },
}


def _indian_date(iso: str | None) -> str:
    return date.fromisoformat(iso).strftime("%d-%m-%Y") if iso else ""


def complaint(scheme: Scheme, spec: AttributeSpec, profile: Mapping[str, Any], name: str,
              application: Mapping[str, Any], reasons: Mapping[str, RejectionReason], *,
              lang: str = "en", today: date | None = None) -> dict[str, Any]:
    """A letter the person can copy, print or send. Built from templates and the trace.

    The "I meet these conditions" paragraph appears only when the rule engine says the
    person is eligible today, and lists only the clauses that decided it — the same
    evidence the assistant's explanations are limited to. Otherwise the letter asks for
    the reason in writing, which is always a fair request. The clauses stay in English in
    every language: they are the rule's own wording, which the office can check.
    """
    if lang not in _TEMPLATES:
        raise ApplicationError(f"language must be one of {', '.join(LANGUAGES)}")
    t = _TEMPLATES[lang]
    today = today or date.today()
    status = application["status"]
    applied = next((e for e in application["events"] if e["status"] == "applied"), None)
    applied_on = (applied or {}).get("on_date")
    scheme_name = (scheme.name_ta if lang == "ta" else scheme.name_ml if lang == "ml"
                   else "") or scheme.name

    lines = [t["to"].format(to=scheme.authority or "The officer in charge of the scheme"),
             t["subject"].format(scheme=scheme_name), ""]
    opening = t["opening"].format(
        name=name, scheme=scheme_name,
        when=t["when"].format(date=_indian_date(applied_on)) if applied_on else "",
        ref=t["ref"].format(ref=application["reference"]) if application.get("reference") else "")
    trace = scheme.decide(profile)
    eligible = trace.verdict is Verdict.TRUE
    if status == "rejected":
        reason = reasons.get(application["events"][-1].get("reason") or "")
        label = (reason.labels.get(lang) or reason.label) if reason else ""
        state_line = t["rejected_reason"].format(reason=label) if label else t["rejected"]
        ask = t["ask_review"] if eligible else t["ask_reason"]
    elif status == "approved":
        state_line = t["not_paid"].format(date=_indian_date(application["events"][-1].get("on_date"))
                                          or _indian_date(last_date(application).isoformat()))
        ask = t["ask_payment"]
    else:
        state_line, ask = t["waiting"], t["ask_status"]
    lines += [f"{opening} {state_line}", ""]
    if eligible:
        lines.append(t["meets"])
        lines += [f"- {line}" for line in decisive_clauses(trace_to_dict(trace, spec), said="")]
        lines.append("")
    lines += [ask, "", name, today.strftime("%d-%m-%Y")]
    return {
        "lang": lang,
        "text": "\n".join(lines),
        "grounded_in_rules": eligible,
        "send_to": [{"name": scheme.authority, "kind": "authority"}] if scheme.authority else [],
        "channels": channels_for(scheme),
    }


# ------------------------------------------------------------------------ calendar


def calendar(active: SchemeKB, spec: AttributeSpec, profile: Mapping[str, Any],
             applications: Iterable[Mapping[str, Any]], *, today: date | None = None,
             horizon_days: int = 365) -> list[dict[str, Any]]:
    """Everything with a date on it for one person, soonest first.

    Follow-ups come from the tracker, application windows from the schemes (only those
    with a sourced window), and birthdays that open or close a scheme from
    :func:`~tn_schemematch.outlook.coming_up`. The last have no calendar date — the
    vocabulary holds an age, not a date of birth — so they sort after the dated items.
    """
    from .outlook import coming_up

    today = today or date.today()
    items: list[dict[str, Any]] = []
    for application in applications:
        due = follow_up_due_on(application)
        if due is None or application["scheme_id"] not in active:
            continue
        scheme = active[application["scheme_id"]]
        items.append({
            "kind": "follow_up", "date": due.isoformat(), "overdue": due <= today,
            "scheme_id": scheme.id, "application_id": application["id"],
            "text": (f"Ask about your {scheme.name} application"
                     if application["status"] in WAITING else
                     f"Check that the {scheme.name} money has arrived")})

    buckets = active.match(profile)
    relevant = set(buckets[Verdict.TRUE]) | set(buckets[Verdict.UNKNOWN])
    for scheme_id in sorted(relevant):
        for window in active[scheme_id].windows:
            upcoming = window.next_from(today)
            if upcoming is None or (upcoming[0] - today).days > horizon_days:
                continue
            opens, closes = upcoming
            items.append({
                "kind": "window", "date": max(opens, today).isoformat(),
                "closes": closes.isoformat(), "open_now": opens <= today,
                "scheme_id": scheme_id, "source": window.source, "note": window.note,
                "confirmed": scheme_id in buckets[Verdict.TRUE],
                "text": (f"{active[scheme_id].name}: applications open until "
                         f"{closes.strftime('%d %b %Y')}" if opens <= today else
                         f"{active[scheme_id].name}: applications open "
                         f"{opens.strftime('%d %b %Y')}")})

    for event in coming_up(active, spec, profile):
        when = f"At {event['age']:.0f}" if event.get("age") else f"In {event['in_years']} years"
        for scheme in event["gains"]:
            items.append({"kind": "age", "date": None, "in_years": event["in_years"],
                          "scheme_id": scheme["id"], "gains": True,
                          "text": f"{when}: {scheme['name']} opens to you"})
        for scheme in event["loses"]:
            items.append({"kind": "age", "date": None, "in_years": event["in_years"],
                          "scheme_id": scheme["id"], "gains": False,
                          "text": f"{when}: {scheme['name']} closes — apply before then"})
    return sorted(items, key=lambda i: (i["date"] is None, i["date"] or "",
                                        i.get("in_years") or 0))
