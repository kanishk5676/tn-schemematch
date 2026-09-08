"""The HTTP layer, driven end to end with no key and no network.

The decisive test here is `test_full_interview_over_http_reaches_the_gold_set`: it drives
the real routes from a persona's profile and asserts the answer equals the one the rule
engine computes directly. That is what proves the web layer did not quietly change the
system's behaviour on the way to the browser.
"""

import json

import pytest

pytest.importorskip("flask")

from tn_schemematch.systems.base import ScriptedClient  # noqa: E402
from tn_schemematch.web import create_app  # noqa: E402


@pytest.fixture
def client(kb, spec):
    """Rules-only: no model at all, the same posture as the offline demo path."""
    return create_app(kb=kb, spec=spec, client=None).test_client()


@pytest.fixture
def scripted():
    """A client whose model returns a fixed code-mixed extraction."""
    return ScriptedClient(default=json.dumps(
        {"occupation": "விவசாயி", "land_owned_acres": "2 ekkar", "vibe": "rural"}))


# ---------------------------------------------------------------- starting up


def test_start_session_returns_a_question_and_a_board(client):
    body = client.post("/api/session", json={"query": "naan vivasayi", "use_ai": False}).get_json()
    assert body["session_id"]
    assert body["question"]["attr"]
    assert sum(body["board"]["counts"].values()) == body["board"]["total"]
    assert body["has_model"] is False


def test_start_without_ai_makes_no_model_call(kb, spec, scripted):
    """The offline demo path must genuinely not touch the client."""
    app = create_app(kb=kb, spec=spec, client=scripted)
    body = app.test_client().post(
        "/api/session", json={"query": "naan vivasayi", "use_ai": False}).get_json()
    assert scripted.calls == []
    assert body["extraction"]["used_ai"] is False
    assert body["question"] is not None


def test_extraction_surfaces_both_halves(kb, spec, scripted):
    """The raw model output and the normalized profile both reach the browser."""
    app = create_app(kb=kb, spec=spec, client=scripted)
    body = app.test_client().post(
        "/api/session", json={"query": "naan vivasayi rendu ekkar"}).get_json()
    extraction = body["extraction"]
    assert extraction["used_ai"] is True
    assert extraction["raw"]["occupation"] == "விவசாயி"
    values = {row["attr"]: row["value"] for row in extraction["normalized"]}
    assert values["occupation"] == "farmer"
    assert values["land_owned_acres"] == 2.0
    assert any("vibe" in r for r in extraction["rejected"])
    assert body["has_model"] is True


def test_extraction_failure_still_yields_a_usable_session(kb, spec):
    app = create_app(kb=kb, spec=spec, client=ScriptedClient(default="sorry, no"))
    body = app.test_client().post("/api/session", json={"query": "naan vivasayi"}).get_json()
    assert body["extraction"]["error"]
    assert body["question"] is not None


# ------------------------------------------------------------------- the loop


def test_answer_advances_and_updates_the_board(client):
    start = client.post("/api/session", json={"query": "", "use_ai": False}).get_json()
    sid, attr = start["session_id"], start["question"]["attr"]
    body = client.post(f"/api/session/{sid}/answer", json={"attr": attr, "value": "TN"}).get_json()
    assert body["accepted"] and body["source"] == "form"
    assert body["question"]["attr"] != attr


def test_skip_does_not_reask(client):
    start = client.post("/api/session", json={"query": "", "use_ai": False}).get_json()
    sid = start["session_id"]
    seen, attr = [], start["question"]["attr"]
    for _ in range(4):
        seen.append(attr)
        body = client.post(f"/api/session/{sid}/skip", json={"attr": attr}).get_json()
        attr = body["question"]["attr"]
    assert len(set(seen)) == len(seen)
    assert attr not in seen


def test_full_interview_over_http_reaches_the_gold_set(client, kb, personas):
    """The web layer and the library must agree on the answer."""
    persona = personas["p001"]
    start = client.post("/api/session", json={
        "query": persona.queries["code_mixed"], "use_ai": False, "max_questions": 40,
    }).get_json()
    sid, body = start["session_id"], start

    while not body["done"]:
        attr = body["question"]["attr"]
        value = persona.profile.get(attr)
        route, payload = ((f"/api/session/{sid}/answer", {"attr": attr, "value": value})
                          if value is not None
                          else (f"/api/session/{sid}/skip", {"attr": attr}))
        body = client.post(route, json=payload).get_json()

    result = client.get(f"/api/session/{sid}/result").get_json()
    assert {card["id"] for card in result["eligible"]} == set(persona.gold_eligible(kb))


def test_persona_replay_finishes_in_one_request(client, kb, personas):
    """The zero-typing stage path."""
    body = client.post("/api/session", json={"persona": "p001"}).get_json()
    assert body["done"] is True
    result = client.get(f"/api/session/{body['session_id']}/result").get_json()
    assert {c["id"] for c in result["eligible"]} == set(personas["p001"].gold_eligible(kb))


def test_result_carries_traces_and_near_misses(client, personas):
    body = client.post("/api/session", json={"persona": "p001"}).get_json()
    result = client.get(f"/api/session/{body['session_id']}/result").get_json()
    json.dumps(result)
    for card in result["eligible"]:
        assert card["trace"]["verdict"] == "eligible"
        assert card["trace"]["children"]
    for miss in result["near_misses"]:
        assert miss["missing"]["human"]


# -------------------------------------------------------------- error shapes


def test_unknown_session_is_404(client):
    body = client.get("/api/session/nope/result")
    assert body.status_code == 404
    assert body.get_json()["error"]["code"] == "no_such_session"


def test_unknown_attribute_is_400(client):
    sid = client.post("/api/session", json={"use_ai": False}).get_json()["session_id"]
    response = client.post(f"/api/session/{sid}/answer",
                           json={"attr": "favourite_colour", "value": "blue"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "bad_attribute"


def test_derived_attribute_is_refused(client):
    """A client must not be able to set an attribute the vocabulary computes."""
    sid = client.post("/api/session", json={"use_ai": False}).get_json()["session_id"]
    response = client.post(f"/api/session/{sid}/answer",
                           json={"attr": "is_widow", "value": True})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "derived_attribute"


def test_unparseable_free_text_does_not_consume_the_question(client):
    """A rejected answer must leave the attribute answerable rather than burning it.

    The frontend keeps the question on screen; the server's half of that contract is
    simply not to record it as asked.
    """
    sid = client.post("/api/session", json={"use_ai": False}).get_json()["session_id"]
    first = client.post(f"/api/session/{sid}/answer",
                        json={"attr": "age", "text": "!!!"}).get_json()
    assert not first["accepted"]
    second = client.post(f"/api/session/{sid}/answer",
                         json={"attr": "age", "value": 45}).get_json()
    assert second["accepted"] and second["value"] == 45.0


def test_model_only_routes_refuse_without_a_model(client):
    sid = client.post("/api/session", json={"persona": "p001"}).get_json()["session_id"]
    assert client.get(f"/api/session/{sid}/explain/pm-kisan").status_code == 503
    assert client.post(f"/api/session/{sid}/compare").status_code == 503


def test_unknown_persona_is_404(client):
    assert client.post("/api/session", json={"persona": "nobody"}).status_code == 404


# ---------------------------------------------------------------- catalogue


def test_schemes_endpoint_lists_every_active_scheme(client, kb):
    body = client.get("/api/schemes").get_json()
    assert body["total"] == len(kb.active())
    assert body["facets"]["sectors"]


def test_schemes_endpoint_filters_by_level(client, kb):
    body = client.get("/api/schemes?level=state").get_json()
    expected = sum(1 for s in kb.active() if s.level == "state")
    assert len(body["schemes"]) == expected


def test_scheme_detail_has_a_rule_tree_without_a_session(client):
    body = client.get("/api/schemes/pm-kisan").get_json()
    assert body["verdict"] == "undetermined"
    assert body["rule_tree"]["children"]
    assert body["eligibility_prose"]


def test_stats_endpoint_returns_coverage(client):
    body = client.get("/api/stats").get_json()
    assert body["kb"]["n_schemes"] > 0
    assert body["spec"]["n_elicitable"] > 0
    assert isinstance(body["runs"], list)


def test_pages_render(client):
    for path in ("/", "/schemes", "/dashboard"):
        assert client.get(path).status_code == 200


# ----------------------------------------------------------- model-backed API


def test_explain_is_grounded_only_in_satisfied_clauses(kb, spec):
    """The anti-hallucination contract, tested on the prompt itself.

    The model is handed the satisfied clauses and nothing else. If a condition the person
    does NOT meet ever reaches the prompt, the explanation could assert it — so assert its
    absence rather than trusting the wording of the system prompt.
    """
    scripted = ScriptedClient(default="You qualify because you own farmland.")
    app = create_app(kb=kb, spec=spec, client=scripted)
    http = app.test_client()
    sid = http.post("/api/session", json={"persona": "p001"}).get_json()["session_id"]

    body = http.get(f"/api/session/{sid}/explain/pm-kisan").get_json()
    assert body["text"] == "You qualify because you own farmland."

    _, prompt = scripted.calls[-1]
    assert "CONDITIONS THIS PERSON SATISFIES" in prompt
    # p001 is male; a female-only clause must never appear in the evidence list.
    assert "must be female" not in prompt


def test_explain_is_cached_per_scheme_and_language(kb, spec):
    scripted = ScriptedClient(default="ok")
    http = create_app(kb=kb, spec=spec, client=scripted).test_client()
    sid = http.post("/api/session", json={"persona": "p001"}).get_json()["session_id"]
    http.get(f"/api/session/{sid}/explain/pm-kisan")
    http.get(f"/api/session/{sid}/explain/pm-kisan")
    assert len(scripted.calls) == 1


def test_compare_separates_false_positives_from_hallucinations(kb, spec):
    scripted = ScriptedClient(default=json.dumps(
        {"eligible_schemes": ["pm-kisan", "kmut", "free-money-yojana"]}))
    http = create_app(kb=kb, spec=spec, client=scripted).test_client()
    sid = http.post("/api/session", json={"persona": "p001"}).get_json()["session_id"]

    body = http.post(f"/api/session/{sid}/compare").get_json()
    assert "free-money-yojana" in body["hallucinated"]
    # p001 is male; the women-only scheme is a false positive the rules catch.
    assert any(c["id"] == "kmut" for c in body["false_positives"])
