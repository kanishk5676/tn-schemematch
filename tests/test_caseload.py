"""The helper's list: who needs what, most actionable first. No web layer needed."""

from datetime import date, timedelta

import pytest

from tn_schemematch.caseload import caseload
from tn_schemematch.documents import default_documents
from tn_schemematch.vault import Vault, VaultError

WIDOW_62 = {"age": 62, "gender": "female", "marital_status": "widowed", "state": "TN",
            "is_destitute": True, "fixed_assets_value": 10000,
            "receives_other_pension": False, "is_bpl": True}


@pytest.fixture
def vault(tmp_path, spec):
    return Vault(tmp_path / "vault", spec)


def person(vault, name, facts, **kwargs):
    pid = vault.create_profile(name, **kwargs)["id"]
    for attr, value in facts.items():
        vault.record(pid, attr, value, source="form")
    return pid


def test_an_application_is_recorded_and_updated(vault):
    pid = person(vault, "Selvi", WIDOW_62)
    vault.set_application(pid, "tn-old-age-pension", status="applied",
                          reference="SSS/123", applied_on="2026-09-01")
    row = vault.set_application(pid, "tn-old-age-pension", status="sanctioned")
    assert row["status"] == "sanctioned"
    assert row["applied_on"] == "2026-09-01", "a later update keeps the date applied"
    assert len(vault.applications(pid)) == 1
    with pytest.raises(VaultError):
        vault.set_application(pid, "tn-old-age-pension", status="lost")
    with pytest.raises(VaultError):
        vault.set_application(pid, "tn-old-age-pension", status="applied", applied_on="soon")


def test_the_list_says_who_can_get_what_and_what_is_missing(vault, kb, spec):
    pid = person(vault, "Selvi", WIDOW_62)
    rows = caseload(vault, kb.active(), spec, default_documents(), "en")["people"]
    row = next(r for r in rows if r["id"] == pid)
    assert any(e["id"] == "tn-old-age-pension" for e in row["eligible"])
    assert row["to_collect"], "nothing is on file, so papers are missing"


def test_a_stalled_application_comes_first(vault, kb, spec):
    quiet = person(vault, "Selvi", WIDOW_62)
    person(vault, "Kumar", {"age": 30})
    long_ago = (date.today() - timedelta(days=45)).isoformat()
    vault.set_application(quiet, "tn-old-age-pension", status="applied", applied_on=long_ago)
    result = caseload(vault, kb.active(), spec, default_documents(), "en")
    assert result["people"][0]["id"] == quiet
    assert result["people"][0]["follow_up"]
    assert result["totals"]["follow_up"] == 1


def test_something_opening_soon_is_listed(vault, kb, spec):
    pid = person(vault, "Kamala", {**WIDOW_62, "age": 59})
    row = next(r for r in caseload(vault, kb.active(), spec, default_documents(), "ta")["people"]
               if r["id"] == pid)
    assert any(s["id"] == "tn-old-age-pension" and s["at_age"] == 60 for s in row["soon"])


def test_an_old_vault_gains_the_new_columns(tmp_path, spec):
    import sqlite3

    root = tmp_path / "old"
    root.mkdir()
    db = sqlite3.connect(root / "vault.db")
    db.executescript("""
        CREATE TABLE documents (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL,
            doc_type TEXT NOT NULL, filename TEXT NOT NULL, stored_path TEXT NOT NULL,
            media_type TEXT NOT NULL, reading TEXT, status TEXT NOT NULL,
            uploaded_at REAL NOT NULL);
    """)
    db.close()
    vault = Vault(root, spec)
    columns = {row["name"] for row in vault._db.execute("PRAGMA table_info(documents)")}
    assert "keep_photo" in columns
