"""The model protocol, an offline scripted client, and the JSON helpers prompts share.

Everything that talks to a model goes through :class:`LLMClient` (plus the optional
``complete_with_images`` and ``converse`` capabilities described in
:mod:`tn_schemematch.systems.clients`). :class:`ScriptedClient` implements all three from
canned responses, so every model path in the product is tested with no key and no network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from ..attributes import AttributeSpec


# ------------------------------------------------------------------- LLM backend


@runtime_checkable
class LLMClient(Protocol):
    """Minimal backend interface. Implement this to plug in a model."""

    name: str

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        """Return the model's completion for a system + user prompt pair."""
        ...


@dataclass
class ScriptedClient:
    """Offline client that replays canned responses, keyed by substring of the prompt.

    Exists so every model path — prompts, parsing, the agent loop, document reading — can
    be exercised in CI with no API key and no nondeterminism. Tests that depend on a live
    model test the model, not the code.
    """

    responses: dict[str, str] = field(default_factory=dict)
    default: str = "{}"
    name: str = "scripted"
    calls: list[tuple[str, str]] = field(default_factory=list)
    # Agent turns, consumed in order by ``converse``: each is
    # {"stop_reason": ..., "content": [{"type": "text" | "tool_use", ...}, ...]}.
    turns: list[dict[str, Any]] = field(default_factory=list)
    image_calls: list[dict[str, Any]] = field(default_factory=list)
    conversations: list[dict[str, Any]] = field(default_factory=list)

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        self.calls.append((system, user))
        for key, response in self.responses.items():
            if key in user:
                return response
        return self.default

    def complete_with_images(self, system: str, user: str, images, *,
                             schema: dict[str, Any] | None = None,
                             effort: str | None = None) -> str:
        self.image_calls.append({"system": system, "user": user, "schema": schema,
                                 "media_types": [media for media, _ in images]})
        return self.complete(system, user, json_mode=True)

    def converse(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]], *, effort: str | None = None) -> "ScriptedMessage":
        # Snapshot, because the caller keeps appending to the same list.
        self.conversations.append({"system": system, "messages": json.loads(json.dumps(
            messages, default=str)), "tools": [t["name"] for t in tools]})
        turn = self.turns.pop(0) if self.turns else {
            "stop_reason": "end_turn", "content": [{"type": "text", "text": self.default}]}
        return ScriptedMessage(turn["stop_reason"],
                               [ScriptedBlock(dict(block)) for block in turn["content"]])


class ScriptedBlock:
    """A content block shaped like the SDK's: attribute access plus ``to_dict``."""

    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name) from None

    def to_dict(self, **_: Any) -> dict[str, Any]:
        return dict(self._data)


@dataclass
class ScriptedMessage:
    stop_reason: str
    content: list[ScriptedBlock]


# ------------------------------------------------------------------ shared helpers


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json_response(text: str) -> Any:
    """Pull a JSON object out of a model response, tolerating fenced code blocks.

    Parse failures raise, and the caller degrades (to rules only, or to asking the person)
    rather than repairing the output: a guessed repair is an unearned fact.
    """
    text = text.strip()
    if not text:
        raise ValueError("empty response")
    match = _JSON_BLOCK.search(text)
    if match:
        text = match.group(1).strip()
    else:
        start = min((i for i in (text.find("{"), text.find("[")) if i != -1), default=-1)
        if start > 0:
            text = text[start:]
    return json.loads(text)


def attribute_catalogue(spec: AttributeSpec) -> str:
    """The elicitable attribute vocabulary, rendered for a prompt."""
    lines = []
    for name in spec.elicitable_names():
        attr = spec[name]
        if attr.type == "enum":
            kind = f"one of [{', '.join(str(v) for v in attr.domain or ())}]"
        elif attr.type == "number":
            kind = f"number in {attr.unit or 'units'}"
        else:
            kind = "true/false"
        lines.append(f"- {name} ({kind}): {attr.description.strip().splitlines()[0]}")
    return "\n".join(lines)
