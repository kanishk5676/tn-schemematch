"""Model backends.

Kept behind the tiny :class:`~tn_schemematch.systems.base.LLMClient` protocol and imported
lazily, so the core package — KB, rules, elicitation — has no model dependency at all and
the whole test suite runs without a key.

Every client records its model and decoding configuration in ``name``, which the page shows
and the usage meter prices by.

**Sampling parameters are gone.** The Anthropic API no longer accepts ``temperature``,
``top_p`` or ``top_k`` (the 1.x SDK does not even take them as arguments, and current models
reject them). ``effort`` is the one decoding knob. :class:`CachingClient` can dump every raw
response to a JSONL file and replay it, which is how a demo is rehearsed once and then
replayed for free.

**Money.** An optional :class:`~tn_schemematch.systems.budget.UsageMeter` is checked before
each call and fed after it. A spent daily cap, a spent credit balance or a rejected key all
raise :class:`~tn_schemematch.systems.budget.ModelUnavailable`, which the assistant answers
by carrying on in guided mode rather than failing the person's turn.

Two capabilities sit beside the protocol's ``complete`` and are detected with ``hasattr``
by the code that needs them, so a backend without them degrades with a clear message:

- ``complete_with_images`` — read a photographed document (:mod:`tn_schemematch.documents`).
- ``converse`` — one step of a multi-turn, tool-using conversation (:mod:`tn_schemematch.agent`).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from .budget import CreditExhausted, KeyRejected, ModelUnavailable

DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"

# Server-side refusal fallback: when a safety classifier declines a request, the API re-runs
# it on the model Anthropic recommends for that refusal category, inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class ModelRefusal(RuntimeError):
    """The model (and any fallback) declined the request. Callers treat it like any other
    model failure: the interview degrades to rules only."""


@dataclass
class AnthropicClient:
    """Anthropic Messages API backend.

    ``effort`` replaces temperature as the one decoding knob: it sets how much the model
    thinks before answering. ``low`` suits the short JSON calls this project makes —
    extracting slots, normalizing one answer — where latency is felt on screen.
    """

    model: str = DEFAULT_ANTHROPIC_MODEL
    effort: str = "low"
    # Adaptive thinking spends from this budget too, so it is set well above any answer.
    max_tokens: int = 16000
    max_retries: int = 3
    # Server-side refusal fallback. Off for Haiku, which has none.
    fallbacks: bool | None = None
    api_key: str | None = None
    # A :class:`~.budget.UsageMeter`: checked before each call, fed after it.
    meter: Any = None
    name: str = field(init=False)
    _client: Any = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        if self.fallbacks is None:
            self.fallbacks = not self.model.startswith("claude-haiku")
        self.name = f"anthropic:{self.model}@effort-{self.effort}"

    def _ensure(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "anthropic package not installed — pip install '.[models]'"
                ) from exc
            # No key argument when none is configured: the SDK then resolves credentials
            # itself (ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, or an `ant auth login`
            # profile). Retries on 429/5xx/connection errors are the SDK's job too.
            kwargs: dict[str, Any] = {"max_retries": self.max_retries}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            self._client = anthropic.Anthropic(**kwargs)
        return self._client

    def _request(self, *, system: str, messages: list[dict[str, Any]],
                 effort: str | None = None, output_format: dict[str, Any] | None = None,
                 tools: list[dict[str, Any]] | None = None, cache: bool = False) -> Any:
        """One Messages call. Returns the raw response after checking for a refusal."""
        output_config: dict[str, Any] = {"effort": effort or self.effort}
        if output_format is not None:
            output_config["format"] = output_format
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
            "output_config": output_config,
        }
        if tools:
            kwargs["tools"] = tools
        if cache:
            # Automatic caching of the longest stable prefix: tools, system prompt and the
            # conversation so far are re-sent on every step of an agent turn.
            kwargs["cache_control"] = {"type": "ephemeral"}
        if self.fallbacks:
            kwargs["betas"] = [FALLBACK_BETA]
            kwargs["fallbacks"] = "default"
        if self.meter is not None:
            self.meter.check()  # over today's cap: no call is made at all
        try:
            response = self._ensure().beta.messages.create(**kwargs)
        except Exception as exc:  # noqa: BLE001 — surfaced to the caller with our name on it
            unavailable = _unavailable(exc)
            if unavailable is not None:
                raise unavailable(f"{self.name}: {exc}") from exc
            raise RuntimeError(f"{self.name} failed: {type(exc).__name__}: {exc}") from exc
        if self.meter is not None and getattr(response, "usage", None) is not None:
            self.meter.record(getattr(response, "model", None) or self.model, response.usage)
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            category = getattr(details, "category", None) if details else None
            raise ModelRefusal(f"{self.name} declined the request (category: {category})")
        return response

    @staticmethod
    def _text(response: Any) -> str:
        return "".join(block.text for block in response.content if block.type == "text")

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        # json_mode is honoured by the prompts themselves ("Reply with JSON only"); the
        # parse is strict downstream, so a non-JSON answer is recorded as the model's error.
        response = self._request(system=system,
                                 messages=[{"role": "user", "content": user}])
        return self._text(response)

    def complete_with_images(self, system: str, user: str,
                             images: Sequence[tuple[str, bytes]], *,
                             schema: dict[str, Any] | None = None,
                             effort: str | None = "medium") -> str:
        """Read one or more images. With ``schema``, the reply is guaranteed valid JSON.

        Images go before the text: the instruction reads better after the model has seen
        what it is about.
        """
        content: list[dict[str, Any]] = [
            {"type": "image", "source": {
                "type": "base64", "media_type": media_type,
                "data": base64.standard_b64encode(data).decode("ascii")}}
            for media_type, data in images
        ]
        content.append({"type": "text", "text": user})
        output_format = ({"type": "json_schema", "schema": schema}
                         if schema is not None else None)
        response = self._request(system=system, messages=[{"role": "user", "content": content}],
                                 effort=effort, output_format=output_format)
        return self._text(response)

    def converse(self, system: str, messages: list[dict[str, Any]],
                 tools: list[dict[str, Any]], *, effort: str | None = "medium") -> Any:
        """One step of a tool-using conversation. Returns the raw response, whose
        ``content`` the caller must append to the history unchanged."""
        return self._request(system=system, messages=messages, tools=tools, effort=effort,
                             cache=True)


def _unavailable(exc: Exception) -> type[ModelUnavailable] | None:
    """Errors that mean "the model is not usable now", as opposed to a bad request.

    Matched by the SDK's class names, so this module still imports without the SDK.
    """
    names = {cls.__name__ for cls in type(exc).__mro__}
    if names & {"AuthenticationError", "PermissionDeniedError"}:
        return KeyRejected
    if "credit balance" in str(exc).lower():
        return CreditExhausted
    return None


@dataclass
class OpenAIClient:
    """OpenAI chat-completions backend."""

    model: str = "gpt-4o"
    temperature: float = 0.0
    max_tokens: int = 2048
    max_retries: int = 3
    api_key: str | None = None
    name: str = field(init=False)
    _client: Any = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.name = f"openai:{self.model}@t{self.temperature}"

    def _ensure(self) -> Any:
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "openai package not installed — pip install '.[models]'"
                ) from exc
            self._client = OpenAI(api_key=self.api_key or os.environ.get("OPENAI_API_KEY"))
        return self._client

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        client = self._ensure()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = client.chat.completions.create(**kwargs)
                return response.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                last = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"{self.name} failed after {self.max_retries} attempts: {last}")


@dataclass
class CachingClient:
    """Wraps another client and memoizes on (system, user).

    The same sentence extracted twice costs once. The cache is keyed on the exact prompt
    pair, so a prompt edit correctly misses.

    It is also a recording. With sampling parameters gone a second call need not return
    the same text, so :meth:`dump` writes every response to a file and :meth:`load`
    replays them — a rehearsed demo makes no model call at all.
    """

    inner: Any
    cache: dict[tuple[str, str], str] = field(default_factory=dict)
    name: str = field(init=False)
    hits: int = 0
    misses: int = 0

    def __post_init__(self) -> None:
        self.name = getattr(self.inner, "name", "unknown")
        # Optional capabilities are exposed only when the wrapped client has them, so a
        # hasattr check on the wrapper answers the same as one on the client.
        if hasattr(self.inner, "complete_with_images"):
            self.complete_with_images = self._complete_with_images
        if hasattr(self.inner, "converse"):
            # Conversations are stateful and never repeat exactly; nothing to cache.
            self.converse = self.inner.converse

    @property
    def meter(self) -> Any:
        return getattr(self.inner, "meter", None)

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        key = (system, user)
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        response = self.inner.complete(system, user, json_mode=json_mode)
        self.cache[key] = response
        return response

    def _complete_with_images(self, system: str, user: str,
                              images: Sequence[tuple[str, bytes]], **kwargs: Any) -> str:
        digest = hashlib.sha256(b"".join(data for _, data in images)).hexdigest()
        key = (system, f"{user}\n[images sha256:{digest}]")
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        response = self.inner.complete_with_images(system, user, images, **kwargs)
        self.cache[key] = response
        return response

    def dump(self, path: str | Path) -> int:
        """Write every cached response as JSONL. Returns the number written."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for (system, user), response in self.cache.items():
                handle.write(json.dumps({"system": system, "user": user,
                                         "response": response}, ensure_ascii=False) + "\n")
        return len(self.cache)

    def load(self, path: str | Path) -> int:
        """Preload responses written by :meth:`dump`. Returns the number loaded."""
        loaded = 0
        with Path(path).open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    self.cache[(row["system"], row["user"])] = row["response"]
                    loaded += 1
        return loaded


# ------------------------------------------------------------------ construction


def has_credentials(backend: str) -> bool:
    """Whether a backend can plausibly authenticate, checked before binding a port.

    For Anthropic an unset ``ANTHROPIC_API_KEY`` is not the end of it: the SDK also reads
    ``ANTHROPIC_AUTH_TOKEN`` and the profile ``ant auth login`` stores on disk.
    """
    if backend == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY")
                    or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                    or (Path.home() / ".config" / "anthropic").exists())
    if backend == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    return True


def make_client(backend: str, model: str | None = None, *,
                max_retries: int = 3, meter: Any = None) -> CachingClient | None:
    """The one place a backend name becomes a client. ``none`` means rules only."""
    if backend == "none":
        return None
    if backend == "anthropic":
        inner: Any = AnthropicClient(model=model or DEFAULT_ANTHROPIC_MODEL,
                                     max_retries=max_retries, meter=meter)
    elif backend == "openai":
        inner = OpenAIClient(model=model or OpenAIClient.model, max_retries=max_retries)
    else:
        raise ValueError(f"unknown backend {backend!r}")
    return CachingClient(inner)
