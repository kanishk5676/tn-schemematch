"""End-to-end harness tests, using scripted model responses so nothing depends on a key."""

import json

import pytest

from tn_schemematch.eval.runner import rq2_report, run_experiment, score_results, summarize
from tn_schemematch.systems.base import ScriptedClient, SimulatedCitizen, parse_json_response
from tn_schemematch.systems.grounding import GroundingPipeline, OracleExtractionPipeline
from tn_schemematch.systems.rag_baseline import RAGBaseline
from tn_schemematch.systems.retrieval import BM25Retriever, OracleRetriever, recall_at_k


# ------------------------------------------------------------------- retrieval


def test_bm25_finds_the_obviously_relevant_scheme(kb):
    retriever = BM25Retriever(kb)
    top = retriever.retrieve("widow pension for destitute women in Tamil Nadu", k=3)
    assert "tn-widow-pension" in top


def test_oracle_retriever_has_perfect_recall(kb, personas):
    """Recall is undefined, not perfect, for a persona who qualifies for nothing.

    The benchmark deliberately contains such personas — "nothing here fits you" is a
    correct and useful answer — and ``recall_at_k`` returns None for them rather than
    dividing by zero. Asserting 1.0 across the whole set would have quietly required that
    no such persona exist.
    """
    retriever = OracleRetriever(kb)
    scored = 0
    for persona in personas:
        gold = persona.gold_eligible(kb)
        recall = recall_at_k(retriever.retrieve(persona.query("english")), gold)
        if recall is None:
            assert gold == []
            continue
        assert recall == 1.0
        scored += 1
    assert scored > 0


def test_lexical_retrieval_is_not_language_neutral(kb, personas):
    """Documented confound for RQ2: BM25 sees fewer English content words in the code-mixed
    variant, so some of any observed gap is retrieval, not reasoning. Measured, not assumed."""
    retriever = BM25Retriever(kb)
    measured = 0
    for persona in personas:
        gold = persona.gold_eligible(kb)
        if not gold:
            continue  # recall over an empty gold set is undefined, not zero
        for condition in ("code_mixed", "english"):
            recall = recall_at_k(retriever.retrieve(persona.query(condition), k=5), gold)
            assert recall is not None  # the number itself is a finding, not a pass/fail
            measured += 1
    assert measured > 0


# ------------------------------------------------------------ simulated citizen


def test_citizen_answers_only_what_is_asked(kb, personas):
    persona = personas["p001"]
    citizen = SimulatedCitizen(persona, kb.spec)
    reply, value = citizen.answer("gender")
    assert value == "male"
    assert citizen.asked == ["gender"]
    assert "male" in reply


def test_citizen_refuses_derived_attributes(kb, personas):
    citizen = SimulatedCitizen(personas["p001"], kb.spec)
    _, value = citizen.answer("farmer_category")
    assert value is None


def test_citizen_verbalizes_rather_than_dumping_json(kb, personas):
    citizen = SimulatedCitizen(personas["p001"], kb.spec)
    reply, _ = citizen.answer("annual_family_income")
    assert reply == "90000 rupees a year."


def test_citizen_question_budget_is_enforced(kb, personas):
    citizen = SimulatedCitizen(personas["p001"], kb.spec, max_questions=2)
    citizen.answer("age")
    citizen.answer("gender")
    assert citizen.exhausted


# ------------------------------------------------------------ grounding pipeline


def test_grounding_pipeline_reaches_the_gold_answer(kb, personas, sample_personas):
    """With correct extraction and enough questions, the rules must reproduce ground truth.

    This is the property that makes the pipeline worth proposing: its ceiling is the KB,
    not the model's reasoning.
    """
    system = OracleExtractionPipeline(kb, max_questions=40)
    for persona in sample_personas:
        result = system.run(persona, "code_mixed", kb)
        assert result.returned == persona.gold_eligible(kb), (
            f"{persona.id}: got {result.returned}, expected {persona.gold_eligible(kb)}"
        )


def test_default_question_budget_and_batch_size_are_sufficient(kb, personas, sample_personas):
    """Regression guard on the shipped defaults, not just on generous settings.

    This test is why the default budget is 40 and not 20. Twenty sufficed on the
    ten-scheme KB and silently truncated the interview at 41 schemes, dropping schemes
    personas genuinely qualified for — a failure that looks like a recall problem in the
    results table and is really a budget problem in the harness.
    """
    system = OracleExtractionPipeline(kb)
    for persona in sample_personas:
        result = system.run(persona, "english", kb)
        assert result.returned == persona.gold_eligible(kb), (
            f"{persona.id} unresolved at the default budget of {system.max_questions}"
        )


def test_batching_questions_costs_accuracy_under_a_budget(kb, personas):
    """Documents why ask_batch_size defaults to 1.

    Asking several questions before re-ranking wastes the ones that a prior answer would
    have made unnecessary. Under a fixed budget that waste is not free — it drops a scheme
    the citizen genuinely qualified for. Recorded as a test so the default is not
    'optimized' back for latency without someone seeing the cost.

    The persona and budget that expose the effect moved when the KB grew from 10 schemes
    to 41: at 10 schemes it was p002 at a budget of 15, and it is now p001 at 26. The
    *effect* is unchanged — batches of three spend two or three questions that a prior
    answer would have made unnecessary, and the cost lands on whichever persona is closest
    to the budget. That the witness moves with KB size is why this is written as a search
    over one named persona rather than a claim about all of them.
    """
    persona = personas["p001"]
    one_at_a_time = OracleExtractionPipeline(kb, max_questions=26, ask_batch_size=1)
    batched = OracleExtractionPipeline(kb, max_questions=26, ask_batch_size=3)

    assert one_at_a_time.run(persona, "english", kb).returned == persona.gold_eligible(kb)
    assert batched.run(persona, "english", kb).returned != persona.gold_eligible(kb)


def test_grounding_normalizes_code_mixed_extractions(kb, personas):
    """The extractor may return surface forms; canonicalization happens downstream."""
    client = ScriptedClient(default=json.dumps({
        "occupation": "விவசாயி",
        "land_owned_acres": "2 ekkar",
        "ration_card_type": "ration card irukku",
    }))
    result = GroundingPipeline(client, kb, max_questions=40).run(personas["p001"], "code_mixed", kb)
    assert result.extracted_profile["occupation"] == "farmer"
    assert result.extracted_profile["land_owned_acres"] == pytest.approx(2.0)
    assert result.extracted_profile["ration_card_type"] == "phh_rice"
    assert result.returned == personas["p001"].gold_eligible(kb)


def test_unparseable_extraction_is_dropped_not_guessed(kb, personas):
    """An unreadable value must leave the attribute unknown, so the citizen gets asked."""
    client = ScriptedClient(default=json.dumps({"annual_family_income": "no idea really"}))
    result = GroundingPipeline(client, kb, max_questions=40).run(personas["p002"], "english", kb)
    assert "unnormalizable" in json.dumps(result.transcript)
    assert result.returned == personas["p002"].gold_eligible(kb)


def test_hallucinated_attribute_names_are_ignored(kb, personas):
    client = ScriptedClient(default=json.dumps({"is_deserving": True, "vibe": "rural"}))
    result = GroundingPipeline(client, kb, max_questions=40).run(personas["p001"], "english", kb)
    assert not result.error
    assert "is_deserving" not in result.extracted_profile


def test_broken_json_is_recorded_as_an_error_not_repaired(kb, personas):
    client = ScriptedClient(default="I'm afraid I can't help with that.")
    result = GroundingPipeline(client, kb).run(personas["p001"], "english", kb)
    assert result.failed
    assert result.returned == []


def test_grounding_never_asks_a_pointless_question(kb, personas, sample_personas):
    """Every question it asks must have been able to change some verdict when asked."""
    from tn_schemematch.elicitation import necessary_questions

    system = OracleExtractionPipeline(kb, max_questions=40)
    active = kb.active()
    for persona in sample_personas:
        result = system.run(persona, "english", kb)
        allowed = necessary_questions(active, {
            **persona.known_profile(),
            **kb.spec.derive(dict(persona.known_profile())),
        })
        assert set(result.questions_asked) <= allowed


# ---------------------------------------------------------------- RAG baseline


def test_rag_baseline_returns_what_the_model_says(kb, personas):
    client = ScriptedClient(default=json.dumps({
        "questions": [], "eligible_schemes": ["pm-kisan", "cmchis"], "reasoning": "..."
    }))
    result = RAGBaseline(client, kb).run(personas["p001"], "code_mixed", kb)
    assert result.returned == ["cmchis", "pm-kisan"]
    assert result.retrieved


def test_rag_baseline_over_returning_is_caught_as_false_positives(kb, personas):
    """The failure mode the benchmark exists to measure: plausible, topical, wrong."""
    client = ScriptedClient(default=json.dumps({
        "questions": [], "eligible_schemes": ["pm-kisan", "cmchis", "kmut", "tn-widow-pension"]
    }))
    results = [RAGBaseline(client, kb).run(personas["p001"], c, kb) for c in ("code_mixed", "english")]
    scores = score_results(results, personas, kb)
    assert all(s.fpr == 0.5 for s in scores)
    assert all("kmut" in s.false_positives for s in scores)


def test_recommending_a_discontinued_scheme_is_flagged_as_harmful(kb, personas):
    client = ScriptedClient(default=json.dumps({
        "questions": [], "eligible_schemes": ["pudhumai-penn", "moovalur-marriage-assistance"]
    }))
    result = RAGBaseline(client, kb).run(personas["p003"], "english", kb)
    scores = score_results([result], personas, kb)
    assert scores[0].harmful_fpr == 0.5


def test_rag_baseline_elicitation_loop_runs(kb, personas):
    client = ScriptedClient(
        responses={"ANSWERS THE CITIZEN HAS ALREADY GIVEN": json.dumps(
            {"questions": [], "eligible_schemes": ["pudhumai-penn"]}
        )},
        default=json.dumps({"questions": ["gender", "state"], "eligible_schemes": []}),
    )
    result = RAGBaseline(client, kb).run(personas["p003"], "code_mixed", kb)
    assert result.questions_asked == ["gender", "state"]
    assert result.returned == ["pudhumai-penn"]


def test_invented_scheme_names_are_reported_not_silently_dropped(kb, personas):
    client = ScriptedClient(default=json.dumps({
        "questions": [], "eligible_schemes": ["pm-kisan", "Amma Universal Prosperity Scheme"]
    }))
    result = RAGBaseline(client, kb).run(personas["p001"], "english", kb)
    assert result.returned == ["pm-kisan"]
    assert "unrecognised scheme names" in json.dumps(result.transcript)


# ---------------------------------------------------------------- full pipeline


def test_experiment_runs_and_scores_end_to_end(kb, sample_personas):
    """End-to-end shape check, on a slice: the full sweep belongs in scripts/pilot.py."""
    personas = sample_personas
    client = ScriptedClient(default=json.dumps({"questions": [], "eligible_schemes": ["cmchis"]}))
    systems = [RAGBaseline(client, kb), OracleExtractionPipeline(kb, max_questions=40)]
    results = run_experiment(systems, personas, kb)
    assert len(results) == len(systems) * len(personas) * 2

    scores = score_results(results, personas, kb)
    summary = summarize(scores)
    assert len(summary) == len(systems) * 2

    grounded = [s for s in scores if s.system.startswith("grounding")]
    assert all(s.exact_match for s in grounded)

    report = rq2_report(scores, n_boot=200)
    assert set(report) == {s.name for s in systems}


def test_rq2_report_shape(kb, sample_personas):
    """A system that degrades under code-mixing must show up as a negative delta."""
    good = json.dumps({"questions": [], "eligible_schemes": ["cmchis", "pm-kisan"]})
    bad = json.dumps({"questions": [], "eligible_schemes": []})
    client = ScriptedClient(responses={}, default=good)
    results = []
    for persona in sample_personas:
        for condition in ("code_mixed", "english"):
            client.default = bad if condition == "code_mixed" else good
            results.append(RAGBaseline(client, kb).run(persona, condition, kb))
    scores = score_results(results, sample_personas, kb)
    rows = next(iter(rq2_report(scores, metrics=("recall",), n_boot=500).values()))
    assert rows[0]["metric"] == "recall"
    assert rows[0]["delta"] < 0


# ------------------------------------------------------------------- utilities


@pytest.mark.parametrize(
    "raw", ['{"a": 1}', '```json\n{"a": 1}\n```', 'Here you go:\n{"a": 1}']
)
def test_json_extraction_tolerates_common_wrappers(raw):
    assert parse_json_response(raw) == {"a": 1}


def test_json_extraction_fails_loudly_on_prose():
    with pytest.raises(Exception):
        parse_json_response("I cannot answer that question.")
