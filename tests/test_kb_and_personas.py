"""Integrity of the released artifacts: the rule KB and the persona benchmark.

These are the tests that protect the benchmark's labels. Nothing here checks that a model
is good; they check that the ground truth is well-formed, so that when a model disagrees
with it, the model is the thing that was wrong.
"""

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest

from tn_schemematch import validate_kb
from tn_schemematch.elicitation import assert_monotone, necessary_questions
from tn_schemematch.kb import STALE_AFTER_DAYS, SchemeKB, stale_schemes
from tn_schemematch.personas import validate_personas

REPO_ROOT = Path(__file__).resolve().parent.parent
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
        assert scheme_id in kb  # still loaded, so the assistant can say it has closed


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


# --------------------------------------------------------------- expansion tripwires
#
# These three cost almost nothing and all pass today. They exist because the KB is about
# to triple, and each guards a failure that is otherwise silent or reported far from its
# cause.


def test_every_persona_sets_every_non_derived_attribute(spec, personas):
    """The front-line back-fill guard.

    Adding an attribute to the vocabulary obliges every persona to carry it, or its gold
    label becomes a guess. Today that only surfaces via the settle test, and only once
    some rule actually reads the attribute — which can be several batches after the
    omission, with an error message about the *scheme* rather than the persona. This
    fails immediately, on declaration, and names the personas.
    """
    expected = {name for name, attr in spec.attributes.items() if not attr.is_derived}
    for persona in personas:
        missing = expected - set(persona.profile)
        assert not missing, f"{persona.id} does not set {sorted(missing)}"


def test_base_profile_covers_the_vocabulary(spec):
    """The persona generator must know about every attribute the spec declares.

    If it does not, every generated candidate is rejected for leaving schemes
    undetermined, the run writes fewer personas than asked for, and the retire step then
    deletes the ones it failed to replace. The benchmark shrinks and the suite stays
    green, because a smaller benchmark is still a consistent one.
    """
    import random
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    from generate_personas import base_profile

    expected = {name for name, attr in spec.attributes.items() if not attr.is_derived}
    actual = set(base_profile(random.Random(0)))
    assert actual == expected, (
        f"generator misses {sorted(expected - actual)}; "
        f"generator invents {sorted(actual - expected)}"
    )


# Three files predate the filename==id convention. Renaming them would invalidate every
# data/runs artifact, both hardcoded-id tests and the docs, for cosmetic gain — so they are
# pinned here instead, and the set is closed: it may shrink, never grow.
LEGACY_FILENAME_MISMATCHES = frozenset({"kmut", "mrmbs", "tn-widow-pension"})


def test_scheme_filename_matches_its_id(kb):
    """`id` comes from inside the file, so a filename can drift from it unnoticed.

    At 42 schemes that is a curiosity. At 110, hunting for the file that defines a
    scheme id becomes routine, and three exceptions become thirty.
    """
    for scheme in kb:
        if scheme.id in LEGACY_FILENAME_MISMATCHES:
            continue
        assert scheme.source_file.stem == scheme.id, (
            f"{scheme.source_file.name} declares id {scheme.id!r}"
        )


# ------------------------------------------------------------- multi-jurisdiction KB
#
# The KB is national while the persona benchmark is Tamil Nadu only. That makes these
# checks structural by necessity: they are properties of the rules, so they hold for
# states no persona lives in.


def test_state_schemes_are_refuted_outside_their_jurisdiction(kb):
    """A state scheme must reject a resident of every other state in the vocabulary.

    The failure this guards is a Karnataka file copied from a Tamil Nadu one that still
    tests `state == TN`. Nothing else catches it: the rule *does* constrain `state`, no
    persona lives in Karnataka so no gold label moves, and the gold-set diff is clean.
    The scheme is simply unreachable, permanently, and silently.
    """
    from tn_schemematch.kb import _check_jurisdiction_scoping, _saturated_profile

    problems = _check_jurisdiction_scoping(kb, _saturated_profile(kb.spec))
    assert problems == [], "\n".join(problems)


def test_every_state_scheme_declares_a_jurisdiction(kb):
    for scheme in kb:
        if scheme.level == "state":
            assert scheme.jurisdiction, f"{scheme.id} is a state scheme with no jurisdiction"
        else:
            assert not scheme.jurisdiction, f"{scheme.id} is central but claims a jurisdiction"


def test_state_domain_matches_the_scheme_tree(kb, spec):
    """Every state in the vocabulary has schemes, and every scheme directory has a code.

    Keeps the domain from advertising coverage that does not exist. It is also what makes
    dropping a state clean: remove its directory and its code in one commit, and this
    stays green.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "kb" / "schemes"
    directories = {d.name.upper() for d in root.iterdir()
                   if d.is_dir() and d.name != "central"}
    codes = {c for c in (spec["state"].domain or ()) if c != "other"}
    assert directories == codes, (
        f"in the domain but with no schemes: {sorted(codes - directories)}; "
        f"on disk but not in the domain: {sorted(directories - codes)}"
    )


def test_state_aliases_do_not_collide(spec):
    """`canonicalize` substring-matches aliases longer than two characters.

    So one state's alias being a substring of another's resolves to the wrong state,
    silently. This is not hypothetical: "bengal" (West Bengal) is a substring of
    "bengaluru", so an alias like "bengaluru state" for Karnataka would canonicalize to
    West Bengal.
    """
    from tn_schemematch.attributes import _fold

    forms = [(code, _fold(f)) for code, fs in spec["state"].aliases.items() for f in fs]
    for code_a, form_a in forms:
        if len(form_a) <= 2:
            continue
        for code_b, form_b in forms:
            if code_a == code_b or len(form_b) <= 2:
                continue
            assert form_a not in form_b, (
                f"alias {form_a!r} ({code_a}) is a substring of {form_b!r} ({code_b}); "
                f"{form_b!r} would canonicalize to {code_a}"
            )


def test_enum_probing_is_equivalent_to_probing_the_whole_domain(kb):
    """The enum reduction in `candidate_values` must be exact, not merely cheaper.

    Enums admit only eq/ne/in/not_in, so values no predicate names are indistinguishable
    to the rule. If that reasoning is ever wrong — a new operator, a rule reaching an enum
    some other way — pivotality starts silently missing questions, and the interview stops
    asking things it needs.
    """
    from tn_schemematch.elicitation import candidate_values

    for scheme in kb:
        for attr in scheme.attributes:
            if kb.spec[attr].type != "enum":
                continue
            reduced = {scheme.eligibility.evaluate({attr: v}).verdict
                       for v in candidate_values(scheme.eligibility, attr, kb.spec)}
            full = {scheme.eligibility.evaluate({attr: v}).verdict
                    for v in kb.spec[attr].values()}
            assert reduced == full, f"{scheme.id}/{attr}: {reduced} != {full}"


def test_oracle_sequence_is_not_capped_below_the_vocabulary(kb, personas):
    """A pinned oracle cap truncates silently once the KB outgrows it.

    `oracle_n_questions` then saturates at the cap, and it is the denominator of the
    reported question-overhead ratio — so the number stays plausible while becoming
    wrong. Assert real headroom instead of trusting the constant.
    """
    budget = len(kb.spec.elicitable_names())
    worst = max(len(p.elicitation_ground(kb).oracle_sequence) for p in personas)
    assert worst < budget, (
        f"the longest oracle sequence is {worst} questions against a vocabulary of "
        f"{budget} elicitable attributes — the sequence is at risk of truncation"
    )


# The date this repository started recording its fetches. Sources retrieved before it
# predate the log and are exempt; everything after must be traceable to a row in it.
FETCH_ERA = date(2026, 9, 8)


def test_sources_from_the_fetch_era_have_a_retrieval_record(kb):
    """Make "cited" checkable.

    `test_every_scheme_cites_a_dated_source` can only assert that a URL is a string
    starting with http, which a citation invented from memory satisfies just as well as
    one that was read. This asserts the URL also appears in docs/retrieval-log.md, so a
    scheme cannot enter the KB carrying a source nobody fetched.
    """
    log = (REPO_ROOT / "docs" / "retrieval-log.md").read_text(encoding="utf-8")
    for scheme in kb:
        for source in scheme.sources:
            if source.retrieved < FETCH_ERA:
                continue
            assert source.url in log, (
                f"{scheme.id} cites {source.url} dated {source.retrieved}, but that URL "
                f"has no row in docs/retrieval-log.md"
            )


def test_no_source_is_dated_in_the_future(kb):
    today = date.today()
    for scheme in kb:
        for source in scheme.sources:
            assert source.retrieved <= today, (
                f"{scheme.id} cites {source.url} as retrieved on {source.retrieved}"
            )


# ------------------------------------------------------------------- staleness


STALE_TODAY = date(2027, 6, 1)


def _last_read(kb, scheme, retrieved, **changes):
    """A one-scheme KB whose only source was read on ``retrieved``."""
    source = replace(scheme.sources[0], retrieved=retrieved)
    return SchemeKB({scheme.id: replace(scheme, sources=(source,), **changes)}, kb.spec)


def test_a_scheme_goes_stale_the_day_after_its_source_ages_out(kb):
    scheme = next(iter(kb.active()))
    edge = STALE_TODAY - timedelta(days=STALE_AFTER_DAYS)
    assert stale_schemes(_last_read(kb, scheme, edge), today=STALE_TODAY) == []
    [warning] = stale_schemes(_last_read(kb, scheme, edge - timedelta(days=1)),
                              today=STALE_TODAY)
    assert warning.startswith(f"{scheme.id}: last checked")


def test_a_recent_verification_resets_the_age(kb):
    scheme = next(iter(kb.active()))
    verified = _last_read(kb, scheme, date(2026, 1, 1), status="verified",
                          verified_on=STALE_TODAY - timedelta(days=10))
    assert stale_schemes(verified, today=STALE_TODAY) == []


def test_deprecated_schemes_are_never_stale(kb):
    scheme = kb[kb.deprecated_ids()[0]]
    assert stale_schemes(_last_read(kb, scheme, date(2020, 1, 1)), today=STALE_TODAY) == []


def test_stale_sources_warn_without_failing_validate(capsys):
    """CI runs `schemematch validate`; an ageing source must not turn it red."""
    from tn_schemematch.cli import main
    assert main(["validate", "--max-age-days", "0"]) == 0
    out = capsys.readouterr().out
    assert "warning(s), no source checked in 0 days" in out
    assert "All checks passed." in out


# ------------------------------------------------------------- plain language


def test_plain_text_loads_and_falls_back(kb):
    """Plain words are optional; a scheme without them still has a name to say."""
    with_plain = [s for s in kb if s.has_plain]
    without = [s for s in kb if not s.has_plain]
    assert with_plain and without
    for scheme in with_plain:
        for lang in ("ta", "en"):
            assert scheme.plain_text(lang, "name") and scheme.plain_text(lang, "what")
    bare = without[0]
    assert bare.plain_text("ta", "name") == (bare.name_ta or bare.name)
    assert bare.plain_text("en", "what") == (bare.summary or bare.benefit_prose)
    assert bare.plain_text("ta", "where") == ""


def test_plain_text_is_unreviewed_until_a_person_checks_it(kb):
    assert not any(s.plain_reviewed for s in kb), (
        "plain text marked reviewed: say who checked it in docs/verification-log.md")


@pytest.mark.parametrize("block,problem", [
    ({"fr": {"name": "x"}}, "unknown language"),
    ({"ta": {"wher": "x"}}, "unknown field"),
    ({"reviewed": "yes"}, "true or false"),
])
def test_malformed_plain_blocks_are_rejected(tmp_path, spec, block, problem):
    import yaml

    from tn_schemematch.kb import KBError, load_scheme
    raw = yaml.safe_load(Path("kb/schemes/central/pm-kisan.yaml").read_text(encoding="utf-8"))
    raw["plain"] = block
    path = tmp_path / "broken.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(KBError, match=problem):
        load_scheme(path, spec)


def test_the_most_common_schemes_have_plain_tamil(kb):
    common = ["tn-old-age-pension", "tn-widow-pension", "kmut", "pm-kisan", "cmchis",
              "pmjay", "mgnrega", "pmfby", "pudhumai-penn", "pmmvy", "mrmbs"]
    for scheme_id in common:
        assert (kb[scheme_id].plain.get("ta") or {}).get("what"), scheme_id
