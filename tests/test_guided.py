"""Guided mode: a whole conversation with no model, from the rule engine and fixed words."""

import pytest

from tn_schemematch import DEFAULT_QUESTION_BUDGET
from tn_schemematch.guided import (
    answer,
    default_questions,
    opening,
    read_answer,
    validate_questions,
)
from tn_schemematch.interview import Interview


@pytest.fixture(scope="module")
def book():
    return default_questions()


@pytest.fixture
def iv(kb, spec):
    return Interview(kb=kb, spec=spec, client=None)


def test_every_askable_attribute_has_words_in_both_languages(book, spec):
    assert validate_questions(book, spec) == []


def test_opening_greets_and_asks_the_policy_s_first_question(book, iv):
    state = iv.start("", max_questions=DEFAULT_QUESTION_BUDGET, use_ai=False)
    turn = opening(book, iv, state, "ta")
    assert turn["question"]["attr"] == iv.next_question(state)
    assert "வணக்கம்" in turn["say"]
    assert turn["question"]["text"] in turn["reply"]


def test_a_whole_conversation_by_buttons_reaches_the_gold_set(book, iv, kb, sample_personas):
    """Guided mode is the product, not a fallback: it must finish with the right answer."""
    for persona in list(sample_personas)[:8]:
        state = iv.start("", max_questions=DEFAULT_QUESTION_BUDGET, use_ai=False,
                         seed_profile=persona.known_profile())
        turn = opening(book, iv, state, "en")
        while not turn["done"]:
            attr = turn["question"]["attr"]
            value = persona.profile.get(attr)
            if value is None:
                turn = answer(book, iv, state, "en", attr=attr, skip=True)
            else:
                question = book[attr]
                # A number pad answers on the question's own scale.
                shown = value / question.scale if question.scale != 1 else value
                turn = answer(book, iv, state, "en", attr=attr, value=shown)
        assert set(kb.active().eligible_ids(state.profile)) == set(persona.gold_eligible(kb)), persona.id


@pytest.mark.parametrize("text,expected", [
    ("அறுபத்தைந்து", 65), ("sixty", 60), ("70 vayasu", 70), ("iruvathi anju", 25),
])
def test_spoken_ages_are_read(book, spec, text, expected):
    assert read_answer(book, spec, "age", text) == ("value", expected)


@pytest.mark.parametrize("text,expected", [
    ("ஆமாங்க", True), ("aama", True), ("yes", True), ("இல்லை", False), ("illainga", False),
])
def test_spoken_yes_and_no(book, spec, text, expected):
    assert read_answer(book, spec, "has_aadhaar", text) == ("value", expected)


@pytest.mark.parametrize("text", ["theriyathu", "தெரியாது", "I don't know", "skip"])
def test_dont_know_skips(book, spec, text):
    assert read_answer(book, spec, "has_aadhaar", text) == ("skip", None)


def test_an_option_label_is_an_answer(book, spec):
    assert read_answer(book, spec, "residence_type", "கிராமம்") == ("value", "rural")
    assert read_answer(book, spec, "marital_status", "not married") == ("value", "unmarried")


def test_a_two_month_bill_is_scaled_to_a_year(book, spec):
    assert read_answer(book, spec, "annual_electricity_units", "400") == ("value", 2400)
    # A reply that names its own period is taken at its word.
    assert read_answer(book, spec, "annual_electricity_units", "300 units per month") == ("value", 3600)


def test_number_pad_answers_are_scaled(book, iv):
    state = iv.start("", max_questions=DEFAULT_QUESTION_BUDGET, use_ai=False)
    # Ask electricity directly by making it the only open question is fiddly; check the
    # helper the route uses instead.
    from tn_schemematch.guided import scaled_value
    assert scaled_value(book, "annual_electricity_units", 400) == 2400
    assert scaled_value(book, "age", 40) == 40
    assert state.profile == {}


def test_an_unread_answer_is_asked_again_then_retired(book, iv):
    state = iv.start("", max_questions=DEFAULT_QUESTION_BUDGET, use_ai=False)
    first = opening(book, iv, state, "en")["question"]["attr"]
    turn = answer(book, iv, state, "en", attr=first, text="blue elephant")
    assert turn["understood"] is False and turn["question"]["attr"] == first
    turn = answer(book, iv, state, "en", attr=first, text="purple")
    assert turn["question"] is None or turn["question"]["attr"] != first
    assert first in state.skipped


def test_an_answer_to_a_stale_question_is_refused(book, iv):
    state = iv.start("", max_questions=DEFAULT_QUESTION_BUDGET, use_ai=False)
    current = opening(book, iv, state, "en")["question"]["attr"]
    other = next(a for a in iv.spec.elicitable_names() if a != current)
    assert answer(book, iv, state, "en", attr=other, value=1)["error"] == "stale"
    assert other not in state.profile


def test_sensitive_questions_say_they_can_be_skipped(book, iv, spec):
    state = iv.start("", max_questions=DEFAULT_QUESTION_BUDGET, use_ai=False)
    from tn_schemematch.guided import question_card
    card = question_card(book, iv, state, "social_category", "ta")
    assert card["sensitive"] is True
    card = question_card(book, iv, state, "age", "ta")
    assert card["sensitive"] is False


def test_choice_cards_carry_both_languages(book, iv):
    state = iv.start("", max_questions=DEFAULT_QUESTION_BUDGET, use_ai=False)
    from tn_schemematch.guided import question_card
    card = question_card(book, iv, state, "residence_type", "ta")
    assert card["control"] == "choice"
    assert {o["value"] for o in card["options"]} == {"rural", "urban"}
    assert card["options"][0]["label"] == "கிராமம்" and card["options"][0]["alt"] == "Village"
