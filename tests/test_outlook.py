"""Looking ahead: actions that unlock schemes, schemes that come with age, the family."""

import pytest

from tn_schemematch.benefits import totals
from tn_schemematch.outlook import coming_up, household, unlock
from tn_schemematch.rules import Verdict

pytest.importorskip("flask")

from tn_schemematch.vault import Vault  # noqa: E402
from tn_schemematch.web import create_app  # noqa: E402


@pytest.fixture
def active(kb):
    return kb.active()


def changed(spec, profile, **changes):
    base = {k: v for k, v in profile.items() if not spec[k].is_derived}
    base.update(changes)
    base.update(spec.derive(base))
    return base


def test_an_action_is_offered_only_when_it_makes_someone_eligible(active, spec, personas):
    profile = changed(spec, personas["p001"].profile, has_bank_account=False)
    result = unlock(active, spec, profile)
    bank = next(a for a in result["actions"] if a["attr"] == "has_bank_account")
    assert bank["text"] == "Open a bank account"
    after = active.match(changed(spec, profile, has_bank_account=True))[Verdict.TRUE]
    assert {s["id"] for s in bank["schemes"]} <= set(after)
    assert not {s["id"] for s in bank["schemes"]} & set(active.match(profile)[Verdict.TRUE])


def test_an_action_respects_who_it_is_for(active, spec, personas):
    """The fisheries relief tests cooperative membership, not occupation, so without
    ``only_if`` a farmer would be told to join a fishermen's society."""
    farmer = changed(spec, personas["p001"].profile, occupation="farmer",
                     is_member_of_fishermen_cooperative=False)
    fisher = changed(spec, farmer, occupation="fisher")
    assert not any(a["attr"] == "is_member_of_fishermen_cooperative"
                   for a in unlock(active, spec, farmer)["actions"])
    assert any(a["attr"] == "is_member_of_fishermen_cooperative"
               for a in unlock(active, spec, fisher)["actions"])


def test_questions_name_the_unknown_facts_that_hold_schemes_back(active, spec):
    result = unlock(active, spec, {"gender": "female"})
    attrs = [q["attr"] for q in result["questions"]]
    assert "state" in attrs and "age" in attrs
    assert all(q["n_schemes"] > 0 for q in result["questions"])


def test_the_old_age_pension_comes_at_sixty(active, spec, personas):
    profile = changed(spec, personas["p002"].profile, age=57, marital_status="married",
                      is_destitute=True, fixed_assets_value=0, receives_other_pension=False)
    events = coming_up(active, spec, profile)
    at_sixty = next(e for e in events if e["age"] == 60)
    assert at_sixty["in_years"] == 3
    assert "tn-old-age-pension" in {s["id"] for s in at_sixty["gains"]}


def test_coming_up_also_reports_what_is_lost(active, spec, personas):
    """PMJJBY enrols up to 50; the farmer persona at 45 loses it within the decade."""
    events = coming_up(active, spec, personas["p001"].profile)
    lost = {s["id"] for e in events for s in e["loses"]}
    assert "pmjjby" in lost


def test_without_an_age_nothing_is_predicted(active, spec):
    assert coming_up(active, spec, {"gender": "female", "state": "TN"}) == []


def test_a_household_counts_a_per_family_scheme_once(kb, spec, personas, tmp_path):
    vault = Vault(tmp_path / "vault", spec)
    farmer = personas["p001"].profile
    facts = [(a, v, "form", "") for a, v in farmer.items()
             if a in spec.elicitable_names() and v is not None]
    first = vault.create_profile("Murugan")["id"]
    second = vault.create_profile("Selvi", household=first, relation="wife")["id"]
    vault.record_many(first, facts)
    vault.record_many(second, facts)
    result = household(kb.active(), vault, second)
    assert [m["name"] for m in result["members"]] == ["Murugan", "Selvi"]
    eligible = {s["id"] for s in result["members"][0]["eligible"]}
    assert "pm-kisan" in eligible
    assert "Pradhan Mantri Kisan Samman Nidhi (PM-KISAN)" in result["members"][1]["shared_with_family"]
    # Same facts, same schemes: twice one person's money, less the per-family ones once.
    alone = totals(kb.active(), eligible)
    per_family = sum(kb[i].value.yearly or 0 for i in alone["counted"]
                     if kb[i].value and kb[i].value.per_family)
    assert result["total"]["yearly"] == 2 * alone["yearly"] - per_family
    vault.close()


def test_planning_routes(kb, spec, personas, tmp_path):
    http = create_app(kb=kb, spec=spec, client=None, vault_dir=tmp_path / "vault").test_client()
    pid = http.post("/api/profiles", json={"name": "Lakshmi"}).get_json()["id"]
    http.post(f"/api/profiles/{pid}/facts", json={"attr": "age", "value": 58})
    assert http.get(f"/api/profiles/{pid}/coming-up").get_json()["age_known"] is True
    assert "questions" in http.get(f"/api/profiles/{pid}/unlock").get_json()
    family = http.get(f"/api/profiles/{pid}/household").get_json()
    assert family["members"][0]["id"] == pid
    assert http.get("/api/profiles/nobody/household").status_code == 404
