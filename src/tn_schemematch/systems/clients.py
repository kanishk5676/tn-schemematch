"""Model backends.

Kept behind the tiny :class:`~tn_schemematch.systems.base.LLMClient` protocol and imported
lazily, so the core package — KB, rules, elicitation, metrics — has no model dependency at
all and the whole test suite runs without a key.

Every client records temperature and any retry behaviour in ``name``, because that string
ends up in the results file and in the paper's system column. A run whose decoding
parameters cannot be reconstructed from its own output is not reproducible.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnthropicClient:
    """Anthropic Messages API backend."""

    model: str = "claude-sonnet-5"
    temperature: float = 0.0
    max_tokens: int = 2048
    max_retries: int = 3
    api_key: str | None = None
    name: str = field(init=False)
    _client: Any = field(init=False, default=None, repr=False)

    def __post_init__(self) -> None:
        self.name = f"anthropic:{self.model}@t{self.temperature}"

    def _ensure(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "anthropic package not installed — pip install '.[models]'"
                ) from exc
            self._client = anthropic.Anthropic(
                api_key=self.api_key or os.environ.get("ANTHROPIC_API_KEY")
            )
        return self._client

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        client = self._ensure()
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                response = client.messages.create(
                    model=self.model,
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                return "".join(
                    block.text for block in response.content if block.type == "text"
                )
            except Exception as exc:  # noqa: BLE001 — transport errors are retryable
                last = exc
                time.sleep(2**attempt)
        raise RuntimeError(f"{self.name} failed after {self.max_retries} attempts: {last}")


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

    Runs are re-scored far more often than they are re-generated — every metric change
    during error analysis would otherwise mean paying for the whole grid again. The cache
    is keyed on the exact prompt pair, so a prompt edit correctly misses.
    """

    inner: Any
    cache: dict[tuple[str, str], str] = field(default_factory=dict)
    name: str = field(init=False)
    hits: int = 0
    misses: int = 0

    def __post_init__(self) -> None:
        self.name = getattr(self.inner, "name", "unknown")

    def complete(self, system: str, user: str, *, json_mode: bool = False) -> str:
        key = (system, user)
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        self.misses += 1
        response = self.inner.complete(system, user, json_mode=json_mode)
        self.cache[key] = response
        return response
