"""Integrity of the released artifacts: the rule KB and the persona benchmark.

These are the tests that protect the benchmark's labels. Nothing here checks that a model
is good; they check that the ground truth is well-formed, so that when a model disagrees
with it, the model is the thing that was wrong.
"""

import pytest

from tn_schemematch import validate_kb
from tn_schemematch.elicitation import assert_monotone, necessary_questions
from tn_schemematch.personas import validate_personas
from tn_schemematch.rules import Verdict


# ---------------------------------------------------------------------- KB shape


def test_kb_loads_and_validates(kb):
    assert len(kb) > 0
    assert validate_kb(kb) == []


def test_every_scheme_cites_a_dated_source(kb):
    """Provenance is not optional: an uncited rule cannot be audited or refreshed."""
    for scheme in kb:
        assert scheme.sources, f"{scheme.id} has no sources"
        for source in scheme.sources:
            assert source.url.startswith("http"), f"{scheme.id}: bad source url"
            assert source.retrieved is not None, f"{scheme.id}: source has no retrieval date"


def test_state_schemes_constrain_state(kb):
    """Otherwise a persona from outside Tamil Nadu would match a TN-only scheme."""
    for scheme in kb:
        if scheme.level == "state":
            assert "state" in scheme.attributes, f"{scheme.id} never checks state"


def test_fully_specified_profile_settles_every_scheme(kb, personas):
    """No scheme may stay UNDETERMINED once everything is known, or its label is a guess."""
    for persona in personas:
        buckets = kb.active().match(persona.profile)
        assert buckets[Verdict.UNKNOWN] == [], (
            f"{persona.id} leaves {buckets[Verdict.UNKNOWN]} undetermined"
        )


def test_deprecated_schemes_are_excluded_from_ground_truth_but_kept_for_retrieval(kb):
    deprecated = kb.deprecated_ids()
    assert deprecated, "expect at least one discontinued scheme — recommending one is a real harm"
    for scheme_id in deprecated:
        assert scheme_id not in kb.active()
        assert scheme_id in kb  # still indexable, so a system can be caught returning it


def test_retrieval_text_contains_the_eligibility_wording(kb):
    """The baseline must see the real criteria; a straw-man baseline proves nothing."""
    for scheme in kb:
        assert scheme.eligibility_prose[:40] in scheme.retrieval_text()


# ------------------------------------------------------------------- persona set


def test_personas_load_and_validate(kb, personas):
    assert len(personas) > 0
    assert validate_personas(personas, kb) == []


def test_both_language_conditions_present(personas):
    for persona in personas:
        assert persona.queries["code_mixed"].strip()
        assert persona.queries["english"].strip()
        assert persona.queries["code_mixed"] != persona.queries["english"]


def test_stated_attributes_are_a_subset_of_the_profile(personas):
    for persona in personas:
        assert set(persona.stated_in_query) <= set(persona.profile)


def test_gold_sets_differ_across_personas(kb, personas):
    """A benchmark whose personas all have the same answer measures nothing."""
    gold = {tuple(v) for v in personas.gold(kb).values()}
    assert len(gold) > 1


def test_minimal_pair_differs_only_in_gender(personas):
    p003, p004 = personas["p003"], personas["p004"]
    differing = {
        k for k in set(p003.profile) | set(p004.profile)
        if p003.profile.get(k) != p004.profile.get(k)
    }
    assert differing == {"gender"}, f"p003/p004 differ in {differing}"
    assert p003.queries == p004.queries


def test_minimal_pair_differs_exactly_where_gender_is_read(kb, personas):
    """The categorical constraint must actually bite, or the pair tests nothing.

    On the ten-scheme KB the two gold sets were disjoint, and the test asserted that.
    They are not disjoint any more and should not be: a 41-scheme KB contains schemes
    that do not read gender at all — a bank-linked life cover, a contributory pension —
    and both students qualify for them. Disjointness was a property of a small KB, not of
    the minimal-pair design. What the design actually claims is narrower and still true:
    everything the two sets disagree about is a scheme whose rule reads gender, and
    nothing else moved.
    """
    gold_f = set(personas["p003"].gold_eligible(kb))
    gold_m = set(personas["p004"].gold_eligible(kb))
    assert gold_f and gold_m
    assert gold_f != gold_m
    assert "pudhumai-penn" in gold_f - gold_m
    assert "tamil-pudhalvan" in gold_m - gold_f
    for scheme_id in gold_f ^ gold_m:
        assert "gender" in kb[scheme_id].attributes, (
            f"{scheme_id} differs across the minimal pair but its rule never reads gender"
        )


def test_seed_personas_are_marked_unvalidated(personas):
    """Guards against seed data quietly ending up in a reported result."""
    for persona in personas:
        if persona.annotation.validated_by:
            continue
        assert "NOT YET NATIVELY VALIDATED" in persona.annotation.notes, (
            f"{persona.id} is unvalidated but does not say so"
        )


# ------------------------------------------------------------------ elicitation


def test_query_leaves_something_open(kb, sample_personas):
    """If a query already settled everything, it would not be underspecified."""
    for persona in sample_personas:
        ground = persona.elicitation_ground(kb)
        assert ground.undetermined_at_start, f"{persona.id}: query is not underspecified"
        assert ground.necessary, f"{persona.id}: nothing left worth asking"


def test_necessary_questions_shrink_as_answers_arrive(kb, personas):
    persona = personas["p001"]
    active = kb.active()
    known = dict(persona.known_profile())
    before = necessary_questions(active, known)
    known["gender"] = persona.profile["gender"]
    known.update(kb.spec.derive(known))
    after = necessary_questions(active, known)
    assert after < before


def test_settled_verdicts_never_flip(kb, sample_personas):
    """The monotonicity property the elicitation search depends on."""
    active = kb.active()
    for persona in sample_personas:
        known = dict(persona.known_profile())
        known.update(kb.spec.derive(known))
        order = [a for a in kb.spec.elicitable_names() if a not in known]
        assert_monotone(active, known, order, persona.profile)


def test_minimal_confirming_set_is_sufficient(kb, sample_personas):
    """Answering exactly the minimal set must reproduce the gold answer."""
    active = kb.active()
    for persona in sample_personas:
        ground = persona.elicitation_ground(kb)
        profile = dict(persona.known_profile())
        for attr in ground.minimal_confirming:
            profile[attr] = persona.profile[attr]
        profile.update(kb.spec.derive(profile))
        assert active.eligible_ids(profile) == persona.gold_eligible(kb), (
            f"{persona.id}: minimal set {ground.minimal_confirming} did not reproduce the answer"
        )


def test_minimal_confirming_set_is_smaller_than_exhaustive(kb, sample_personas):
    """Most of an exhaustive interview is spent ruling schemes out, not in."""
    for persona in sample_personas:
        ground = persona.elicitation_ground(kb)
        assert ground.minimal_n_questions <= ground.oracle_n_questions


def test_oracle_sequence_settles_everything_settleable(kb, sample_personas):
    active = kb.active()
    for persona in sample_personas:
        ground = persona.elicitation_ground(kb)
        profile = dict(persona.known_profile())
        for attr in ground.oracle_sequence:
            profile[attr] = persona.profile[attr]
        profile.update(kb.spec.derive(profile))
        assert active.match(profile)[Verdict.UNKNOWN] == []


def test_necessary_questions_exclude_derived_attributes(kb, sample_personas):
    for persona in sample_personas:
        ground = persona.elicitation_ground(kb)
        for attr in ground.necessary:
            assert kb.spec[attr].elicitable
