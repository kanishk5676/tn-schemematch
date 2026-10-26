"""Helper mode over HTTP: the PIN, who may see which profile, and the helper's list."""

import pytest

pytest.importorskip("flask")

from tn_schemematch.web import create_app  # noqa: E402

PIN = "2468"


@pytest.fixture
def app(kb, spec, tmp_path):
    return create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "vault",
                      helper_pin=PIN, secret_key="test")


def make_person(http, name="Selvi"):
    return http.post("/api/profiles", json={"name": name}).get_json()["id"]


def test_a_citizen_sees_only_the_profiles_their_browser_made(app):
    mine, stranger = app.test_client(), app.test_client()
    pid = make_person(mine)
    assert mine.get(f"/api/profiles/{pid}").status_code == 200
    assert [p["id"] for p in mine.get("/api/profiles").get_json()["profiles"]] == [pid]
    assert stranger.get(f"/api/profiles/{pid}").status_code == 401
    assert stranger.get("/api/profiles").get_json()["profiles"] == []
    assert stranger.get(f"/api/profiles/{pid}/checklist").status_code == 401
    assert stranger.post("/api/chat", json={"profile_id": pid}).status_code == 401


def test_the_helper_pin_unlocks_everyone_and_logout_locks_again(app):
    citizen, helper = app.test_client(), app.test_client()
    pid = make_person(citizen)
    assert helper.get("/api/helper/overview").status_code == 401
    assert helper.post("/api/helper/login", json={"pin": "0000"}).status_code == 401
    assert helper.post("/api/helper/login", json={"pin": PIN}).status_code == 200
    assert helper.get(f"/api/profiles/{pid}").status_code == 200
    people = helper.get("/api/helper/overview").get_json()["people"]
    assert [p["id"] for p in people] == [pid]
    helper.post("/api/helper/logout")
    assert helper.get(f"/api/profiles/{pid}").status_code == 401


def test_wrong_pins_lock_the_address_out(app):
    http = app.test_client()
    for _ in range(5):
        assert http.post("/api/helper/login", json={"pin": "1"}).status_code == 401
    assert http.post("/api/helper/login", json={"pin": PIN}).status_code == 429


def test_without_a_pin_everyone_is_a_helper(kb, spec, tmp_path):
    app = create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "vault")
    one, two = app.test_client(), app.test_client()
    pid = make_person(one)
    assert two.get(f"/api/profiles/{pid}").status_code == 200
    assert two.get("/api/helper/me").get_json() == {"pin_required": False, "helper": True,
                                                    "own": []}


def test_a_saved_chat_belongs_to_the_browser_that_saved_it(app):
    http = app.test_client()
    chat_id = http.post("/api/chat", json={}).get_json()["chat_id"]
    saved = http.post(f"/api/session/{chat_id}/save", json={"name": "Murugan"}).get_json()
    assert http.get(f"/api/profiles/{saved['profile_id']}").status_code == 200


def test_applications_are_recorded_and_shown_on_the_list(app):
    helper = app.test_client()
    helper.post("/api/helper/login", json={"pin": PIN})
    pid = make_person(helper)
    for attr, value in {"age": 62, "gender": "female", "marital_status": "widowed",
                        "state": "TN", "is_destitute": True, "fixed_assets_value": 10000,
                        "receives_other_pension": False, "is_bpl": True}.items():
        helper.post(f"/api/profiles/{pid}/facts", json={"attr": attr, "value": value})
    row = helper.post(f"/api/profiles/{pid}/applications", json={
        "scheme_id": "tn-old-age-pension", "status": "applied", "reference": "SSS/42",
        "applied_on": "2026-01-05"}).get_json()
    assert row["status"] == "applied"
    bad = helper.post(f"/api/profiles/{pid}/applications",
                      json={"scheme_id": "tn-old-age-pension", "status": "lost"})
    assert bad.status_code == 400
    person = helper.get("/api/helper/overview?lang=en").get_json()["people"][0]
    assert person["follow_up"] and person["follow_up"][0]["reference"] == "SSS/42"
    page = helper.get(f"/profile/{pid}/pack/tn-old-age-pension").get_data(as_text=True)
    assert "SSS/42" in page


def test_the_helper_page_renders(app):
    assert app.test_client().get("/helper").status_code == 200
