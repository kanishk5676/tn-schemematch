"""Kerala and Malayalam: the script, the vocabulary, the schemes and the test profiles."""

import pytest

from tn_schemematch.attributes import SchemaError, _fold
from tn_schemematch.benefits import resolve
from tn_schemematch.interview import normalize_extraction
from tn_schemematch.kb import districts_by_state, load_scheme, validate_kb, SchemeKB

KERALA_PENSIONS = ["kl-agricultural-labour-pension", "kl-disability-pension",
                   "kl-old-age-pension", "kl-unmarried-women-pension", "kl-widow-pension"]


# ------------------------------------------------------------------------ script


@pytest.mark.parametrize("text", ["ലക്ഷം", "രണ്ട് ഏക്കർ", "കർഷകത്തൊഴിലാളി", "லட்சம்"])
def test_the_normalizer_keeps_indic_words_whole(text):
    """It used to keep only the Tamil block, so vowel signs and the virama of every other
    script became spaces: "ലക്ഷം" (lakh) came out as "ലക ഷ"."""
    assert _fold(text) == text


def test_an_old_style_chillu_is_not_split():
    assert " " not in _fold("അവന്‍")


@pytest.mark.parametrize("attr,raw,value", [
    ("annual_family_income", "2 ലക്ഷം", 200000.0),
    ("annual_family_income", "മാസം 8000", 96000.0),
    ("land_owned_acres", "80 sentu", 0.8),
    ("land_owned_acres", "50 സെന്റ്", 0.5),
    ("state", "കേരളം", "KL"),
    ("district", "കോഴിക്കോട്", "Kozhikode"),
    ("district", "calicut", "Kozhikode"),
    ("gender", "സ്ത്രീ", "female"),
    ("marital_status", "vidhava", "widowed"),
    ("occupation", "കർഷകത്തൊഴിലാളി", "agri_labourer"),
    ("occupation", "njan karshakan aanu", "farmer"),
    ("has_bank_account", "ഉണ്ട്", True),
    ("has_bank_account", "ഇല്ല", False),
])
def test_malayalam_and_manglish_answers(spec, attr, raw, value):
    assert spec.canonicalize(attr, raw) == value


# -------------------------------------------------------------------- vocabulary


def test_a_card_colour_means_what_it_means_in_that_state(spec):
    assert spec.canonicalize("ration_card_type", "white card", context={"state": "KL"}) == "npns"
    assert spec.canonicalize("ration_card_type", "white card", context={"state": "TN"}) == "phh_rice"
    assert spec.canonicalize("ration_card_type", "yellow card", context={"state": "KL"}) == "aay"
    with pytest.raises(SchemaError, match="different states"):
        spec.canonicalize("ration_card_type", "white card")


def test_extraction_reads_the_state_before_the_card(spec):
    profile, rejected = normalize_extraction(
        spec, {"ration_card_type": "yellow card", "state": "Kerala"})
    assert profile["ration_card_type"] == "aay" and not rejected


def test_the_vault_reads_values_in_the_person_s_state(tmp_path, spec):
    from tn_schemematch.vault import Vault
    vault = Vault(tmp_path / "vault", spec)
    pid = vault.create_profile("Fathima")["id"]
    vault.record_many(pid, [("ration_card_type", "white card", "query", ""),
                            ("state", "kerala", "query", "")])
    assert vault.profile(pid)[0]["ration_card_type"] == "npns"
    vault.close()


def test_every_district_belongs_to_exactly_one_state(spec):
    by_state = districts_by_state()
    names = [d for ds in by_state.values() for d in ds]
    assert len(names) == len(set(names))
    assert set(names) == set(spec["district"].domain)
    assert len(by_state["KL"]) == 14 and len(by_state["TN"]) == 38


def test_a_state_scheme_may_not_name_another_state_s_district(tmp_path, spec, kb):
    path = tmp_path / "x.yaml"
    path.write_text(
        "id: kl-x\nname: X\nlevel: state\njurisdiction: KL\nsummary: s\neligibility_prose: p\n"
        "eligibility:\n  all:\n    - {attr: state, op: eq, value: KL}\n"
        "    - {attr: district, op: in, value: [Kozhikode, Madurai]}\n")
    small = SchemeKB({"kl-x": load_scheme(path, spec)}, spec)
    assert any("Madurai" in problem for problem in validate_kb(small))


# ----------------------------------------------------------------------- schemes


def test_kerala_pensions_are_refuted_for_a_tamil_nadu_resident(kb, personas):
    tn = personas["p002"].profile
    for scheme_id in KERALA_PENSIONS:
        assert kb[scheme_id].verdict(tn).value == "ineligible"


def test_kerala_pensions_carry_a_malayalam_name_and_the_sourced_amount(kb):
    for scheme_id in KERALA_PENSIONS:
        scheme = kb[scheme_id]
        assert scheme.name_ml and scheme.value.amount == 2000 and scheme.value.per == "month"
        assert all("lsgkerala.gov.in" in source.url for source in scheme.sources)


def test_a_kerala_widow_is_counted_one_pension(kb, personas):
    eligible = personas["p006"].gold_eligible(kb)
    assert {"kl-widow-pension", "nsap-ignwps"} <= set(eligible)
    resolved = resolve(kb.active(), eligible)
    assert "kl-widow-pension" in resolved["take"] and "nsap-ignwps" not in resolved["take"]


def test_a_kerala_farm_worker_draws_one_of_three_pensions(kb, personas):
    eligible = set(personas["p007"].gold_eligible(kb))
    pensions = {"kl-agricultural-labour-pension", "kl-old-age-pension", "nsap-ignoaps"}
    assert pensions <= eligible
    taken = set(resolve(kb.active(), eligible)["take"]) & pensions
    assert len(taken) == 1 and taken <= {"kl-agricultural-labour-pension", "kl-old-age-pension"}


def test_kerala_documents_have_malayalam_labels_and_guides():
    from tn_schemematch.documents import default_documents
    vocab = default_documents()
    assert all(t.label_ml for t in vocab.types.values())
    assert vocab.guide("income_certificate", "KL")["state"] == "KL"
