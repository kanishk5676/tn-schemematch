"""The request each model client actually sends, checked with no network.

A fake stands in for the SDK client, so these tests assert on the exact keyword arguments
that would reach the API. That is the only place a removed parameter shows up before a
live call fails: the 1.x SDK rejects ``temperature`` as an unexpected argument, and the
backend's broad exception handling would turn that into a silent rules-only fallback.
"""

import json
from types import SimpleNamespace

import pytest

from tn_schemematch.systems.clients import (
    FALLBACK_BETA,
    AnthropicClient,
    CachingClient,
    ModelRefusal,
    make_client,
)


class FakeSDK:
    """Captures ``beta.messages.create`` kwargs and returns a canned response."""

    def __init__(self, text="{}", stop_reason="end_turn"):
        self.requests = []
        self._text = text
        self._stop_reason = stop_reason
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.requests.append(kwargs)
        return SimpleNamespace(
            stop_reason=self._stop_reason,
            stop_details=SimpleNamespace(category="general_harms")
            if self._stop_reason == "refusal" else None,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=self._text)],
        )


def client_with(fake, **kwargs):
    client = AnthropicClient(**kwargs)
    client._client = fake
    return client


def test_no_sampling_parameters_are_sent():
    fake = FakeSDK()
    client_with(fake).complete("system", "user")
    request = fake.requests[0]
    for removed in ("temperature", "top_p", "top_k"):
        assert removed not in request


def test_effort_and_refusal_fallback_are_sent():
    fake = FakeSDK()
    client_with(fake, effort="low").complete("system", "user")
    request = fake.requests[0]
    assert request["output_config"] == {"effort": "low"}
    assert request["betas"] == [FALLBACK_BETA]
    assert request["fallbacks"] == "default"
    assert request["model"] == "claude-opus-5-5"


def test_haiku_gets_no_fallback():
    """Haiku has no server-side fallback; sending one is wasted or a 400."""
    fake = FakeSDK()
    client_with(fake, model="claude-haiku-5-5").complete("system", "user")
    assert "fallbacks" not in fake.requests[0]


def test_only_text_blocks_are_returned():
    fake = FakeSDK(text='{"age": 45}')
    assert client_with(fake).complete("system", "user") == '{"age": 45}'


def test_refusal_raises_instead_of_returning_empty_text():
    fake = FakeSDK(stop_reason="refusal")
    with pytest.raises(ModelRefusal, match="general_harms"):
        client_with(fake).complete("system", "user")


def test_sdk_errors_carry_the_client_name():
    def boom(**kwargs):
        raise ValueError("bad key")
    client = AnthropicClient()
    client._client = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=boom)))
    with pytest.raises(RuntimeError, match="anthropic:claude-opus-5-5"):
        client.complete("system", "user")


def test_image_request_puts_images_first_and_constrains_json():
    fake = FakeSDK(text='{"doc_type": "ration_card"}')
    schema = {"type": "object", "properties": {"doc_type": {"type": "string"}},
              "required": ["doc_type"], "additionalProperties": False}
    out = client_with(fake).complete_with_images(
        "read this", "what document is it?", [("image/jpeg", b"\xff\xd8jpeg")], schema=schema)
    assert json.loads(out)["doc_type"] == "ration_card"

    request = fake.requests[0]
    content = request["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "text"]
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert request["output_config"]["format"] == {"type": "json_schema", "schema": schema}
    assert request["output_config"]["effort"] == "medium"


def test_converse_sends_tools_and_full_history():
    fake = FakeSDK()
    history = [{"role": "user", "content": "vanakkam"}]
    tools = [{"name": "get_profile", "description": "x", "input_schema": {"type": "object"}}]
    client_with(fake).converse("agent", history, tools)
    assert fake.requests[0]["tools"] == tools
    assert fake.requests[0]["messages"] == history


def test_caching_client_exposes_only_what_the_inner_client_has():
    full = CachingClient(AnthropicClient())
    assert hasattr(full, "complete_with_images") and hasattr(full, "converse")
    bare = CachingClient(SimpleNamespace(name="bare", complete=lambda *a, **k: "{}"))
    assert not hasattr(bare, "complete_with_images")
    assert not hasattr(bare, "converse")


def test_responses_round_trip_through_jsonl(tmp_path):
    calls = []
    inner = SimpleNamespace(name="inner",
                            complete=lambda s, u, json_mode=False: calls.append(u) or f"r:{u}")
    first = CachingClient(inner)
    first.complete("sys", "a")
    first.complete("sys", "b")
    assert first.dump(tmp_path / "responses.jsonl") == 2

    replay = CachingClient(inner)
    assert replay.load(tmp_path / "responses.jsonl") == 2
    assert replay.complete("sys", "a") == "r:a"
    assert len(calls) == 2  # the replay made no new call
    assert replay.hits == 1 and replay.misses == 0


def test_make_client_defaults():
    assert make_client("none") is None
    assert make_client("anthropic").name == "anthropic:claude-opus-5-5@effort-low"
    assert make_client("anthropic", "claude-sonnet-5-5").name.startswith(
        "anthropic:claude-sonnet-5-5")
