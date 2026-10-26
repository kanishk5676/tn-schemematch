"""The usage meter and the daily cap: spending stops before the credit does."""

from types import SimpleNamespace

import pytest

from tn_schemematch.systems.budget import (
    BudgetExceeded,
    CreditExhausted,
    KeyRejected,
    UsageMeter,
    cost_usd,
)
from tn_schemematch.systems.clients import AnthropicClient


def usage(i=0, o=0, read=0, write=0):
    return SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=read,
                           cache_creation_input_tokens=write)


def test_costs_follow_the_price_table():
    assert cost_usd("claude-opus-5-5", usage(i=1_000_000)) == pytest.approx(4.0)
    assert cost_usd("claude-haiku-5-5", usage(o=1_000_000)) == pytest.approx(0.5)
    assert cost_usd("claude-sonnet-5-5", usage(read=1_000_000)) == pytest.approx(0.2)


def test_an_unknown_model_is_priced_high_not_free():
    assert cost_usd("claude-something-new", usage(i=1_000_000)) >= 4.0


def test_meter_adds_up_and_persists(tmp_path):
    path = tmp_path / "usage.json"
    meter = UsageMeter(path=path)
    meter.record("claude-haiku-5-5", usage(i=10_000, o=1_000))
    meter.record("claude-haiku-5-5", usage(i=10_000, o=1_000))
    assert meter.today()["calls"] == 2
    again = UsageMeter(path=path)
    assert again.spent_today() == pytest.approx(meter.spent_today())


def test_the_cap_refuses_before_spending(tmp_path):
    meter = UsageMeter(path=tmp_path / "usage.json", daily_budget_usd=0.01)
    meter.check()
    meter.record("claude-opus-5-5", usage(o=1_000))  # $0.02
    with pytest.raises(BudgetExceeded):
        meter.check()


class FakeSDK:
    def __init__(self, error=None):
        self.calls = 0
        self.error = error
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return SimpleNamespace(stop_reason="end_turn", model=kwargs["model"],
                               usage=usage(i=1_000, o=100),
                               content=[SimpleNamespace(type="text", text="{}")])


def test_client_records_usage_and_stops_at_the_cap():
    meter = UsageMeter(daily_budget_usd=0.004)
    client = AnthropicClient(meter=meter)
    client._client = fake = FakeSDK()
    client.complete("s", "u")  # 1000 in + 100 out on Opus 5.5 = $0.006
    assert meter.today()["calls"] == 1
    with pytest.raises(BudgetExceeded):
        client.complete("s", "u")
    assert fake.calls == 1, "a call over the cap must not reach the API"


def test_an_empty_credit_balance_is_recognised():
    class BadRequestError(Exception):
        pass

    client = AnthropicClient()
    client._client = FakeSDK(BadRequestError(
        "Your credit balance is too low to access the Anthropic API."))
    with pytest.raises(CreditExhausted):
        client.complete("s", "u")


def test_a_rejected_key_is_recognised():
    class AuthenticationError(Exception):
        pass

    client = AnthropicClient()
    client._client = FakeSDK(AuthenticationError("invalid x-api-key"))
    with pytest.raises(KeyRejected):
        client.complete("s", "u")


def test_other_errors_are_not_mistaken_for_an_empty_balance():
    client = AnthropicClient()
    client._client = FakeSDK(ValueError("something else"))
    with pytest.raises(RuntimeError) as info:
        client.complete("s", "u")
    assert not isinstance(info.value, (CreditExhausted, KeyRejected, BudgetExceeded))
