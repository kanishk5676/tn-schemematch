"""The assistant with no model: a whole conversation from the rule engine and fixed words.

The agent (:mod:`tn_schemematch.agent`) lets a person speak freely and has a model work out
what they meant. That costs money on every message, and it stops when the key is missing
or the credit runs out. This module holds the same conversation without any model:

- **which** question comes next is the elicitation policy, exactly as in the agent;
- **the words** of the question come from ``kb/spec/questions.yaml``, in spoken Tamil and
  plain English;
- **the answer** is a button, a number, or a spoken or typed reply read by the
  deterministic parser (aliases, Tamil and English number words, units, and the option
  labels themselves).

So guided mode is not a fallback screen that says "sorry". It is the product working on its
own, and the model is an upgrade on top of it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml

from .attributes import AttributeSpec, SchemaError, _fold
from .interview import MAX_RETRIES, Interview, InterviewState, question_reason

DEFAULT_QUESTIONS_PATH = Path(__file__).resolve().parent.parent.parent / "kb" / "spec" / "questions.yaml"
LANGUAGES = ("ta", "en")

# Replies that mean "I don't know" or "skip", in the ways people say them.
_DONT_KNOW = {
    "theriyadhu", "theriyathu", "theriyala", "teriyala", "teriyadhu", "therila", "theriyaadhu",
    "தெரியாது", "தெரியல", "தெரியவில்லை", "dont know", "don t know", "do not know", "not sure",
    "idk", "skip", "pass", "vendam", "venam", "வேண்டாம்", "தவிர்", "thavir", "next",
    "sollamudiyathu", "solla mudiyathu", "சொல்ல முடியாது", "சொல்ல விருப்பமில்லை",
    "prefer not to say", "no comment",
}


class QuestionBookError(ValueError):
    """``questions.yaml`` is malformed."""


@dataclass(frozen=True)
class Question:
    attr: str
    ask: Mapping[str, str]
    label: Mapping[str, str] = field(default_factory=dict)
    options: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    unit: Mapping[str, str] = field(default_factory=dict)
    scale: float = 1.0


@dataclass
class QuestionBook:
    version: str
    reviewed: bool
    questions: dict[str, Question]

    def __contains__(self, attr: str) -> bool:
        return attr in self.questions

    def __getitem__(self, attr: str) -> Question:
        return self.questions[attr]

    def ask(self, attr: str, lang: str) -> str:
        question = self.questions.get(attr)
        if question is None:
            return attr.replace("_", " ") + "?"
        return question.ask.get(lang) or question.ask.get("en") or ""

    def label(self, attr: str, lang: str) -> str:
        question = self.questions.get(attr)
        if question is None:
            return attr.replace("_", " ")
        return question.label.get(lang) or question.label.get("en") or attr.replace("_", " ")

    def option_label(self, attr: str, value: Any, lang: str) -> str:
        question = self.questions.get(attr)
        labels = (question.options.get(str(value)) if question else None) or {}
        return labels.get(lang) or labels.get("en") or str(value).replace("_", " ")


def load_questions(path: str | Path | None = None) -> QuestionBook:
    path = Path(path) if path else DEFAULT_QUESTIONS_PATH
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions: dict[str, Question] = {}
    for attr, body in (raw.get("questions") or {}).items():
        if not isinstance(body, Mapping) or not isinstance(body.get("ask"), Mapping):
            raise QuestionBookError(f"{attr}: every question needs an 'ask' mapping")
        options = {str(value): dict(labels) for value, labels in (body.get("options") or {}).items()}
        questions[attr] = Question(attr=attr, ask=dict(body["ask"]),
                                   label=dict(body.get("label") or {}), options=options,
                                   unit=dict(body.get("unit") or {}),
                                   scale=float(body.get("scale") or 1.0))
    return QuestionBook(version=str(raw.get("version", "0")),
                        reviewed=bool(raw.get("reviewed", False)), questions=questions)


@lru_cache(maxsize=2)
def default_questions() -> QuestionBook:
    return load_questions()


def validate_questions(book: QuestionBook, spec: AttributeSpec) -> list[str]:
    """Every askable attribute has words in both languages, and every enum value a label.

    Without this a new attribute would be asked as its raw id — "is_secc_deprived_household?"
    — read aloud to someone who cannot read it either.
    """
    problems: list[str] = []
    for attr in spec.elicitable_names():
        if attr not in book:
            problems.append(f"questions.yaml: no question for {attr!r}")
            continue
        question = book[attr]
        for lang in LANGUAGES:
            if not question.ask.get(lang):
                problems.append(f"questions.yaml: {attr} has no {lang!r} question")
            if not question.label.get(lang):
                problems.append(f"questions.yaml: {attr} has no {lang!r} label")
        if spec[attr].type == "enum":
            for value in spec[attr].domain or ():
                labels = question.options.get(str(value)) or {}
                for lang in LANGUAGES:
                    if not labels.get(lang):
                        problems.append(f"questions.yaml: {attr}={value} has no {lang!r} label")
            extra = set(question.options) - {str(v) for v in spec[attr].domain or ()}
            if extra:
                problems.append(f"questions.yaml: {attr} labels unknown value(s) {sorted(extra)}")
    for attr in book.questions:
        if attr not in spec:
            problems.append(f"questions.yaml: {attr!r} is not an attribute")
    return problems


# ----------------------------------------------------------------------- answers


_PERIOD = re.compile(r"(maas|masa|maat|month|மாச|மாத|varusham|varudam|year|வருட|வருஷ)")


def read_answer(book: QuestionBook, spec: AttributeSpec, attr: str,
                text: str) -> tuple[str, Any]:
    """Read a spoken or typed reply to the question for ``attr``, with no model.

    Returns ``("value", v)``, ``("skip", None)`` for "I don't know", or ``("unread", None)``.
    """
    folded = _fold(text)
    if not folded:
        return "unread", None
    if folded in _DONT_KNOW or any(phrase in folded for phrase in _DONT_KNOW if " " in phrase):
        return "skip", None
    attribute = spec[attr]
    question = book.questions.get(attr)

    if attribute.type == "enum" and question is not None:
        # The option labels are answers too: someone may say the button instead of tapping.
        matches = []
        for value, labels in question.options.items():
            for label in labels.values():
                key = _fold(re.sub(r"\(.*?\)", " ", label))
                if key and (key == folded or (len(key) > 3 and key in folded)):
                    matches.append((len(key), value))
        if matches:
            value = max(matches)[1]
            domain = {str(v): v for v in attribute.domain or ()}
            return "value", domain.get(value, value)
    try:
        value = spec.canonicalize(attr, text)
    except SchemaError:
        return "unread", None
    if attribute.type == "number" and question is not None and question.scale != 1:
        # The question asked for a figure on its own scale (a two-month bill) unless the
        # reply names its own period.
        if not _PERIOD.search(folded):
            value = value * question.scale
    return "value", value


def scaled_value(book: QuestionBook, attr: str, value: Any) -> Any:
    """A number-pad answer on the question's own scale, converted to the rule's."""
    question = book.questions.get(attr)
    if question is None or question.scale == 1 or isinstance(value, bool):
        return value
    try:
        return float(value) * question.scale
    except (TypeError, ValueError):
        return value


def _number_text(value: float) -> str:
    """65 → "65", 2.5 → "2.5", 120000 → "1,20,000" (Indian grouping)."""
    if float(value).is_integer():
        digits = str(int(value))
        if len(digits) <= 3:
            return digits
        head, tail = digits[:-3], digits[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        return ",".join(groups + [tail])
    return f"{value:.2f}".rstrip("0").rstrip(".")


def answer_text(book: QuestionBook, spec: AttributeSpec, attr: str, value: Any,
                lang: str) -> str:
    """A stored value as the person would say it: "ஆம்", "விவசாயி", "2 ஏக்கர்"."""
    attribute = spec[attr]
    if attribute.type == "bool":
        return BUTTONS["yes" if value else "no"][lang]
    if attribute.type == "enum":
        return book.option_label(attr, value, lang)
    question = book.questions.get(attr)
    shown = value / question.scale if question is not None and question.scale != 1 else value
    unit = (question.unit.get(lang) if question else "") or ""
    return f"{_number_text(float(shown))} {unit}".strip()


def told(book: QuestionBook, spec: AttributeSpec, profile: Mapping[str, Any],
         lang: str) -> list[dict[str, Any]]:
    """What the person has said, in their language, for "what you told me"."""
    rows = []
    for attr in spec.elicitable_names():
        if profile.get(attr) is None:
            continue
        rows.append({"attr": attr, "label": book.label(attr, lang),
                     "display": answer_text(book, spec, attr, profile[attr], lang)})
    return rows


# ------------------------------------------------------------------------ phrases


PHRASES: dict[str, dict[str, str]] = {
    "hello": {
        "ta": "வணக்கம்! நான் உதவி. உங்களுக்கு எந்த அரசுத் திட்டங்கள் கிடைக்கும் என்று கண்டுபிடிக்கச் சில கேள்விகள் கேட்கிறேன். பதில் தெரியவில்லை என்றால் 'தெரியாது' என்று சொல்லுங்கள்.",
        "en": "Hello! I am Udhavi. I will ask a few questions to find the government schemes you can get. If you don't know an answer, just say 'I don't know'.",
    },
    "welcome_back": {
        "ta": "வணக்கம்! முன்பு சொன்னவை என்னிடம் இருக்கின்றன. இன்னும் சில கேள்விகள் மட்டும்.",
        "en": "Welcome back! I still have what you told me before. Just a few more questions.",
    },
    "ack": {"ta": "சரி.", "en": "Got it."},
    "skipped": {"ta": "பரவாயில்லை, அடுத்த கேள்வி.", "en": "That's fine, next question."},
    "unread": {
        "ta": "மன்னிக்கவும், புரியவில்லை. கீழே உள்ள பொத்தானைத் தொடுங்கள், அல்லது வேறு மாதிரி சொல்லுங்கள்.",
        "en": "Sorry, I didn't understand. Tap a button below, or say it another way.",
    },
    "gave_up": {
        "ta": "இதை விட்டுவிடுவோம். அடுத்த கேள்வி.",
        "en": "Let's leave this one. Next question.",
    },
    "sensitive": {
        "ta": "சொல்ல விருப்பம் இல்லை என்றால் 'தவிர்' என்பதைத் தொடுங்கள்.",
        "en": "You don't have to answer this. Tap 'Skip' if you prefer.",
    },
    "why_one": {"ta": "இந்தப் பதில் ஒரு திட்டத்தை முடிவு செய்யும்.",
                "en": "This answer decides 1 scheme."},
    "why_many": {"ta": "இந்தப் பதில் {n} திட்டங்களை முடிவு செய்யும்.",
                 "en": "This answer decides {n} schemes."},
    "done": {
        "ta": "நன்றி! எல்லாக் கேள்விகளும் முடிந்தன.",
        "en": "Thank you! That's all the questions.",
    },
    "out_of_credit": {
        "ta": "இப்போது நான் கேள்விகள் மூலம் தொடர்கிறேன்.",
        "en": "I'll carry on with simple questions now.",
    },
}

BUTTONS: dict[str, dict[str, str]] = {
    "yes": {"ta": "ஆம்", "en": "Yes"},
    "no": {"ta": "இல்லை", "en": "No"},
    "dont_know": {"ta": "தெரியாது", "en": "Don't know"},
    "skip": {"ta": "தவிர்", "en": "Skip"},
}


def phrase(key: str, lang: str, **values: Any) -> str:
    text = PHRASES[key].get(lang) or PHRASES[key]["en"]
    return text.format(**values) if values else text


# -------------------------------------------------------------------- the turns


def question_card(book: QuestionBook, iv: Interview, state: InterviewState, attr: str,
                  lang: str) -> dict[str, Any]:
    """Everything the page needs to ask one question: the words, in the chosen language
    and the other one, and the control to answer with."""
    attribute = iv.spec[attr]
    question = book.questions.get(attr)
    other = "en" if lang == "ta" else "ta"
    if attribute.type == "bool":
        control = "yesno"
        options = [{"value": True, "label": BUTTONS["yes"][lang], "alt": BUTTONS["yes"][other]},
                   {"value": False, "label": BUTTONS["no"][lang], "alt": BUTTONS["no"][other]}]
    elif attribute.type == "enum":
        control = "choice"
        options = [{"value": value, "label": book.option_label(attr, value, lang),
                    "alt": book.option_label(attr, value, other)}
                   for value in attribute.domain or ()]
    else:
        control = "number"
        options = []
    settles = question_reason(iv.active, state.profile, attr)["settles"]
    why = (phrase("why_one", lang) if settles == 1
           else phrase("why_many", lang, n=settles) if settles > 1 else "")
    sensitive = attribute.sensitivity == "high"
    return {
        "attr": attr,
        "text": book.ask(attr, lang),
        "alt": book.ask(attr, other),
        "control": control,
        "options": options,
        "unit": (question.unit.get(lang) if question else "") or "",
        "scale": question.scale if question else 1.0,
        "min": attribute.domain[0] if attribute.type == "number" and attribute.domain else None,
        "max": attribute.domain[1] if attribute.type == "number" and attribute.domain else None,
        "sensitive": sensitive,
        "why": why,
        "skip_label": BUTTONS["skip"][lang],
        "dont_know_label": BUTTONS["dont_know"][lang],
        "index": len(state.asked) + 1,
    }


def _say_question(card: Mapping[str, Any], lang: str) -> str:
    parts = [card["text"]]
    if card["sensitive"]:
        parts.append(phrase("sensitive", lang))
    return " ".join(parts)


def opening(book: QuestionBook, iv: Interview, state: InterviewState, lang: str, *,
            returning: bool = False) -> dict[str, Any]:
    """The first turn: a greeting and the first question."""
    greeting = phrase("welcome_back" if returning else "hello", lang)
    return _next(book, iv, state, lang, lead=greeting)


def answer(book: QuestionBook, iv: Interview, state: InterviewState, lang: str, *,
           attr: str, value: Any = None, text: str | None = None,
           skip: bool = False) -> dict[str, Any]:
    """One answer — a button value, a typed or spoken reply, or a skip — and the next turn.

    The answer must be for the question currently asked. A stale page answering an old
    question is refused rather than applied to the wrong attribute.
    """
    current = iv.next_question(state)
    if attr != current:
        return {"error": "stale", "expected": current}

    if skip:
        iv.skip(state, attr)
        return _next(book, iv, state, lang, lead=phrase("skipped", lang))

    if text is not None:
        kind, parsed = read_answer(book, iv.spec, attr, text)
        if kind == "skip":
            iv.skip(state, attr)
            return _next(book, iv, state, lang, lead=phrase("skipped", lang))
        if kind == "unread":
            state.retries[attr] = state.retries.get(attr, 0) + 1
            if state.retries[attr] >= MAX_RETRIES:
                iv.skip(state, attr)
                return _next(book, iv, state, lang, lead=phrase("gave_up", lang))
            card = question_card(book, iv, state, attr, lang)
            reply = phrase("unread", lang)
            return {"reply": reply, "lead": reply, "say": reply + " " + _say_question(card, lang),
                    "question": card, "done": False, "understood": False}
        state.retries.pop(attr, None)
        outcome = iv.answer_value(state, attr, parsed, source="said")
    else:
        outcome = iv.answer_value(state, attr, scaled_value(book, attr, value), source="form")

    if outcome.source == "rejected":
        card = question_card(book, iv, state, attr, lang)
        reply = phrase("unread", lang)
        return {"reply": reply, "say": reply, "question": card, "done": False,
                "understood": False, "message": outcome.message}
    return _next(book, iv, state, lang, lead=phrase("ack", lang))


def _next(book: QuestionBook, iv: Interview, state: InterviewState, lang: str, *,
          lead: str) -> dict[str, Any]:
    attr = iv.next_question(state)
    if attr is None:
        state.finished = True
        reply = f"{lead} {phrase('done', lang)}".strip()
        return {"reply": reply, "say": reply, "question": None, "done": True,
                "understood": True}
    card = question_card(book, iv, state, attr, lang)
    reply = f"{lead} {card['text']}".strip()
    # ``lead`` alone is what a page that shows the question card needs in the bubble.
    return {"reply": reply, "lead": lead, "say": f"{lead} {_say_question(card, lang)}".strip(),
            "question": card, "done": False, "understood": True}
