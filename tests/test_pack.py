"""The application sheet and the age forecast."""

import pytest

from tn_schemematch.documents import default_documents
from tn_schemematch.guided import default_questions
from tn_schemematch.pack import (
    NotEligible,
    application_pack,
    coming_up,
    coming_up_text,
    share_text,
)

WIDOW_57 = {"age": 57.0, "gender": "female", "marital_status": "widowed", "state": "TN",
            "is_destitute": True, "fixed_assets_value": 10000.0,
            "receives_other_pension": False, "is_bpl": True}


@pytest.fixture(scope="module")
def tools():
    return default_documents(), default_questions()


def make(kb, spec, tools, profile, scheme_id, lang="ta", held=()):
    documents, book = tools
    return application_pack(kb.active()[scheme_id], profile, spec, documents, book, lang,
                            active=kb.active(), held=held, person="Lakshmi")


def test_a_sheet_is_made_only_for_an_eligible_scheme(kb, spec, personas, tools):
    profile = personas["p002"].profile
    active = kb.active()
    eligible = active.eligible_ids(profile)
    assert make(kb, spec, tools, profile, eligible[0])["id"] == eligible[0]
    ruled_out = next(s for s in active.ids() if s not in eligible)
    with pytest.raises(NotEligible):
        make(kb, spec, tools, profile, ruled_out)


def test_the_sheet_lists_every_document_the_scheme_needs(kb, spec, personas, tools):
    profile = personas["p002"].profile
    sid = kb.active().eligible_ids(profile)[0]
    pack = make(kb, spec, tools, profile, sid)
    assert len(pack["documents"]) == len(kb[sid].documents)
    assert all(item["status"] in {"have", "missing", "action"} for item in pack["documents"])


def test_documents_on_file_are_marked_had(kb, spec, personas, tools):
    profile = personas["p002"].profile
    sid = kb.active().eligible_ids(profile)[0]
    everything = [t.id for t in tools[0].uploadable()]
    pack = make(kb, spec, tools, profile, sid, held=everything)
    assert pack["n_missing"] == 0


def test_the_officer_s_questions_are_the_clauses_that_decided_it(kb, spec, tools):
    profile = dict(WIDOW_57, age=62.0)
    pack = make(kb, spec, tools, profile, "tn-old-age-pension")
    attrs = [fact["attr"] for fact in pack["facts"]]
    assert "age" in attrs
    age = next(f for f in pack["facts"] if f["attr"] == "age")
    assert age["label"] == "வயது" and age["answer"].startswith("62")
    assert "gender" not in attrs, "the old age pension does not check gender"


def test_plain_words_lead_and_the_official_name_follows(kb, spec, tools):
    pack = make(kb, spec, tools, dict(WIDOW_57, age=62.0), "tn-old-age-pension", lang="en")
    assert pack["name"] == "Old age pension (Tamil Nadu)"
    assert pack["official_name"] == kb["tn-old-age-pension"].name
    assert pack["where"] and pack["caveat"]


def test_the_whatsapp_text_carries_the_checklist(kb, spec, tools):
    pack = make(kb, spec, tools, dict(WIDOW_57, age=62.0), "tn-old-age-pension")
    text = share_text(pack)
    assert pack["name"] in text
    for item in pack["documents"]:
        assert item["label"] in text


def test_the_old_age_pension_is_coming_up_at_sixty(kb, spec):
    later = coming_up(kb.active(), WIDOW_57, spec)
    ids = {row["id"]: row for row in later}
    assert ids["tn-old-age-pension"]["in_years"] == 3
    assert ids["tn-old-age-pension"]["at_age"] == 60
    text = coming_up_text(kb.active(), later, "ta")
    assert "60 வயதில்" in text


def test_nothing_is_forecast_without_an_age(kb, spec):
    assert coming_up(kb.active(), {k: v for k, v in WIDOW_57.items() if k != "age"}, spec) == []


def test_a_scheme_already_held_is_not_forecast(kb, spec):
    profile = dict(WIDOW_57, age=62.0)
    now = set(kb.active().eligible_ids(profile))
    assert not now & {row["id"] for row in coming_up(kb.active(), profile, spec)}
