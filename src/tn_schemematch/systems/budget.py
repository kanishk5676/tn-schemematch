"""What the model has cost, and a daily cap that turns the assistant to guided mode.

The project runs on a small prepaid credit. Two things go wrong without a meter: nobody
knows what a conversation costs, and when the credit runs out the assistant stops in the
middle of someone's turn. So every model call records its token usage here, priced from a
table, and a daily cap in US dollars is checked *before* each call. Over the cap, the call
is not made: :class:`BudgetExceeded` is raised, and the chat carries on in guided mode.

Prices are list prices per million tokens and an estimate, not a bill: the console is the
record of what was actually charged. Cache writes are priced at 1.25x input (the 5-minute
cache) and an unknown model at the most expensive known price, so the estimate errs high.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping


class ModelUnavailable(RuntimeError):
    """The model cannot be used right now. The caller switches to guided mode."""

    reason = "unavailable"


class BudgetExceeded(ModelUnavailable):
    """Today's spending cap is reached; no call was made."""

    reason = "daily_budget"


class CreditExhausted(ModelUnavailable):
    """The API says the account has no credit left."""

    reason = "no_credit"


class KeyRejected(ModelUnavailable):
    """The API key is missing, wrong or revoked."""

    reason = "key_rejected"


# USD per million tokens: input, output, cache read, cache write.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-fable-5-1": (10.0, 50.0, 0.25, 12.5),
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-sonnet-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
_MOST_EXPENSIVE = max(PRICES.values())


def price_of(model: str) -> tuple[float, float, float, float]:
    for name, price in PRICES.items():
        if model == name or model.startswith(name + "-"):
            return price
    return _MOST_EXPENSIVE


def cost_usd(model: str, usage: Any) -> float:
    """The list price of one response's usage."""
    def tokens(name: str) -> int:
        value = usage.get(name) if isinstance(usage, Mapping) else getattr(usage, name, 0)
        return int(value or 0)

    inp, out, read, write = price_of(model)
    return (tokens("input_tokens") * inp + tokens("output_tokens") * out
            + tokens("cache_read_input_tokens") * read
            + tokens("cache_creation_input_tokens") * write) / 1_000_000


@dataclass
class UsageMeter:
    """Per-day token and cost totals, kept in a small JSON file.

    ``daily_budget_usd`` of ``None`` means no cap (the meter still counts).
    """

    path: Path | None = None
    daily_budget_usd: float | None = None
    _days: dict[str, dict[str, float]] = field(default_factory=dict, init=False, repr=False)
    _lock: Any = field(default_factory=threading.Lock, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.path is not None:
            self.path = Path(self.path)
            try:
                self._days = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._days = {}

    @staticmethod
    def _today() -> str:
        return date.today().isoformat()

    def today(self) -> dict[str, float]:
        with self._lock:
            return dict(self._days.get(self._today(), {}))

    def spent_today(self) -> float:
        return float(self.today().get("usd", 0.0))

    def check(self) -> None:
        """Raise :class:`BudgetExceeded` if today's cap is already reached."""
        if self.daily_budget_usd is not None and self.spent_today() >= self.daily_budget_usd:
            raise BudgetExceeded(
                f"today's model budget of ${self.daily_budget_usd:.2f} is spent")

    def record(self, model: str, usage: Any) -> float:
        """Add one response's usage. Returns its estimated cost."""
        cost = cost_usd(model, usage)

        def tokens(name: str) -> int:
            value = usage.get(name) if isinstance(usage, Mapping) else getattr(usage, name, 0)
            return int(value or 0)

        with self._lock:
            day = self._days.setdefault(self._today(), {})
            day["calls"] = day.get("calls", 0) + 1
            for name in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                         "cache_creation_input_tokens"):
                day[name] = day.get(name, 0) + tokens(name)
            day["usd"] = round(day.get("usd", 0.0) + cost, 6)
            self._save()
        return cost

    def _save(self) -> None:
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._days, indent=1, sort_keys=True),
                                 encoding="utf-8")
        except OSError:
            pass  # a meter that cannot write must never take the assistant down

    def report(self) -> dict[str, Any]:
        """For /admin: today, the last week, and the cap."""
        with self._lock:
            recent = sorted(self._days.items(), reverse=True)[:7]
        return {
            "today": dict(recent[0][1]) if recent and recent[0][0] == self._today() else {},
            "days": [{"date": day, **values} for day, values in recent],
            "daily_budget_usd": self.daily_budget_usd,
            "total_usd": round(sum(v.get("usd", 0.0) for _, v in recent), 4),
        }
