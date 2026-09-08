"""The resumable interview engine.

Every test here runs offline. The model is a :class:`ScriptedClient`, so the AI paths are
exercised without a key and without a network — which is also the demo's fallback posture.
"""

import json

import pytest

from tn_schemematch.attributes import SchemaError
from tn_schemematch.interview import (
    Interview,
    InterviewState,
    extract_attributes,
    normalize_extraction,
    parse_answer,
)
from tn_schemematch.systems.base import ScriptedClient


@pytest.fixture
def interview(kb, spec):
    return Interview(kb=kb, spec=spec, client=None)


def drive(iv, persona, *, max_questions=40):
    """Run a whole interview, answering truthfully from a persona's full profile."""
    state = iv.start(persona.queries["code_mixed"], max_questions=max_questions, use_ai=False)
    while True:
        attr = iv.next_question(state)
        if attr is None:
            return state
        value = persona.profile.get(attr)
        if value is None:
            iv.skip(state, attr)
        else:
            iv.answer_value(state, attr, value)


# ------------------------------------------------------------------ state contract


def test_state_round_trips_through_json(interview, personas):
    """The session-storage contract: state must survive a serialize/deserialize cycle."""
    state = drive(interview, personas["p001"], max_questions=6)
    restored = InterviewState.from_dict(json.loads(json.dumps(state.to_dict())))
    assert restored.profile == state.profile
    assert restored.asked == state.asked
    assert restored.skipped == state.skipped


def test_state_ignores_unknown_keys(interview):
    """A stored session from an older shape must not crash the server on load."""
    restored = InterviewState.from_dict({"query": "hi", "some_future_field": 1})
    assert restored.query == "hi"


# ------------------------------------------------------------------ the loop itself


def test_skipped_questions_are_not_reasked(interview):
    """The infinite-loop guard.

    question_priority is a pure function of (kb, profile) with no memory, so a declined
    question is re-ranked to the top on the next turn unless `skipped` holds it back.
    """
    state = interview.start("", use_ai=False)
    seen = []
    for _ in range(5):
        attr = interview.next_question(state)
        assert attr is not None
        seen.append(attr)
        interview.skip(state, attr)
    assert len(set(seen)) == 5, f"a skipped question came back: {seen}"


def test_question_budget_is_enforced(interview):
    state = interview.start("", max_questions=3, use_ai=False)
    for _ in range(3):
        interview.skip(state, interview.next_question(state))
    assert interview.next_question(state) is None


def test_interview_reaches_the_gold_set(interview, kb, sample_personas):
    """The headless mirror of the grounding pipeline's gold-answer test."""
    for persona in list(sample_personas)[:6]:
        state = drive(interview, persona)
        got = {card["id"] for card in interview.results(state)["eligible"]}
        assert got == set(persona.gold_eligible(kb)), f"{persona.id} diverged"


def test_answers_settle_schemes(interview, personas):
    state = drive(interview, personas["p001"], max_questions=10)
    assert sum(row["settled"] for row in state.history) > 0


# ------------------------------------------------------------------ the two invariants


def test_derived_attributes_are_never_accepted(interview, spec):
    """A caller must not be able to contradict the vocabulary."""
    state = interview.start("", use_ai=False)
    outcome = interview.answer_value(state, "is_widow", True)
    assert not outcome.accepted
    assert "derived" in (outcome.message or "")
    assert "is_widow" not in state.profile


def test_derive_runs_after_every_answer(interview):
    """is_widow must appear from marital_status without ever being asked."""
    state = interview.start("", use_ai=False)
    interview.answer_value(state, "marital_status", "widowed")
    assert state.profile.get("is_widow") is True
    assert "is_widow" not in state.asked


def test_unknown_attribute_is_rejected(interview):
    state = interview.start("", use_ai=False)
    outcome = interview.answer_value(state, "favourite_colour", "blue")
    assert not outcome.accepted


# ------------------------------------------------------------------ answer parsing


def test_parse_answer_prefers_aliases_over_the_model(spec):
    """Most answers must never reach the model — that is the design claim, so test it."""
    client = ScriptedClient(default=json.dumps({"value": 99.0}))
    value, source = parse_answer(spec, "land_owned_acres", "2 ekkar", client)
    assert (value, source) == (2.0, "aliases")
    assert client.calls == [], "the alias table should have settled this with no model call"


def test_parse_answer_falls_back_to_the_model(spec):
    """'rendu ekkar' has no digit, so the deterministic parser cannot read it."""
    client = ScriptedClient(default=json.dumps({"value": 2.0}))
    value, source = parse_answer(spec, "land_owned_acres", "rendu ekkar", client)
    assert (value, source) == (2.0, "model")
    assert len(client.calls) == 1


def test_unparseable_answer_is_not_guessed(spec):
    value, source = parse_answer(spec, "land_owned_acres", "konjam", None)
    assert value is None and source == "unparsed"


def test_model_may_decline_to_answer(spec):
    """A model that says 'not stated' must not be turned into a value."""
    client = ScriptedClient(default=json.dumps({"value": None}))
    value, source = parse_answer(spec, "age", "hard to say", client)
    assert value is None and source == "model-said-unstated"


def test_short_aliases_do_not_match_inside_words(spec):
    """Regression: 'm' once matched inside 'pombala', reading Tamil for woman as male.

    Unanchored substring matching on one- and two-character abbreviations silently
    produced a wrong canonical value instead of failing, which is the worst outcome
    available — the interview never asks, and the wrong rule branch is taken.
    """
    for word in ("pombala", "amma"):
        with pytest.raises(SchemaError):
            spec.canonicalize("gender", word)
    with pytest.raises(SchemaError):
        spec.canonicalize("education_level", "male")
    # exact abbreviations must still resolve
    assert spec.canonicalize("gender", "m") == "male"
    assert spec.canonicalize("education_level", "ma") == "postgraduate"


def test_two_bad_answers_retire_the_question(interview):
    """One stubborn phrasing must not be able to stall the interview."""
    state = interview.start("", use_ai=False)
    attr = interview.next_question(state)
    first = interview.answer_text(state, attr, "!!!")
    assert not first.accepted and attr not in state.skipped
    second = interview.answer_text(state, attr, "!!!")
    assert second.accepted and attr in state.skipped
    assert interview.next_question(state) != attr


# ------------------------------------------------------------------ extraction


def test_extraction_normalizes_code_mixed_values(spec):
    client = ScriptedClient(default=json.dumps(
        {"occupation": "விவசாயி", "land_owned_acres": "2 ekkar"}))
    raw = extract_attributes(client, spec, "naan vivasayi")
    profile, rejected = normalize_extraction(spec, raw)
    assert profile["occupation"] == "farmer"
    assert profile["land_owned_acres"] == 2.0
    assert not rejected


def test_extraction_drops_slots_outside_the_vocabulary(spec):
    profile, rejected = normalize_extraction(spec, {"vibe": "rural", "age": 40})
    assert "vibe" not in profile
    assert any("not in vocabulary" in r for r in rejected)


def test_extraction_refuses_a_derived_slot(spec):
    profile, rejected = normalize_extraction(spec, {"is_widow": True})
    assert "is_widow" not in profile
    assert any("derived" in r for r in rejected)


def test_extraction_failure_degrades_to_rules_only(kb, spec):
    """A model returning prose must leave a usable, empty-profile interview."""
    iv = Interview(kb=kb, spec=spec, client=ScriptedClient(default="I cannot help with that"))
    state = iv.start("naan vivasayi")
    assert state.extraction_error is not None
    assert state.profile == {}
    assert iv.next_question(state) is not None


def test_start_without_ai_makes_no_model_call(kb, spec):
    """The offline demo path: the toggle must genuinely not touch the client."""
    client = ScriptedClient(default="{}")
    iv = Interview(kb=kb, spec=spec, client=client)
    state = iv.start("naan vivasayi", use_ai=False)
    assert client.calls == []
    assert state.used_ai is False
