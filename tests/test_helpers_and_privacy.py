"""Helpers, partners and privacy: camps, reports, the partner API, consent, audit, sources."""

import io

import pytest

pytest.importorskip("flask")

from tn_schemematch.documents import prepare_upload, DocumentError  # noqa: E402
from tn_schemematch.helpers import anonymous_report, check_facts  # noqa: E402
from tn_schemematch.partners import RateLimiter, create_key  # noqa: E402
from tn_schemematch.vault import Vault  # noqa: E402
from tn_schemematch.watch import fingerprint, page_text, save_baseline, load_baseline, watch  # noqa: E402
from tn_schemematch.web import create_app  # noqa: E402

FARMER = {"state": "TN", "district": "Thanjavur", "age": "45", "gender": "male",
          "marital_status": "married", "occupation": "farmer", "annual_family_income": "90000",
          "ration_card_type": "phh_rice", "land_owned_acres": "2", "disability_percent": "0",
          "social_category": "MBC", "residence_type": "rural", "house_ownership": "owns_kutcha",
          "has_aadhaar": True, "has_bank_account": True, "is_bpl": True,
          "receives_other_pension": False}


def make(kb, spec, tmp_path, **kwargs):
    app = create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "vault", **kwargs)
    return app, app.test_client()


# --------------------------------------------------------------------- sign-in


def test_without_a_pin_helper_pages_are_open(kb, spec, tmp_path):
    _, http = make(kb, spec, tmp_path)
    assert http.get("/api/helper").get_json() == {"pin_required": False, "signed_in": True}
    assert http.get("/api/camps").status_code == 200


def test_with_a_pin_helper_routes_need_it(kb, spec, tmp_path):
    _, http = make(kb, spec, tmp_path, helper_pin="2468")
    assert http.get("/api/camps").status_code == 401
    assert http.get("/api/outcomes").status_code == 401
    assert http.get("/api/reports/summary").status_code == 401
    assert b"Helper sign-in" in http.get("/camp").data
    assert http.post("/api/helper/login", json={"pin": "0000"}).status_code == 401
    assert http.post("/api/helper/login", json={"pin": "2468"}).status_code == 200
    assert http.get("/api/camps").status_code == 200
    http.post("/api/helper/logout")
    assert http.get("/api/camps").status_code == 401


def test_repeated_wrong_pins_lock_sign_in(kb, spec, tmp_path):
    _, http = make(kb, spec, tmp_path, helper_pin="2468")
    for _ in range(5):
        http.post("/api/helper/login", json={"pin": "1111"})
    assert http.post("/api/helper/login", json={"pin": "2468"}).status_code == 429


def test_the_pin_is_not_kept_in_plain_text(kb, spec, tmp_path):
    app, _ = make(kb, spec, tmp_path, helper_pin="2468")
    assert "2468" not in str(app.config["HELPER_PIN_HASH"])


# ------------------------------------------------------------------------ camps


def test_camp_intake_saves_a_person_with_consent(kb, spec, tmp_path):
    app, http = make(kb, spec, tmp_path)
    cid = http.post("/api/camps", json={"name": "Ward 4"}).get_json()["id"]
    refused = http.post(f"/api/camps/{cid}/people", json={"name": "Murugan", "facts": FARMER})
    assert refused.get_json()["error"]["code"] == "consent_required"

    person = http.post(f"/api/camps/{cid}/people",
                       json={"name": "Murugan", "facts": FARMER, "consent": True, "lang": "ta"})
    assert person.status_code == 201
    body = person.get_json()
    assert body["n_eligible"] > 0 and "Mahatma Gandhi National Rural Employment Guarantee Act (MGNREGA)" in body["schemes"]
    vault = app.extensions["schemematch"].vault
    assert vault.consent(body["id"])["given_by"] == "helper"
    assert vault.consent(body["id"])["lang"] == "ta"
    camp = http.get(f"/api/camps/{cid}").get_json()
    assert [p["id"] for p in camp["people"]] == [body["id"]]


def test_a_bad_answer_saves_nobody(kb, spec, tmp_path):
    app, http = make(kb, spec, tmp_path)
    cid = http.post("/api/camps", json={"name": "Ward 4"}).get_json()["id"]
    response = http.post(f"/api/camps/{cid}/people", json={
        "name": "Murugan", "consent": True, "facts": {**FARMER, "gender": "purple"}})
    assert response.status_code == 400
    assert "gender" in response.get_json()["error"]["fields"]
    assert app.extensions["schemematch"].vault.profiles() == []


def test_check_facts_reads_the_state_first(spec):
    values, errors = check_facts(spec, {"ration_card_type": "white card", "state": "Kerala"})
    assert values["ration_card_type"] == "npns" and not errors


def test_a_printed_sheet_names_schemes_and_where_to_get_papers(kb, spec, tmp_path):
    _, http = make(kb, spec, tmp_path)
    cid = http.post("/api/camps", json={"name": "Ward 4"}).get_json()["id"]
    pid = http.post(f"/api/camps/{cid}/people",
                    json={"name": "Murugan", "facts": FARMER, "consent": True}).get_json()["id"]
    page = http.get(f"/print/{pid}").data.decode()
    assert "Murugan" in page and "MGNREGA" in page and "Papers to collect" in page
    assert http.get(f"/print/camp/{cid}").status_code == 200


# ---------------------------------------------------------------------- reports


def test_a_small_group_shows_nothing(kb, spec, tmp_path):
    vault = Vault(tmp_path / "vault", spec)
    ids = [vault.create_profile(f"P{i}")["id"] for i in range(3)]
    report = anonymous_report(kb.active(), vault, None, ids)
    assert report["suppressed"] is True and report["n_people"] == "<5"
    vault.close()


def test_counts_under_five_are_suppressed_and_names_never_appear(kb, spec, tmp_path, personas):
    vault = Vault(tmp_path / "vault", spec)
    farmer = personas["p001"].profile
    facts = [(a, v, "form", "") for a, v in farmer.items()
             if a in spec.elicitable_names() and v is not None]
    ids = []
    for i in range(6):
        pid = vault.create_profile(f"Farmer{i}")["id"]
        vault.record_many(pid, facts)
        ids.append(pid)
    vault.open_application(ids[0], "pm-kisan", status="applied", verdict="eligible")
    report = anonymous_report(kb.active(), vault, None, ids)
    row = next(s for s in report["schemes"] if s["scheme_id"] == "pm-kisan")
    assert row["eligible"] == 6
    assert row["applied"] == "<5" and row["not_applied"] == 6 - 1
    assert "Farmer" not in str(report)
    vault.close()


# ---------------------------------------------------------------------- partners


def test_the_partner_api_needs_a_live_key_and_stores_nothing(kb, spec, tmp_path):
    app, http = make(kb, spec, tmp_path)
    vault = app.extensions["schemematch"].vault
    record, key = create_key(vault, "Village NGO")
    assert http.post("/api/v1/check", json={"facts": FARMER}).status_code == 401
    headers = {"Authorization": f"Bearer {key}"}
    body = http.post("/api/v1/check", json={"facts": FARMER}, headers=headers)
    assert body.status_code == 200 and body.headers["Cache-Control"] == "no-store"
    result = body.get_json()
    assert any(s["id"] == "cmchis" for s in result["eligible"])
    assert vault.profiles() == []                     # nothing a partner sends is kept
    assert vault.api_key(record["id"])["n_calls"] == 1
    assert key not in str(vault.api_keys())           # only the hash is stored
    vault.revoke_api_key(record["id"])
    assert http.post("/api/v1/check", json={"facts": FARMER}, headers=headers).status_code == 401


def test_the_partner_api_reports_what_it_could_not_read(kb, spec, tmp_path):
    app, http = make(kb, spec, tmp_path)
    _, key = create_key(app.extensions["schemematch"].vault, "NGO")
    result = http.post("/api/v1/check", json={"facts": {"gender": "purple", "age": "40"}},
                       headers={"Authorization": f"Bearer {key}"}).get_json()
    assert "gender" in result["not_understood"] and result["understood"] == {"age": 40.0}


def test_the_rate_limit_slides():
    limiter = RateLimiter(limit=2, window=10)
    assert limiter.allow("k", now=0) and limiter.allow("k", now=1)
    assert not limiter.allow("k", now=2)
    assert limiter.allow("k", now=11)


# ---------------------------------------------------------------- consent, audit


def test_export_holds_everything_but_file_paths(kb, spec, tmp_path):
    _, http = make(kb, spec, tmp_path)
    pid = http.post("/api/profiles", json={"name": "Lakshmi",
                                           "consent": {"given_by": "self", "lang": "ml"}}).get_json()["id"]
    http.post(f"/api/profiles/{pid}/facts", json={"attr": "age", "value": 61})
    response = http.get(f"/api/profiles/{pid}/export")
    assert "attachment" in response.headers["Content-Disposition"]
    data = response.get_json()
    assert data["consents"][0]["lang"] == "ml"
    assert data["fact_history"][0]["attr"] == "age"
    assert "stored_path" not in str(data)


def test_opening_and_changing_a_profile_is_logged_without_values(kb, spec, tmp_path):
    _, http = make(kb, spec, tmp_path)
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    http.get(f"/api/profiles/{pid}")
    http.post(f"/api/profiles/{pid}/facts", json={"attr": "annual_family_income", "value": 72000})
    http.get(f"/api/profiles/{pid}/eligibility")       # a read of a part is not logged
    log = http.get(f"/api/profiles/{pid}/audit").get_json()["log"]
    actions = [entry["action"] for entry in log]
    assert "opened profile" in actions and "POST /facts" in actions
    assert not any("eligibility" in a for a in actions)
    assert "72000" not in str(log)
    http.delete(f"/api/profiles/{pid}")
    vault = Vault(tmp_path / "vault", spec)
    assert vault.audit_log(pid)[0]["action"] == "deleted profile"
    vault.close()


def test_the_notice_comes_in_three_languages(kb, spec, tmp_path):
    _, http = make(kb, spec, tmp_path)
    for lang in ("en", "ta", "ml"):
        notice = http.get(f"/api/privacy/notice?lang={lang}").get_json()
        assert notice["lang"] == lang and len(notice["points"]) == 6


# ---------------------------------------------------------------------- watcher


def test_a_fingerprint_ignores_markup_and_dates():
    a = "<html><script>x=1</script><p>Income limit Rs 1,00,000</p><i>Updated 13-Oct-2026 11:12</i></html>"
    b = "<div>Income limit Rs 1,00,000</div><span>Updated 23-Oct-2026 09:01</span>"
    assert fingerprint(a) == fingerprint(b)
    assert "x=1" not in page_text(a)
    assert fingerprint(a) != fingerprint(a.replace("1,00,000", "1,20,000"))


def test_the_watcher_reports_changed_new_and_unreachable(kb, tmp_path):
    urls = sorted({s.url for scheme in kb.active() for s in scheme.sources})
    pages = {url: f"page {i}" for i, url in enumerate(urls)}

    def fetcher(url):
        if url == urls[0]:
            raise OSError("no route to host")
        return pages[url]

    first = watch(kb, {}, fetcher=fetcher)
    assert {r["status"] for r in first} == {"new", "unreachable"}
    path = save_baseline(first, {}, tmp_path / "hashes.json")
    pages[urls[1]] = "page changed"
    second = watch(kb, load_baseline(path), fetcher=fetcher)
    by_url = {r["url"]: r["status"] for r in second}
    assert by_url[urls[1]] == "changed" and by_url[urls[2]] == "unchanged"
    assert by_url[urls[0]] == "unreachable"


# -------------------------------------------------------------------------- PDF


def test_a_whole_pdf_is_accepted_and_a_cut_one_refused():
    data, media_type, extension = prepare_upload(b"%PDF-1.7\n1 0 obj\n%%EOF\n")
    assert media_type == "application/pdf" and extension == "pdf"
    with pytest.raises(DocumentError):
        prepare_upload(b"%PDF-1.7 cut off")


def test_a_pdf_upload_is_filed_without_a_model(kb, spec, tmp_path):
    _, http = make(kb, spec, tmp_path)
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    response = http.post(f"/api/profiles/{pid}/documents", content_type="multipart/form-data",
                         data={"file": (io.BytesIO(b"%PDF-1.7\n%%EOF\n"), "income.pdf"),
                               "doc_type": "income_certificate"})
    assert response.status_code == 201
    assert response.get_json()["document"]["media_type"] == "application/pdf"
