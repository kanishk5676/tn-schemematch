"""The assistant over HTTP in both modes, and the switch between them.

Guided mode needs no model at all; the agent hands over to it when the model fails, the
credit runs out or the day's budget is spent. Every test here runs with no key.
"""

import pytest

pytest.importorskip("flask")

from tn_schemematch.guided import default_questions  # noqa: E402
from tn_schemematch.systems.base import ScriptedClient  # noqa: E402
from tn_schemematch.systems.budget import CreditExhausted, UsageMeter  # noqa: E402
from tn_schemematch.web import create_app  # noqa: E402


@pytest.fixture
def guided_http(kb, spec, tmp_path):
    return create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "vault").test_client()


def says(text):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


def answer_by_buttons(http, chat_id, question, profile):
    """Answer one guided question the way the page does: a button, a number, or skip."""
    attr = question["attr"]
    value = profile.get(attr)
    if value is None:
        return http.post(f"/api/chat/{chat_id}/message", json={"attr": attr, "skip": True})
    scale = question.get("scale") or 1
    shown = value / scale if scale != 1 else value
    return http.post(f"/api/chat/{chat_id}/message", json={"attr": attr, "value": shown})


def test_a_guided_chat_over_http_reaches_the_rule_engine_s_answer(guided_http, kb, personas):
    persona = personas["p001"]
    start = guided_http.post("/api/chat", json={"lang": "en"}).get_json()
    chat_id, turn = start["chat_id"], start["turn"]
    for _ in range(60):
        if turn["done"]:
            break
        turn = answer_by_buttons(guided_http, chat_id, turn["question"], persona.profile).get_json()
    assert turn["done"]
    got = {line["id"] for line in turn["result"]["eligible"]}
    assert got == set(persona.gold_eligible(kb))
    assert turn["spoken"] == turn["result"]["text"]


def test_tamil_is_the_default_language(guided_http):
    start = guided_http.post("/api/chat", json={}).get_json()
    assert start["lang"] == "ta"
    assert "வணக்கம்" in start["turn"]["say"]


def test_a_spoken_answer_is_read_without_a_model(guided_http):
    start = guided_http.post("/api/chat", json={"lang": "ta"}).get_json()
    chat_id, question = start["chat_id"], start["turn"]["question"]
    assert question["attr"] == "age"
    body = guided_http.post(f"/api/chat/{chat_id}/message",
                            json={"text": "அறுபத்தைந்து வயசு"}).get_json()
    assert body["understood"] is True
    ages = [row for row in body["profile"] if row["attr"] == "age"]
    assert ages and ages[0]["value"] == 65


def test_an_answer_to_an_old_question_is_refused(guided_http):
    start = guided_http.post("/api/chat", json={}).get_json()
    chat_id, attr = start["chat_id"], start["turn"]["question"]["attr"]
    guided_http.post(f"/api/chat/{chat_id}/message", json={"attr": attr, "value": 40})
    stale = guided_http.post(f"/api/chat/{chat_id}/message", json={"attr": attr, "value": 41})
    assert stale.status_code == 409


def test_guided_answers_are_saved_into_a_bound_profile(guided_http):
    pid = guided_http.post("/api/profiles", json={"name": "Selvi"}).get_json()["id"]
    start = guided_http.post("/api/chat", json={"profile_id": pid}).get_json()
    chat_id, attr = start["chat_id"], start["turn"]["question"]["attr"]
    guided_http.post(f"/api/chat/{chat_id}/message", json={"attr": attr, "value": 62})
    facts = {f["attr"]: f for f in guided_http.get(f"/api/profiles/{pid}").get_json()["facts"]}
    assert facts[attr]["value"] == 62
    assert facts[attr]["source"] == "form"


def test_the_result_can_be_heard_at_any_time(guided_http):
    chat_id = guided_http.post("/api/chat", json={}).get_json()["chat_id"]
    body = guided_http.get(f"/api/chat/{chat_id}/result?lang=en").get_json()
    assert body["lang"] == "en" and body["text"]


def test_agent_mode_cannot_be_chosen_without_a_model(guided_http):
    chat_id = guided_http.post("/api/chat", json={}).get_json()["chat_id"]
    response = guided_http.post(f"/api/chat/{chat_id}/mode", json={"mode": "agent"})
    assert response.status_code == 409


def test_with_a_model_the_chat_starts_as_a_free_conversation(kb, spec, tmp_path):
    client = ScriptedClient(turns=[says("Sollunga!")])
    http = create_app(kb=kb, spec=spec, client=client, vault_dir=tmp_path / "v").test_client()
    start = http.post("/api/chat", json={}).get_json()
    assert start["mode"] == "agent"
    assert client.conversations == [], "the greeting must not cost a model call"
    body = http.post(f"/api/chat/{start['chat_id']}/message", json={"text": "vanakkam"}).get_json()
    assert body["reply"] == "Sollunga!"


def test_a_person_can_choose_simple_questions_even_with_a_model(kb, spec, tmp_path):
    client = ScriptedClient(turns=[says("unused")])
    http = create_app(kb=kb, spec=spec, client=client, vault_dir=tmp_path / "v").test_client()
    start = http.post("/api/chat", json={"mode": "guided"}).get_json()
    assert start["mode"] == "guided" and start["turn"]["question"]
    switched = http.post(f"/api/chat/{start['chat_id']}/mode", json={"mode": "agent"}).get_json()
    assert switched["mode"] == "agent"


def test_running_out_of_credit_mid_chat_switches_to_guided(kb, spec, tmp_path):
    class Spent(ScriptedClient):
        def converse(self, *args, **kwargs):
            raise CreditExhausted("Your credit balance is too low")
    http = create_app(kb=kb, spec=spec, client=Spent(), vault_dir=tmp_path / "v").test_client()
    chat_id = http.post("/api/chat", json={}).get_json()["chat_id"]
    body = http.post(f"/api/chat/{chat_id}/message", json={"text": "naan vivasayi"}).get_json()
    assert body["switched"] is True
    assert body["mode"] == "guided" and body["reason"] == "no_credit"
    assert body["question"]["attr"]
    # And the conversation simply continues.
    attr = body["question"]["attr"]
    nxt = http.post(f"/api/chat/{chat_id}/message", json={"attr": attr, "skip": True})
    assert nxt.status_code == 200


def test_a_spent_daily_budget_starts_the_chat_guided(kb, spec, tmp_path):
    meter = UsageMeter(daily_budget_usd=0.0)

    class Metered(ScriptedClient):
        pass

    client = Metered()
    client.meter = meter
    http = create_app(kb=kb, spec=spec, client=client, vault_dir=tmp_path / "v").test_client()
    start = http.post("/api/chat", json={}).get_json()
    assert start["mode"] == "guided" and start["reason"] == "daily_budget"


def test_every_question_the_page_can_show_has_words(guided_http, spec):
    book = default_questions()
    for attr in spec.elicitable_names():
        assert book.ask(attr, "ta") and book.ask(attr, "en")


def test_usage_is_reported_on_the_stats_endpoint(kb, spec, tmp_path):
    client = ScriptedClient()
    client.meter = UsageMeter(daily_budget_usd=1.0)
    http = create_app(kb=kb, spec=spec, client=client, vault_dir=tmp_path / "v").test_client()
    usage = http.get("/api/stats").get_json()["usage"]
    assert usage["daily_budget_usd"] == 1.0
