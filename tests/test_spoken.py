"""The spoken result: what a person hears is built from the rule engine, in their language."""

from dataclasses import replace

import pytest

from tn_schemematch.documents import default_documents
from tn_schemematch.kb import SchemeKB
from tn_schemematch.serialize import near_misses
from tn_schemematch.spoken import spoken_result


@pytest.fixture(scope="module")
def documents():
    return default_documents()


def _tamil_letters(text):
    return sum(1 for ch in text if "஀" <= ch <= "௿")


def test_spoken_result_names_every_eligible_scheme_the_rules_found(kb, personas, documents):
    profile = personas["p001"].profile
    result = spoken_result(kb.active(), profile, "en", documents=documents)
    assert {line["id"] for line in result["eligible"]} == set(kb.active().eligible_ids(profile))


def test_tamil_result_is_tamil(kb, personas, documents):
    result = spoken_result(kb.active(), personas["p001"].profile, "ta", documents=documents)
    text = result["text"]
    assert _tamil_letters(text) > len(text) * 0.5, text


def test_tamil_never_falls_back_to_an_english_summary(kb, personas):
    """An English summary read out by a Tamil voice is worse than saying nothing."""
    profile = personas["p001"].profile
    result = spoken_result(kb.active(), profile, "ta")
    for line in result["eligible"]:
        scheme = kb[line["id"]]
        if not (scheme.plain.get("ta") or {}).get("what"):
            assert line["what"] == ""


def test_documents_to_bring_are_spoken(kb, personas, documents):
    result = spoken_result(kb.active(), personas["p001"].profile, "en", documents=documents)
    assert "Bring:" in result["text"]


def test_documents_already_held_are_not_asked_for(kb, personas, documents):
    profile = personas["p001"].profile
    everything = [t.id for t in documents.uploadable()]
    result = spoken_result(kb.active(), profile, "en", documents=documents, held=everything)
    assert "Bring:" not in result["text"]


def test_unverified_schemes_are_said_as_may_with_a_caveat(kb, personas):
    result = spoken_result(kb.active(), personas["p001"].profile, "en")
    assert result["text"].startswith("You may be able to get")
    assert "Confirm at an e-Sevai centre" in result["text"]


def test_verified_schemes_are_said_as_you_can_apply(kb, personas):
    profile = personas["p001"].profile
    active = kb.active()
    verified = SchemeKB({sid: replace(active[sid], status="verified")
                         for sid in active.eligible_ids(profile)}, kb.spec)
    result = spoken_result(verified, profile, "en")
    assert result["text"].startswith("You can apply for")
    assert "Confirm at" not in result["text"]


def test_nothing_eligible_says_so_and_offers_more_questions(kb):
    result = spoken_result(kb.active(), {}, "ta")
    assert result["eligible"] == []
    assert "எந்தத் திட்டமும் உறுதியாகவில்லை" in result["text"]
    assert result["n_open"] > 0


def test_near_misses_are_named(kb, personas, spec):
    profile = personas["p001"].profile
    near = [n["id"] for n in near_misses(kb.active(), profile, spec)]
    assert near, "p001 should miss something by one condition"
    result = spoken_result(kb.active(), profile, "en", near_ids=near)
    assert result["near"] and "just one condition" in result["text"]


def test_plain_text_is_preferred_over_the_official_name(kb, personas):
    profile = personas["p001"].profile
    active = kb.active()
    sid = active.eligible_ids(profile)[0]
    plain = {"ta": {"name": "சோதனைப் பெயர்", "what": "மாதம் ஆயிரம் ரூபாய்"},
             "en": {"name": "Test name", "what": "A thousand rupees a month"}}
    patched = SchemeKB({sid: replace(active[sid], plain=plain)}, kb.spec)
    for lang in ("ta", "en"):
        result = spoken_result(patched, profile, lang)
        assert plain[lang]["name"] in result["text"]
        assert plain[lang]["what"] in result["text"]
