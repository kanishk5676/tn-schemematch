"""Benefit amounts and schemes that cannot be taken together."""

import pytest

from tn_schemematch.benefits import resolve, totals, value_text
from tn_schemematch.kb import KBError, figure_in_text, indian_grouping, load_scheme


def test_every_amount_is_quoted_from_the_sourced_prose(kb):
    """validate_kb enforces it; this pins that the shipped KB passes."""
    for scheme in kb:
        figures = []
        if scheme.value:
            figures += [scheme.value.amount] + ([scheme.value.max] if scheme.value.max else [])
        if scheme.cover:
            figures.append(scheme.cover)
        for figure in figures:
            assert figure_in_text(figure, scheme.benefit_prose), (scheme.id, figure)


def test_figures_are_matched_as_whole_numbers():
    assert figure_in_text(1000, "Rs 1,000 per month")
    assert figure_in_text(500000, "Rs 5 lakh per family")
    assert figure_in_text(350000, "Rs 3.50 lakh per house")
    assert figure_in_text(500000, "Up to Rs 5,00,000 per family")
    assert not figure_in_text(1000, "Rs 11,000")
    assert not figure_in_text(600, "Rs 6,000")


def test_indian_grouping():
    assert indian_grouping(500000) == "5,00,000"
    assert indian_grouping(12345678) == "1,23,45,678"
    assert indian_grouping(999) == "999"


def test_exclusions_are_symmetric(kb):
    exclusions = kb.exclusions()
    for a, others in exclusions.items():
        for b in others:
            assert a in exclusions[b], (a, b)


def test_a_bad_value_block_is_refused(tmp_path, spec):
    path = tmp_path / "x.yaml"
    path.write_text(
        "id: x\nname: X\nlevel: central\neligibility_prose: p\n"
        "eligibility: {attr: age, op: gte, value: 18}\nvalue: {amount: 100, per: fortnight}\n")
    with pytest.raises(KBError, match="value.per"):
        load_scheme(path, spec)


def test_the_same_pension_is_counted_once(kb):
    """IGNOAPS and the Tamil Nadu old-age pension are one pension; keep the larger."""
    resolved = resolve(kb, ["nsap-ignoaps", "tn-old-age-pension", "pmjjby"])
    assert resolved["take"] == ["pmjjby", "tn-old-age-pension"]
    group = resolved["groups"][0]
    assert group["drop"] == ["nsap-ignoaps"]
    assert group["reasons"]


def test_a_tie_goes_to_the_state_scheme(kb):
    """CMCHIS and PM-JAY both cover Rs 5 lakh; Tamil Nadu delivers PM-JAY as CMCHIS."""
    assert resolve(kb, ["pmjay", "cmchis"])["take"] == ["cmchis"]


def test_compatible_schemes_inside_a_group_are_both_kept(kb):
    """The refugee pension excludes both the deserted-wives and the unmarried pension, but
    those two do not exclude each other. One group, and the best choice keeps two."""
    resolved = resolve(kb, ["tn-srilankan-refugee-pension", "tn-deserted-wives-pension",
                            "tn-unmarried-women-pension"])
    assert len(resolved["groups"]) == 1
    assert resolved["take"] == ["tn-deserted-wives-pension", "tn-unmarried-women-pension"]
    assert resolved["groups"][0]["drop"] == ["tn-srilankan-refugee-pension"]


def test_totals_separate_monthly_one_time_and_cover(kb):
    money = totals(kb, ["tn-old-age-pension", "pm-kisan", "mrmbs", "cmchis",
                        "kalaignar-kanavu-illam"])
    assert money["yearly"] == 12000 + 6000
    assert money["one_time"] == 18000
    assert money["in_kind"] == 350000
    assert money["best_cover"] == 500000


def test_a_per_family_scheme_is_counted_once_per_household(kb):
    shared: set[str] = set()
    first = totals(kb, ["pm-kisan"], family_counted=shared)
    second = totals(kb, ["pm-kisan"], family_counted=shared)
    assert first["yearly"] == 6000
    assert second["yearly"] == 0
    assert second["shared_with_family"] == ["pm-kisan"]


def test_value_text(kb):
    assert value_text(kb["tn-old-age-pension"]) == "₹1,000 a month"
    assert value_text(kb["pm-kisan"]) == "₹6,000 a year per family"
    assert value_text(kb["evr-maniammaiyar-marriage"]) == "₹25,000–50,000 once"
    assert value_text(kb["cmchis"]) == "cover of ₹5,00,000"
    assert value_text(kb["kgbv"]) == ""
