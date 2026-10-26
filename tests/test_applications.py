"""Around the tracker: history and verdicts, rejections, outcomes, complaints, calendar."""

import time
from datetime import date, timedelta

import pytest

pytest.importorskip("flask")

from tn_schemematch.applications import (  # noqa: E402
    calendar,
    clean_reference,
    complaint,
    explain_rejection,
    follow_up,
    load_rejections,
)
from tn_schemematch.attributes import SchemaError  # noqa: E402
from tn_schemematch.kb import ApplicationWindow, KBError, SchemeKB, load_scheme  # noqa: E402
from tn_schemematch.web import create_app  # noqa: E402


@pytest.fixture(scope="module")
def reasons(spec):
    return load_rejections(spec)


@pytest.fixture
def http(kb, spec, tmp_path):
    return create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "vault").test_client()


def saved_persona(http, persona, name="Murugan"):
    vault = http.application.extensions["schemematch"].vault
    pid = vault.create_profile(name)["id"]
    vault.record_many(pid, [(attr, value, "form", "") for attr, value in persona.profile.items()
                            if value is not None and attr in vault.spec.elicitable_names()])
    return pid


def track(http, pid, scheme_id, status, **fields):
    return http.post(f"/api/profiles/{pid}/applications",
                     json={"scheme_id": scheme_id, "status": status, **fields})


def a_row(status="applied", applied_on=None, reference="", reason=None, updated_at=None):
    """A tracker row as the vault returns it."""
    return {"scheme_id": "pm-kisan", "status": status, "reference": reference, "note": "",
            "applied_on": applied_on, "reason": reason, "verdict": "eligible",
            "updated_at": updated_at or time.time()}


# ------------------------------------------------------------------- vocabulary


def test_every_rejection_reason_names_real_attributes_and_documents(spec):
    from tn_schemematch.documents import default_documents
    reasons = load_rejections(spec, document_types=default_documents().types)
    assert "other" in reasons and "income_above_limit" in reasons
    assert all(r.kind in {"eligibility", "documents", "process"} for r in reasons.values())


def test_an_unknown_attribute_in_a_reason_is_refused(spec, tmp_path):
    path = tmp_path / "r.yaml"
    path.write_text("reasons:\n  other: {label: Other, kind: process}\n"
                    "  odd: {label: Odd, kind: eligibility, attrs: [shoe_size]}\n")
    with pytest.raises(SchemaError, match="shoe_size"):
        load_rejections(spec, path)


def test_an_aadhaar_typed_as_a_reference_is_masked(http, personas):
    assert clean_reference("1234 5678 9012") == "XXXX XXXX XXXX"
    assert clean_reference("ESV/2026/000123") == "ESV/2026/000123"
    pid = saved_persona(http, personas["p001"])
    row = track(http, pid, "pm-kisan", "applied", reference="1234 5678 9012").get_json()
    assert row["reference"] == "XXXX XXXX XXXX"


# ---------------------------------------------------------------------- tracker


def test_every_change_keeps_its_history_and_the_rules_verdict(http, personas):
    pid = saved_persona(http, personas["p001"])
    track(http, pid, "pm-kisan", "applied", applied_on="2026-08-01")
    row = track(http, pid, "pm-kisan", "sanctioned").get_json()
    assert row["status"] == "sanctioned" and row["verdict"] == "eligible"
    assert [h["status"] for h in row["history"]] == ["applied", "sanctioned"]
    assert {h["verdict"] for h in row["history"]} == {"eligible"}
    listed = http.get(f"/api/profiles/{pid}/applications").get_json()["applications"]
    assert listed[0]["history"] == row["history"]


def test_reasons_are_checked(http, personas):
    pid = saved_persona(http, personas["p001"])
    assert track(http, pid, "pm-kisan", "rejected", reason="bad luck").status_code == 400
    assert track(http, pid, "pm-kisan", "applied", reason="other").status_code == 400
    plain = track(http, pid, "pm-kisan", "rejected").get_json()
    assert plain["reason"] is None
    assert plain["rejection"]["id"] == "no_reason_given"


def test_a_rejection_is_explained_against_the_rule(http, personas):
    pid = saved_persona(http, personas["p001"])
    row = track(http, pid, "cmchis", "rejected", reason="income_above_limit").get_json()
    rejection = row["rejection"]
    assert rejection["rules_say"] == "eligible" and rejection["disagrees"] is True
    assert any(c["attr"] == "annual_family_income" and c["met"] == "eligible"
               for c in rejection["clauses"])
    assert rejection["guides"][0]["type"] == "income_certificate"
    assert row["can_complain"] is True


def test_a_rejection_the_rules_agree_with_is_not_a_disagreement(kb, spec, personas, reasons):
    profile = dict(personas["p001"].profile, annual_family_income=900000.0)
    result = explain_rejection(kb["cmchis"], spec, profile, reasons["income_above_limit"])
    assert result["rules_say"] == "ineligible" and result["disagrees"] is False


def test_outcomes_flag_rejections_that_contradict_the_rules(http, personas):
    pid = saved_persona(http, personas["p001"])
    track(http, pid, "cmchis", "rejected", reason="income_above_limit")
    track(http, pid, "pm-kisan", "rejected", reason="documents_missing")
    report = http.get("/api/outcomes").get_json()
    assert report["needs_review"] == ["cmchis"]  # a missing paper is not the rule's fault
    rows = {r["scheme_id"]: r for r in report["schemes"]}
    assert rows["pm-kisan"]["rejected"] == 1 and rows["pm-kisan"]["disagreements"] == 0
    assert "Murugan" not in str(report)


def test_outcomes_need_a_helper_when_a_pin_is_set(kb, spec, tmp_path):
    http = create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "vault",
                      helper_pin="2468").test_client()
    assert http.get("/api/outcomes").status_code == 401
    http.post("/api/helper/login", json={"pin": "2468"})
    assert http.get("/api/outcomes").status_code == 200


def test_deleting_a_person_deletes_their_history(http, personas):
    pid = saved_persona(http, personas["p001"])
    track(http, pid, "pm-kisan", "applied")
    http.delete(f"/api/profiles/{pid}")
    assert http.get("/api/outcomes").get_json()["n_applications"] == 0


# ----------------------------------------------------------------- follow-ups


def test_a_long_wait_asks_for_a_follow_up():
    old = (date.today() - timedelta(days=45)).isoformat()
    assert follow_up(a_row(applied_on=old))["kind"] == "no_decision"
    assert follow_up(a_row()) is None
    assert follow_up(a_row(status="sanctioned", applied_on=old)) is None


# ------------------------------------------------------------------ complaints


def test_a_complaint_claims_eligibility_only_when_the_rules_do(kb, spec, personas, reasons):
    row = a_row(status="rejected", applied_on="2026-08-01", reference="ESV/1",
                reason="income_above_limit")
    eligible = complaint(kb["pm-kisan"], spec, personas["p001"].profile, "Murugan", row, reasons)
    assert eligible["grounded_in_rules"] is True
    assert "I meet these conditions" in eligible["text"]
    assert "01-08-2026" in eligible["text"] and "ESV/1" in eligible["text"]
    assert "Income is above the limit" in eligible["text"]

    not_eligible = complaint(kb["pm-kisan"], spec,
                             dict(personas["p001"].profile, land_owned_acres=0.0),
                             "Murugan", row, reasons)
    assert not_eligible["grounded_in_rules"] is False
    assert "I meet these conditions" not in not_eligible["text"]
    assert "reason for this decision" in not_eligible["text"]


@pytest.mark.parametrize("lang,word", [("ta", "பொருள்"), ("ml", "വിഷയം")])
def test_complaints_in_tamil_and_malayalam(kb, spec, personas, reasons, lang, word):
    letter = complaint(kb["pm-kisan"], spec, personas["p001"].profile, "Murugan",
                       a_row(), reasons, lang=lang)
    assert word in letter["text"]


def test_a_complaint_names_where_to_send_it(http, personas):
    pid = saved_persona(http, personas["p001"])
    track(http, pid, "cmchis", "applied")
    letter = http.get(f"/api/profiles/{pid}/applications/cmchis/complaint?lang=ta").get_json()
    assert letter["lang"] == "ta"
    assert letter["channels"]  # Tamil Nadu scheme: the state's grievance channel
    assert http.get(f"/api/profiles/{pid}/applications/pm-kisan/complaint").status_code == 404


# -------------------------------------------------------------------- calendar


def test_a_yearly_window_rolls_forward():
    window = ApplicationWindow(opens=date(2024, 7, 1), closes=date(2024, 7, 31),
                               source="https://example.gov.in/", every_year=True)
    assert window.next_from(date(2026, 7, 10)) == (date(2026, 7, 1), date(2026, 7, 31))
    assert window.next_from(date(2026, 8, 10)) == (date(2027, 7, 1), date(2027, 7, 31))
    once = ApplicationWindow(opens=date(2024, 7, 1), closes=date(2024, 7, 31),
                             source="https://example.gov.in/")
    assert once.next_from(date(2026, 1, 1)) is None


def test_a_window_needs_a_source(spec, tmp_path):
    path = tmp_path / "w.yaml"
    path.write_text("id: w\nname: W\nlevel: central\neligibility_prose: p\nsummary: s\n"
                    "eligibility: {attr: age, op: gte, value: 18}\n"
                    "windows: [{opens: 2026-07-01, closes: 2026-07-31}]\n")
    with pytest.raises(KBError, match="source"):
        load_scheme(path, spec)


def test_the_calendar_merges_follow_ups_windows_and_birthdays(spec, tmp_path, kb):
    path = tmp_path / "w.yaml"
    path.write_text("id: w\nname: Window scheme\nlevel: central\neligibility_prose: p\n"
                    "summary: s\neligibility: {attr: age, op: gte, value: 18}\n"
                    "windows: [{opens: 2026-07-01, closes: 2026-07-31, every_year: true,"
                    " source: 'https://example.gov.in/notice'}]\n")
    small = SchemeKB({"w": load_scheme(path, spec), "tn-old-age-pension": kb["tn-old-age-pension"],
                      "pm-kisan": kb["pm-kisan"]}, spec)
    profile = {"age": 58.0, "state": "TN", "is_destitute": True, "fixed_assets_value": 0.0,
               "receives_other_pension": False}
    old = (date(2026, 6, 1) - timedelta(days=40)).isoformat()
    items = calendar(small, spec, profile, [a_row(applied_on=old)], today=date(2026, 6, 1))
    kinds = [i["kind"] for i in items]
    assert kinds[:2] == ["follow_up", "window"]
    assert items[0]["overdue"] is True
    assert any(i["kind"] == "age" and i["scheme_id"] == "tn-old-age-pension" for i in items)
