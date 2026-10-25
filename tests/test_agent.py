"""The assistant, driven by a scripted model.

These test the loop and the tools, not a model's judgement: the script says which tool
to call, and the assertions check what the code did with that call — what reached the
profile, what went back into the history, and what the guard reported.
"""

import json

import pytest

pytest.importorskip("flask")

from tn_schemematch.agent import AgentUnavailable, run_turn, scheme_mentions  # noqa: E402
from tn_schemematch.agent_tools import AgentContext, build_tools  # noqa: E402
from tn_schemematch.documents import default_documents  # noqa: E402
from tn_schemematch.interview import Interview  # noqa: E402
from tn_schemematch.systems.base import ScriptedClient  # noqa: E402
from tn_schemematch.web import create_app  # noqa: E402


def call(name, tool_id="t1", **arguments):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": arguments}


def says(text):
    return {"stop_reason": "end_turn", "content": [{"type": "text", "text": text}]}


def uses(*calls, text=None):
    content = ([{"type": "text", "text": text}] if text else []) + list(calls)
    return {"stop_reason": "tool_use", "content": content}


@pytest.fixture
def agent(kb, spec):
    """An agent context over a fresh interview, and a factory for seeding it."""
    interview = Interview(kb=kb, spec=spec)

    def make(seed=None):
        state = interview.start("", max_questions=40, use_ai=False, seed_profile=seed)
        return AgentContext(interview=interview, state=state, documents=default_documents())
    return make


# ----------------------------------------------------------------- the loop


def test_tools_run_and_their_results_go_back_in_order(agent):
    ctx = agent()
    client = ScriptedClient(turns=[
        uses(call("record_facts", facts=[
            {"attr": "occupation", "value": "farmer", "evidence": "naan vivasayi"},
            {"attr": "land_owned_acres", "value": "2 acres", "evidence": "rendu ekkar"}]),
            text="Noting that."),
        uses(call("next_best_question", tool_id="t2")),
        says("Ungalukku vayasu enna?"),
    ])
    history = []
    turn = run_turn(client, ctx, history, "naan vivasayi, rendu ekkar nilam irukku")

    assert turn["reply"] == "Ungalukku vayasu enna?"
    assert [s["tool"] for s in turn["steps"]] == ["record_facts", "next_best_question"]
    assert ctx.state.profile["occupation"] == "farmer"
    assert ctx.state.profile["land_owned_acres"] == 2.0
    assert ctx.state.sources["occupation"] == "chat"

    assert [m["role"] for m in history] == [
        "user", "assistant", "user", "assistant", "user", "assistant"]
    first_result = history[2]["content"][0]
    assert first_result["tool_use_id"] == "t1"
    assert json.loads(first_result["content"])["accepted"][0]["attr"] == "occupation"
    # The model saw the result of step one before deciding step two.
    assert any(block.get("tool_use_id") == "t1"
               for block in client.conversations[1]["messages"][2]["content"])


def test_rejected_values_come_back_with_what_is_allowed(agent):
    ctx = agent()
    client = ScriptedClient(turns=[
        uses(call("record_facts", facts=[
            {"attr": "gender", "value": "purple", "evidence": "?"},
            {"attr": "is_widow", "value": "yes", "evidence": "?"}])),
        says("Sorry, could you say that again?"),
    ])
    history = []
    run_turn(client, ctx, history, "...")
    result = json.loads(history[2]["content"][0]["content"])
    reasons = {r["attr"]: r for r in result["rejected"]}
    assert "female" in reasons["gender"]["allowed"]
    assert "derived" in reasons["is_widow"]["reason"]
    assert "is_widow" not in ctx.state.profile or ctx.state.sources["is_widow"] == "derived"


def test_a_bad_tool_call_is_an_error_result_not_a_crash(agent):
    ctx = agent()
    client = ScriptedClient(turns=[
        uses(call("delete_everything")),
        uses(call("explain_scheme", tool_id="t2", scheme_id="no-such-scheme")),
        says("Let me try something else."),
    ])
    history = []
    turn = run_turn(client, ctx, history, "...")
    assert [s["ok"] for s in turn["steps"]] == [False, False]
    assert history[2]["content"][0]["is_error"] is True
    assert turn["reply"] == "Let me try something else."


def test_steps_per_message_are_capped(agent):
    ctx = agent()
    client = ScriptedClient(turns=[uses(call("get_profile", tool_id=f"t{i}"))
                                   for i in range(20)])
    turn = run_turn(client, ctx, [], "...", max_steps=4)
    assert turn["capped"] is True
    assert len(turn["steps"]) == 4
    assert turn["reply"]


def test_a_client_without_tools_is_refused(agent):
    with pytest.raises(AgentUnavailable):
        run_turn(object(), agent(), [], "hello")


# ---------------------------------------------------------------- the tools


def test_check_eligibility_reports_what_changed(agent, personas):
    persona = personas["p001"]
    ctx = agent(seed=persona.profile)
    client = ScriptedClient(turns=[
        uses(call("check_eligibility")),
        uses(call("record_facts", tool_id="t2", facts=[
            {"attr": "held_constitutional_post", "value": "yes", "evidence": "I am an MLA"}])),
        uses(call("check_eligibility", tool_id="t3")),
        says("ok"),
    ])
    history = []
    run_turn(client, ctx, history, "...")
    first = json.loads(history[2]["content"][0]["content"])
    second = json.loads(history[6]["content"][0]["content"])
    assert "pm-kisan" in {s["id"] for s in first["eligible"]}
    assert "changes_since_last_check" not in first
    assert any("PM-KISAN" in name for name in second["changes_since_last_check"]["lost"])


def test_explain_scheme_gives_the_deciding_clauses(agent, personas):
    ctx = agent(seed=personas["p001"].profile)
    client = ScriptedClient(turns=[
        uses(call("explain_scheme", scheme_id="pm-kisan"),
             call("explain_scheme", tool_id="t2", scheme_id="kmut")),
        says("ok"),
    ])
    history = []
    run_turn(client, ctx, history, "...")
    kisan, kmut = (json.loads(r["content"]) for r in history[2]["content"])
    assert kisan["verdict"] == "eligible" and kisan["conditions_met"]
    assert kisan["documents"] and kisan["apply_url"]
    assert kmut["verdict"] == "ineligible"
    assert any("female" in line for line in kmut["conditions_not_met"])


def test_show_puts_components_on_screen(agent, personas):
    ctx = agent(seed=personas["p001"].profile)
    client = ScriptedClient(turns=[
        uses(call("show", component="scheme_card", scheme_id="pm-kisan", doc_type="",
                  query=""),
             call("show", tool_id="t2", component="upload_document", scheme_id="",
                  doc_type="land_record", query=""),
             call("show", tool_id="t3", component="checklist", scheme_id="", doc_type="",
                  query="")),
        says("Here you go."),
    ])
    turn = run_turn(client, ctx, [], "...")
    kinds = [action["type"] for action in turn["ui"]]
    assert kinds == ["scheme", "upload", "checklist"]
    assert turn["ui"][0]["scheme"]["trace"]["verdict"] == "eligible"
    assert turn["ui"][1]["needs_profile"] is True  # nothing saved yet


def test_tool_schemas_are_strict_and_closed(agent, spec):
    for tool in build_tools(agent()):
        schema = tool["input_schema"]
        assert tool["strict"] is True
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
    record = next(t for t in build_tools(agent()) if t["name"] == "record_facts")
    attrs = record["input_schema"]["properties"]["facts"]["items"]["properties"]["attr"]["enum"]
    assert set(attrs) == set(spec.elicitable_names())


# ------------------------------------------------------------------ the guard


def test_the_guard_flags_a_scheme_the_rules_rule_out(agent, personas):
    """p001 is a man; the model claims a women-only scheme anyway."""
    ctx = agent(seed=personas["p001"].profile)
    client = ScriptedClient(turns=[says(
        "You qualify for PM-KISAN and the Kalaignar Magalir Urimai Thogai!")])
    turn = run_turn(client, ctx, [], "what can I get?")
    verdicts = {m["id"]: m for m in turn["mentions"]}
    assert verdicts["pm-kisan"]["confirmed"] is True
    assert verdicts["kmut"]["verdict"] == "ineligible"
    assert verdicts["kmut"]["confirmed"] is False


def test_the_guard_matches_whole_names_only(kb):
    assert scheme_mentions("Be happy, it is a big pmsby day", kb.active(), {}) == [
        {"id": "pmsby", "name": kb["pmsby"].name, "verdict": "undetermined",
         "confirmed": False}]


# --------------------------------------------------------------------- HTTP


@pytest.fixture
def scripted_app(kb, spec, tmp_path):
    def make(turns):
        client = ScriptedClient(turns=list(turns))
        app = create_app(kb=kb, spec=spec, client=client, vault_dir=tmp_path / "vault")
        return app.test_client(), client
    return make


def test_chat_needs_a_model_that_can_use_tools(kb, spec, tmp_path):
    rules_only = create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "v")
    assert rules_only.test_client().post("/api/chat", json={}).status_code == 503


def test_chat_over_http_writes_through_to_a_saved_profile(scripted_app):
    http, client = scripted_app([
        uses(call("get_profile")),
        uses(call("record_facts", tool_id="t2", facts=[
            {"attr": "marital_status", "value": "widowed", "evidence": "naan widow"}])),
        says("Romba varutham. Ungalukku vayasu enna?"),
    ])
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    http.post(f"/api/profiles/{pid}/facts", json={"attr": "age", "value": 55})

    chat = http.post("/api/chat", json={"profile_id": pid})
    assert chat.status_code == 201
    chat_id = chat.get_json()["chat_id"]
    body = http.post(f"/api/chat/{chat_id}/message", json={"text": "naan widow"}).get_json()

    assert body["reply"].startswith("Romba varutham")
    assert body["profile_name"] == "Lakshmi"
    known = json.loads(client.conversations[1]["messages"][2]["content"][0]["content"])
    assert any(f["attr"] == "age" for f in known["facts"])  # seeded from the vault

    facts = {f["attr"]: f for f in http.get(f"/api/profiles/{pid}").get_json()["facts"]}
    assert facts["marital_status"]["source"] == "chat"
    assert facts["marital_status"]["evidence"] == "naan widow"
    assert facts["is_widow"]["value"] is True  # derived on read

    reloaded = http.get(f"/api/chat/{chat_id}").get_json()
    assert [t["role"] for t in reloaded["transcript"]] == ["user", "assistant"]


def test_chat_errors(scripted_app):
    http, _ = scripted_app([])
    assert http.post("/api/chat", json={"profile_id": "nobody"}).status_code == 404
    assert http.post("/api/chat/nope/message", json={"text": "hi"}).status_code == 404
    chat_id = http.post("/api/chat", json={}).get_json()["chat_id"]
    assert http.post(f"/api/chat/{chat_id}/message", json={"text": "  "}).status_code == 400


def test_a_failing_model_is_a_503_not_a_500(kb, spec, tmp_path):
    class Broken(ScriptedClient):
        def converse(self, *args, **kwargs):
            raise RuntimeError("network down")
    http = create_app(kb=kb, spec=spec, client=Broken(),
                      vault_dir=tmp_path / "vault").test_client()
    chat_id = http.post("/api/chat", json={}).get_json()["chat_id"]
    response = http.post(f"/api/chat/{chat_id}/message", json={"text": "hi"})
    assert response.status_code == 503
    assert response.get_json()["error"]["code"] == "agent_failed"


def test_a_chat_can_be_saved_like_an_interview(scripted_app):
    http, _ = scripted_app([
        uses(call("record_facts", facts=[
            {"attr": "occupation", "value": "fisher", "evidence": "meen pidippen"}])),
        says("Nandri!"),
    ])
    chat_id = http.post("/api/chat", json={}).get_json()["chat_id"]
    http.post(f"/api/chat/{chat_id}/message", json={"text": "naan meen pidippen"})
    saved = http.post(f"/api/session/{chat_id}/save", json={"name": "Murugan"}).get_json()
    facts = http.get(f"/api/profiles/{saved['profile_id']}").get_json()["facts"]
    assert any(f["attr"] == "occupation" and f["source"] == "chat" for f in facts)
    assert http.get(f"/api/chat/{chat_id}").get_json()["profile_id"] == saved["profile_id"]
