"""Saved profiles: provenance, the vocabulary's invariants, and life-event diffs.

Every test gets its own vault under ``tmp_path`` — nothing here touches ``data/vault``.
"""

import pytest

pytest.importorskip("flask")

from tn_schemematch.vault import Vault, VaultError, eligibility  # noqa: E402
from tn_schemematch.web import create_app  # noqa: E402


@pytest.fixture
def vault(tmp_path, spec):
    v = Vault(tmp_path / "vault", spec)
    yield v
    v.close()


@pytest.fixture
def http(kb, spec, tmp_path):
    return create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "vault").test_client()


def saved(vault, persona):
    """A profile holding every elicitable fact of a benchmark persona."""
    pid = vault.create_profile(persona.id)["id"]
    vault.record_many(pid, [
        (attr, value, "form", "")
        for attr, value in persona.profile.items()
        if attr in vault.spec.elicitable_names() and value is not None
    ])
    return pid


# ------------------------------------------------------------------- the store


def test_facts_are_canonicalized_on_the_way_in(vault):
    pid = vault.create_profile("Lakshmi")["id"]
    assert vault.record(pid, "gender", "pen", source="query") == "female"
    assert vault.record(pid, "land_owned_acres", "80 cent", source="query") == 0.8
    profile, sources = vault.profile(pid)
    assert profile["gender"] == "female"
    assert sources["gender"] == "query"


def test_derived_attributes_are_recomputed_never_stored(vault):
    pid = vault.create_profile("Lakshmi")["id"]
    with pytest.raises(VaultError, match="derived"):
        vault.record(pid, "is_widow", True, source="form")
    vault.record(pid, "marital_status", "widowed", source="form")
    profile, sources = vault.profile(pid)
    assert profile["is_widow"] is True
    assert sources["is_widow"] == "derived"


def test_unknown_and_unparseable_values_are_refused(vault):
    pid = vault.create_profile("Lakshmi")["id"]
    with pytest.raises(VaultError):
        vault.record(pid, "favourite_colour", "blue", source="form")
    with pytest.raises(VaultError):
        vault.record(pid, "gender", "purple", source="form")


def test_a_bad_fact_saves_nothing(vault):
    pid = vault.create_profile("Lakshmi")["id"]
    with pytest.raises(VaultError):
        vault.record_many(pid, [("age", 45, "form", ""), ("gender", "purple", "form", "")])
    assert vault.profile(pid)[0] == {}


def test_latest_fact_wins_and_history_keeps_every_one(vault):
    pid = vault.create_profile("Lakshmi")["id"]
    vault.record(pid, "annual_family_income", 36000, source="query", evidence="month-ku 3000")
    vault.record(pid, "annual_family_income", 72000, source="document")
    assert vault.profile(pid)[0]["annual_family_income"] == 72000.0

    history = vault.history(pid, "annual_family_income")
    assert [h["value"] for h in history] == [36000.0, 72000.0]
    assert history[0]["evidence"] == "month-ku 3000"

    row = next(r for r in vault.fact_rows(pid) if r["attr"] == "annual_family_income")
    assert row["source"] == "document"
    assert row["display"] == "72,000 rupees a year"


def test_none_retracts_a_fact(vault):
    pid = vault.create_profile("Lakshmi")["id"]
    vault.record(pid, "age", 45, source="form")
    vault.record(pid, "age", None, source="form")
    assert "age" not in vault.profile(pid)[0]
    assert len(vault.history(pid, "age")) == 2


def test_households_group_people(vault):
    mother = vault.create_profile("Lakshmi")
    daughter = vault.create_profile("Priya", household=mother["id"], relation="daughter")
    assert daughter["household"] == mother["household"]
    names = {p["name"] for p in vault.profiles(mother["household"])}
    assert names == {"Lakshmi", "Priya"}


def test_delete_removes_facts_and_files(vault):
    pid = vault.create_profile("Lakshmi")["id"]
    vault.record(pid, "age", 45, source="form")
    document = vault.add_document(pid, doc_type="aadhaar", filename="a.jpg",
                                  data=b"\xff\xd8", media_type="image/jpeg", extension="jpg")
    vault.delete_profile(pid)
    with pytest.raises(KeyError):
        vault.get_profile(pid)
    assert not (vault.files_dir / pid).exists()
    assert not __import__("pathlib").Path(document["stored_path"]).exists()


def test_unknown_profile_is_a_key_error(vault):
    with pytest.raises(KeyError):
        vault.profile("nobody")
    with pytest.raises(KeyError):
        vault.record("nobody", "age", 45, source="form")


# ------------------------------------------------------------- life events


def test_first_check_reports_no_change(vault, kb, personas):
    pid = saved(vault, personas["p001"])
    result = eligibility(kb.active(), vault, pid)
    assert result["changes"] == {"first_check": True, "gained": [], "lost": []}
    assert {c["id"] for c in result["eligible"]} == set(personas["p001"].gold_eligible(kb))


def test_a_life_event_reports_what_was_lost_and_regained(vault, kb, personas):
    """Holding a constitutional post is one of PM-KISAN's exclusions."""
    persona = personas["p001"]
    assert "pm-kisan" in persona.gold_eligible(kb)
    pid = saved(vault, persona)
    eligibility(kb.active(), vault, pid)  # baseline

    vault.record(pid, "held_constitutional_post", True, source="form")
    after = eligibility(kb.active(), vault, pid)
    assert "pm-kisan" in {c["id"] for c in after["changes"]["lost"]}

    vault.record(pid, "held_constitutional_post", False, source="form")
    again = eligibility(kb.active(), vault, pid)
    assert "pm-kisan" in {c["id"] for c in again["changes"]["gained"]}


def test_a_check_without_remember_keeps_the_baseline(vault, kb, personas):
    pid = saved(vault, personas["p001"])
    eligibility(kb.active(), vault, pid)
    vault.record(pid, "held_constitutional_post", True, source="form")
    eligibility(kb.active(), vault, pid, remember=False)
    assert eligibility(kb.active(), vault, pid)["changes"]["lost"]


# -------------------------------------------------------------------- HTTP


def test_profile_lifecycle_over_http(http):
    created = http.post("/api/profiles", json={"name": "Lakshmi"})
    assert created.status_code == 201
    pid = created.get_json()["id"]

    body = http.post(f"/api/profiles/{pid}/facts",
                     json={"attr": "gender", "text": "pen"}).get_json()
    assert body["fact"]["value"] == "female"
    assert body["fact"]["source"] == "aliases"
    assert body["eligibility"]["changes"]["first_check"] is True

    detail = http.get(f"/api/profiles/{pid}").get_json()
    assert detail["profile"]["name"] == "Lakshmi"
    assert any(f["attr"] == "gender" for f in detail["facts"])

    assert http.delete(f"/api/profiles/{pid}").status_code == 200
    assert http.get(f"/api/profiles/{pid}").status_code == 404


def test_profile_http_errors(http):
    assert http.post("/api/profiles", json={"name": "  "}).status_code == 400
    assert http.get("/api/profiles/nobody/eligibility").status_code == 404
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    derived = http.post(f"/api/profiles/{pid}/facts", json={"attr": "is_widow", "value": True})
    assert derived.status_code == 400
    assert derived.get_json()["error"]["code"] == "derived_attribute"
    unread = http.post(f"/api/profiles/{pid}/facts", json={"attr": "age", "text": "!!!"})
    assert unread.get_json()["error"]["code"] == "unparsed"


# ------------------------------------------------- interview <-> saved profile


def test_a_saved_profile_is_never_asked_again(http):
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    http.post(f"/api/profiles/{pid}/facts", json={"attr": "age", "value": 45})
    http.post(f"/api/profiles/{pid}/facts", json={"attr": "gender", "value": "female"})

    body = http.post("/api/session", json={"use_ai": False, "profile_id": pid,
                                           "max_questions": 40}).get_json()
    assert body["profile_id"] == pid
    sid, asked = body["session_id"], []
    while not body["done"]:
        asked.append(body["question"]["attr"])
        body = http.post(f"/api/session/{sid}/skip",
                         json={"attr": body["question"]["attr"]}).get_json()
    assert asked and not {"age", "gender"} & set(asked)


def test_unknown_profile_cannot_seed_a_session(http):
    response = http.post("/api/session", json={"use_ai": False, "profile_id": "nobody"})
    assert response.status_code == 404


def test_saving_a_session_creates_a_profile_once(http):
    start = http.post("/api/session", json={"use_ai": False}).get_json()
    sid, question = start["session_id"], start["question"]
    value = (True if question["type"] == "bool" else
             question["options"][0]["value"] if question["type"] == "enum" else question["min"])
    http.post(f"/api/session/{sid}/answer", json={"attr": question["attr"], "value": value})

    first = http.post(f"/api/session/{sid}/save", json={"name": "Murugan"}).get_json()
    assert first["saved"] == 1
    pid = first["profile_id"]
    facts = http.get(f"/api/profiles/{pid}").get_json()["facts"]
    assert any(f["attr"] == question["attr"] and f["source"] == "form" for f in facts)

    again = http.post(f"/api/session/{sid}/save", json={}).get_json()
    assert again["profile_id"] == pid and again["saved"] == 0
