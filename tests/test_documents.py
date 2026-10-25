"""Documents: the vocabulary, the reader's guard rails, reconciliation, and the checklist.

The reader is driven by a ``ScriptedClient`` that returns a fixed JSON reading, so these
tests check what this module does with a model's answer — which facts it keeps, which it
discards, what it masks — not what any model would say about a photo.
"""

import io
import json

import pytest

pytest.importorskip("flask")
PIL = pytest.importorskip("PIL.Image")

from tn_schemematch.documents import (  # noqa: E402
    DocumentError,
    apply_reading,
    checklist,
    default_documents,
    load_documents,
    manual_reading,
    mask_ids,
    prepare_image,
    read_document,
    validate_documents,
)
from tn_schemematch.attributes import SchemaError  # noqa: E402
from tn_schemematch.systems.base import ScriptedClient  # noqa: E402
from tn_schemematch.vault import Vault  # noqa: E402
from tn_schemematch.web import create_app  # noqa: E402


@pytest.fixture(scope="module")
def vocab():
    return default_documents()


@pytest.fixture
def vault(tmp_path, spec):
    v = Vault(tmp_path / "vault", spec)
    yield v
    v.close()


def png(size=(60, 40)) -> bytes:
    buffer = io.BytesIO()
    PIL.new("RGB", size, (240, 240, 230)).save(buffer, format="PNG")
    return buffer.getvalue()


def reader(**payload) -> ScriptedClient:
    reading = {"doc_type": "unknown", "holder_name": "", "id_last4": "", "issue_date": "",
               "about_profile_holder": True, "facts": []}
    reading.update(payload)
    return ScriptedClient(default=json.dumps(reading))


# -------------------------------------------------------------------- vocabulary


def test_every_scheme_document_is_mapped(vocab, kb):
    assert validate_documents(vocab, kb) == []


def test_alternatives_map_to_several_types(vocab):
    assert set(vocab.types_for("BPL card or income certificate")) == {
        "ration_card", "income_certificate"}
    assert "aadhaar" in vocab.types_for("Age proof")


def test_vocabulary_refuses_attributes_it_cannot_state(tmp_path, spec):
    bad = tmp_path / "documents.yaml"
    bad.write_text("types:\n  x:\n    kind: document\n    label: X\n"
                   "    evidences: [is_widow]\n    matches: []\n")
    with pytest.raises(SchemaError, match="cannot be stated"):
        load_documents(spec, bad)


# ----------------------------------------------------------------------- reading


def test_reader_keeps_only_what_the_document_type_can_state(spec, vocab):
    client = reader(doc_type="income_certificate", facts=[
        {"attr": "annual_family_income", "value": "Rs. 72,000 per annum",
         "evidence": "Annual family income: Rs. 72,000"},
        {"attr": "social_category", "value": "SC", "evidence": "community SC"},
        {"attr": "fixed_assets_value", "value": "a lot", "evidence": "?"},
    ])
    reading = read_document(client, spec, vocab, png(), "image/png", holder="Lakshmi")
    assert [(f["attr"], f["value"]) for f in reading["facts"]] == [
        ("annual_family_income", 72000.0)]
    reasons = {r["attr"]: r["reason"] for r in reading["rejected"]}
    assert "cannot state" in reasons["social_category"]
    assert "fixed_assets_value" in reasons


def test_the_schema_limits_the_model_to_the_vocabulary(spec, vocab):
    client = reader(doc_type="aadhaar")
    read_document(client, spec, vocab, png(), "image/png")
    schema = client.image_calls[0]["schema"]
    allowed = schema["properties"]["facts"]["items"]["properties"]["attr"]["enum"]
    assert set(allowed) <= set(spec.elicitable_names())
    assert "is_widow" not in allowed  # derived
    assert client.image_calls[0]["media_types"] == ["image/png"]


def test_id_numbers_are_masked_before_storage(spec, vocab):
    client = reader(doc_type="aadhaar", holder_name="Lakshmi 1234 5678 9012", facts=[
        {"attr": "gender", "value": "female", "evidence": "1234 5678 9012 FEMALE"}])
    reading = read_document(client, spec, vocab, png(), "image/png")
    assert "5678" not in json.dumps(reading)
    assert reading["facts"][0]["evidence"] == "XXXX9012 FEMALE"


def test_masking_spares_dates_and_small_numbers():
    assert mask_ids("DOB 12-05-1979, income 1,20,000") == "DOB 12-05-1979, income 1,20,000"
    assert mask_ids("ph 98765 43210") == "ph XXXX3210"


def test_a_document_about_someone_else_states_nothing(spec, vocab):
    client = reader(doc_type="community_certificate", about_profile_holder=False, facts=[
        {"attr": "social_category", "value": "SC", "evidence": "SC"}])
    reading = read_document(client, spec, vocab, png(), "image/png")
    assert reading["facts"] == []  # not even the implied certificate
    assert reading["rejected"][0]["reason"] == "the document is about someone else"


def test_holding_a_document_implies_facts(spec, vocab):
    client = reader(doc_type="community_certificate", facts=[
        {"attr": "social_category", "value": "adi dravidar", "evidence": "Adi Dravidar"}])
    reading = read_document(client, spec, vocab, png(), "image/png")
    facts = {f["attr"]: f for f in reading["facts"]}
    assert facts["social_category"]["value"] == "SC"
    assert facts["has_community_certificate"]["implied"] is True


def test_unrecognised_type_reads_nothing(spec, vocab):
    client = reader(doc_type="passport", facts=[
        {"attr": "age", "value": "45", "evidence": "45"}])
    reading = read_document(client, spec, vocab, png(), "image/png")
    assert reading["doc_type"] == "unknown" and reading["facts"] == []


def test_type_mismatch_is_reported(spec, vocab):
    client = reader(doc_type="bank_passbook")
    reading = read_document(client, spec, vocab, png(), "image/png",
                            expected_type="ration_card")
    assert reading["type_mismatch"] is True
    assert reading["doc_type"] == "bank_passbook"


def test_manual_reading_needs_no_model(spec, vocab):
    reading = manual_reading(vocab, spec, "bank_passbook")
    assert [(f["attr"], f["value"]) for f in reading["facts"]] == [("has_bank_account", True)]
    with pytest.raises(DocumentError):
        manual_reading(vocab, spec, "office_action")  # an action is never uploaded


# ------------------------------------------------------------------------ images


def test_images_are_reencoded_as_jpeg():
    data, media_type, extension = prepare_image(png((3000, 2000)))
    assert (media_type, extension) == ("image/jpeg", "jpg")
    assert max(PIL.open(io.BytesIO(data)).size) == 1600


def test_non_images_and_oversized_uploads_are_refused():
    with pytest.raises(DocumentError) as wrong_type:
        prepare_image(b"%PDF-1.7 not an image")
    assert wrong_type.value.status == 415
    with pytest.raises(DocumentError) as too_big:
        prepare_image(b"\x89PNG\r\n\x1a\n" + b"0" * (10 * 1024 * 1024))
    assert too_big.value.status == 413


# ------------------------------------------------------------------ reconciling


def test_a_document_never_silently_overwrites(spec, vocab, vault):
    pid = vault.create_profile("Lakshmi")["id"]
    vault.record(pid, "annual_family_income", "month-ku 3000", source="query")
    vault.record(pid, "district", "Madurai", source="query")
    client = reader(doc_type="income_certificate", facts=[
        {"attr": "annual_family_income", "value": "72000", "evidence": "Rs 72,000"},
        {"attr": "district", "value": "Madurai", "evidence": "Madurai District"}])
    reading = read_document(client, spec, vocab, png(), "image/png")

    outcome = apply_reading(vault, pid, "doc1", reading)
    assert [c["attr"] for c in outcome["conflicts"]] == ["annual_family_income"]
    assert outcome["conflicts"][0]["current"] == 36000.0
    assert [c["attr"] for c in outcome["confirmed"]] == ["district"]
    profile, sources = vault.profile(pid)
    assert profile["annual_family_income"] == 36000.0  # untouched
    assert sources["district"] == "document"  # agreeing fact now carries the document


# --------------------------------------------------------------------- checklist


def test_checklist_ranks_what_to_collect(vocab, kb, personas):
    active = kb.active()
    eligible = personas["p001"].gold_eligible(kb)
    result = checklist(vocab, active, eligible, held_types=[])
    counts = [entry["n_schemes"] for entry in result["to_collect"]]
    assert counts == sorted(counts, reverse=True)
    assert result["n_ready"] == sum(1 for s in result["schemes"] if not any(
        i["status"] == "missing" for i in s["items"]))


def test_holding_a_document_ticks_every_scheme_that_needs_it(vocab, kb, personas):
    eligible = personas["p001"].gold_eligible(kb)
    before = checklist(vocab, kb.active(), eligible, held_types=[])
    after = checklist(vocab, kb.active(), eligible, held_types=["aadhaar", "bank_passbook"])
    labels = [entry["label"] for entry in after["to_collect"]]
    assert "Aadhaar card" not in labels and "Bank passbook" not in labels
    assert len(after["to_collect"]) < len(before["to_collect"])


def test_actions_are_listed_but_never_missing(vocab, kb):
    scheme = next(s for s in kb.active() if "Mobile number" in s.documents)
    result = checklist(vocab, kb.active(), [scheme.id], held_types=[])
    item = next(i for i in result["schemes"][0]["items"] if i["requirement"] == "Mobile number")
    assert item["status"] == "action"


# -------------------------------------------------------------------------- HTTP


def make_http(kb, spec, tmp_path, client=None):
    return create_app(kb=kb, spec=spec, client=client,
                      vault_dir=tmp_path / "vault").test_client()


def upload(http, pid, data=None, **form):
    form["file"] = (io.BytesIO(data if data is not None else png()), "photo.png")
    return http.post(f"/api/profiles/{pid}/documents", data=form,
                     content_type="multipart/form-data")


def test_upload_reads_merges_and_resolves(kb, spec, tmp_path):
    client = reader(doc_type="income_certificate", facts=[
        {"attr": "annual_family_income", "value": "72000", "evidence": "Rs 72,000"}])
    http = make_http(kb, spec, tmp_path, client)
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    http.post(f"/api/profiles/{pid}/facts",
              json={"attr": "annual_family_income", "value": 36000})

    response = upload(http, pid)
    assert response.status_code == 201
    body = response.get_json()
    assert body["document"]["status"] == "read"
    assert "stored_path" not in body["document"]
    assert body["conflicts"][0]["document_value"] == 72000.0

    doc_id = body["document"]["id"]
    resolved = http.post(f"/api/profiles/{pid}/documents/{doc_id}/resolve",
                         json={"attr": "annual_family_income", "keep": "document"}).get_json()
    income = next(f for f in resolved["facts"] if f["attr"] == "annual_family_income")
    assert income["value"] == 72000.0 and income["source"] == "document"
    again = http.post(f"/api/profiles/{pid}/documents/{doc_id}/resolve",
                      json={"attr": "annual_family_income", "keep": "document"})
    assert again.status_code == 404  # settled once

    assert http.get(body["document"]["file_url"]).data[:3] == b"\xff\xd8\xff"


def test_upload_without_a_model_uses_the_chosen_type(kb, spec, tmp_path):
    http = make_http(kb, spec, tmp_path)
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    assert http.get("/api/documents/types").get_json()["can_read"] is False

    refused = upload(http, pid)
    assert refused.status_code == 400
    assert refused.get_json()["error"]["code"] == "needs_type"

    body = upload(http, pid, doc_type="bank_passbook").get_json()
    assert body["document"]["status"] == "manual"
    assert any(f["attr"] == "has_bank_account" and f["source"] == "document"
               for f in body["facts"])


def test_an_unreadable_photo_waits_for_its_type(kb, spec, tmp_path):
    http = make_http(kb, spec, tmp_path, reader(doc_type="unknown"))
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    body = upload(http, pid).get_json()
    assert body["document"]["status"] == "unread"
    doc_id = body["document"]["id"]

    fixed = http.post(f"/api/profiles/{pid}/documents/{doc_id}/type",
                      json={"doc_type": "aadhaar"}).get_json()
    assert fixed["document"]["doc_type"] == "aadhaar"
    assert any(f["attr"] == "has_aadhaar" for f in fixed["facts"])


def test_bad_uploads_are_refused(kb, spec, tmp_path):
    http = make_http(kb, spec, tmp_path)
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    assert upload(http, pid, data=b"%PDF-1.7", doc_type="aadhaar").status_code == 415
    assert upload(http, pid, doc_type="passport").status_code == 400
    assert upload(http, "nobody", doc_type="aadhaar").status_code == 404


def test_deleting_a_document_reopens_the_checklist(kb, spec, tmp_path):
    http = make_http(kb, spec, tmp_path)
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    doc = upload(http, pid, doc_type="aadhaar").get_json()["document"]
    assert http.get(doc["file_url"]).status_code == 200
    assert http.delete(f"/api/profiles/{pid}/documents/{doc['id']}").status_code == 200
    assert http.get(doc["file_url"]).status_code == 404
    assert http.get(f"/api/profiles/{pid}").get_json()["documents"] == []
