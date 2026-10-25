# Eligibility Matching for Indian Welfare Schemes under Code-Mixed Tamil–English Queries

*A benchmark and structured-grounding approach for high-stakes citizen scheme navigation.*

**Working title:** TN-SchemeMatch  **Status:** Research proposal (draft v1)
**Scope:** 5-week build; targeting an Indic-NLP / NLP-for-social-good / public-sector-AI workshop

---

## 1. Summary

Millions of eligible Indian citizens never claim welfare benefits they qualify for, in
part because discovering which schemes apply requires reconciling an underspecified
personal situation against dozens of schemes whose rules involve income thresholds,
land-size caps, category constraints, age bands, and district scoping. This is an
eligibility-matching problem, not a retrieval problem: knowing "PM-KISAN exists" is easy;
deciding "this specific person qualifies" is where the difficulty — and the real-world
harm — lives.

This project builds a small, hand-verified benchmark and evaluates whether current LLM
agents can perform eligibility matching over structured rules, and critically, whether
their accuracy and false-positive behaviour degrade when citizens ask in code-mixed
Tamil–English rather than clean English. We contribute (a) a structured, machine-readable
eligibility-rule knowledge base of ~40–60 Tamil Nadu and central schemes; (b) ~150–300
code-mixed citizen-persona queries with natively validated ground-truth eligible sets; and
(c) an evaluation of a structured eligibility-grounding pipeline against a plain
RAG-over-scheme-text baseline. The headline metric is the false-positive rate — telling a
citizen they qualify when they do not — because that is the failure mode with genuine
downstream cost.

## 2. Motivation and problem statement

A citizen types something like: *"enakku ration card irukku, farmer, 2 acre land — enna
scheme kedaikum?"* ("I have a ration card, I'm a farmer with 2 acres of land — which
schemes can I get?"). The query is underspecified (no income, age, category, or district),
code-mixed (Tamil grammar, Romanised script, English lexical items), and high-stakes (a
wrong answer either denies a benefit or sends someone to a district office for a scheme
they cannot receive).

An agent that does this well must (1) elicit the missing eligibility attributes it actually
needs, (2) ground them into structured parameters (income, land size, social category, age,
district), (3) reason over each scheme's eligibility rules including numeric thresholds and
category constraints, and (4) return the correct set of qualifying schemes — verifiably,
against ground truth. Deployed systems today, including India's own myScheme portal (which
runs a rule-based eligibility engine and an AI recommendation engine), operate over clean
structured form inputs; they do not take a messy, code-mixed natural-language query and are
not evaluated as reasoning systems with published error rates. That gap is the target.

## 3. Research questions

**RQ2 (primary).** *Does eligibility-matching accuracy degrade under code-mixing versus
clean English?* Holding the underlying persona and rules fixed, does exact-match
precision/recall drop — and does the false-positive rate rise — when the same query is
posed in code-mixed Tamil–English instead of English? This is the question that is
genuinely unclaimed in the literature and carries direct equity stakes: if robustness
degrades for the population that most needs these schemes, that is a finding worth
publishing.

**RQ1 (supporting).** *Can current agents do matching, not just retrieval, when rules
involve thresholds and category constraints?* We expect agents to retrieve relevant schemes
but mis-apply numeric and categorical constraints. We treat this as
replication-in-a-new-domain of a known negative result (see §4) rather than as an open
discovery, and use it to establish the retrieval-vs-matching gap on our benchmark.

**RQ3 (supporting).** *Does a structured eligibility-grounding layer beat a plain
RAG-over-scheme-text baseline?* Extract attributes → normalize → evaluate against
machine-readable rules, versus semantic retrieval over scheme prose. We expect the
structured layer to reduce false positives. This mechanism is well-established in adjacent
domains (§4); our contribution is its transfer and validation in the code-mixed welfare
setting, not the mechanism itself.

## 4. Related work and positioning

This project is applied novelty — a new task framing, benchmark, and regional resource —
rather than a frontier mechanism. Being explicit about the delta is essential, because
several recent works are close in spirit and a reviewer will look for them.

**Rule-guided reasoning with LLMs.** RULEARENA (ACL 2025) benchmarks LLM reasoning over
real-world rule systems (airline luggage fees, NBA transactions, taxation) and shows that
models struggle to apply multi-condition rules with numeric thresholds. This substantially
pre-answers RQ1 in the general case; we position our RQ1 as a domain-specific replication
with real welfare stakes, not a novel claim that "LLMs fail at rules."

**Structured / neurosymbolic eligibility matching.** The clinical-trial patient-matching
literature makes almost exactly the RQ3 argument: similarity-based retrieval smooths over
the sharp constraints (negation, numeric thresholds, temporality) that actually govern
eligibility, so structured or symbolic grounding is needed to cut false positives.
Representative work includes SATIR (constraint-satisfaction retrieval), αNeSy-CTM (LLM
autoformalization plus an SMT solver), LLM-Match, EC2Seq2Sql, and the Criteria2Query
lineage. Our grounding layer is a transfer of this established approach to welfare
eligibility; we cite this line directly and claim domain transfer, not mechanism novelty.

**Citizen-query benefit benchmarks.** CitizenQuery-UK (2026) is the closest single work: a
large benchmark of citizen queries about government benefits, taxes, and services, built on
gov.uk, with a harm framing centred on the invisible cost of misinformation. It differs
from us in three ways that keep this project distinct: it is UK/English, it evaluates
query→response factuality rather than eligibility-set matching against structured rules,
and it has neither code-mixing nor an elicitation loop. We position against it explicitly.

**Indian scheme resources.** AgriGov (2026) is a trilingual English–Hindi–Marathi corpus of
~50 farmer schemes with structured fields including eligibility, built for machine
translation, QA, IR, and RAG. It is a useful seed for KB curation but is not Tamil, not a
matching benchmark, and has no persona queries with ground-truth eligible sets. A small
number of applied Indian "scheme discovery" system papers combine rule-based filtering with
semantic similarity and generic translation, but none is a benchmark, none targets
code-mixing, and none reports a false-positive metric. India's myScheme portal ships a
deployed rule-based eligibility engine plus an AI recommendation engine — important prior
art for any product or patent claim (see §8), but not a published, code-mixed,
reasoning-evaluated benchmark.

**Code-mixed Tamil–English NLP.** Existing Tamil–English resources (DravidianCodeMix and
its descendants) cover sentiment analysis, offensive-language identification, and QA — not
task-oriented eligibility. The nearest task-oriented code-mixed work is a Telugu–English
medical dialog dataset, a different language pair and domain. No prior work carries
code-mixed Tamil–English into welfare eligibility matching.

**The open core.** The defensible contribution is the intersection nobody has occupied:
code-mixed Tamil–English + welfare-scheme eligibility matching + a benchmark with
ground-truth eligible sets + elicitation efficiency + a false-positive-harm metric. RQ2 is
the spine; the Tamil scheme rule KB and the code-mixed persona set are the durable artifacts.

## 5. Proposed approach

**5.1 Structured scheme knowledge base.** Hand-encode ~40–60 Tamil Nadu state and central
schemes. Each scheme carries human-readable prose (for the RAG baseline and for provenance)
and a machine-readable eligibility-rule object: a set of typed predicates over normalized
attributes (e.g. `income_annual <= 100000`, `land_acres <= 2`, `category in {SC, ST, MBC}`,
`age between 18 and 40`, `district in {...}` or `state == TN`), combined with explicit
AND/OR/NOT structure and exclusion clauses. Seed provenance from official portals
(myScheme, TN e-Sevai, scheme-specific sites) and AgriGov-style curation; every rule is
verified against the source guideline and dated.

**5.2 Attribute schema and normalization.** A fixed attribute vocabulary (income, land size,
social category, occupation, age, gender, district, ration-card colour, disability status,
etc.) with normalization rules (units, category codes, Tamil↔English label mappings). This
is the shared substrate the grounding layer targets.

**5.3 Code-mixed persona query set.** Construct ~150–300 citizen personas, each a full
attribute profile with a deterministically computed ground-truth eligible set (from the
rule KB). For each persona, author an underspecified natural-language query in code-mixed
Tamil–English, plus a parallel clean-English version of the same query for the RQ2 ablation.
Native validation of both the code-mixing quality and the ground-truth labels; report
inter-annotator agreement.

**5.4 Two systems under test.**

- *RAG baseline:* retrieve scheme passages by semantic similarity to the query and let the
  agent answer from retrieved prose.
- *Grounding pipeline:* extract attributes from the query → normalize to the schema → run
  an elicitation step for missing required attributes → evaluate the structured rules
  deterministically → return the qualifying set.

**5.5 Elicitation.** The agent should ask only for attributes that can change the answer
given what schemes are in play. We measure whether it does.

## 6. Evaluation

All metrics are exact and verifiable against ground truth.

- **Eligibility match precision / recall / F1** over the returned scheme set versus the
  ground-truth eligible set, per persona and aggregated.
- **False-positive rate** — the fraction of returned schemes for which the person does not
  qualify. This is the headline harm metric and is reported separately, not folded into F1.
- **Elicitation efficiency** — did the agent request the attributes actually needed to
  resolve eligibility, and no more (precision/recall over the set of "necessary questions").
- **Code-mix degradation** — the delta on every metric above between the code-mixed and
  clean-English versions of the same personas (RQ2).
- **Retrieval-vs-matching gap** — schemes correctly surfaced as relevant versus schemes
  correctly decided as eligible (RQ1).

We evaluate several current agents/models and both systems (RAG baseline vs grounding
pipeline) across both language conditions.

## 7. Timeline (5 weeks)

- **Week 1** — Build the structured scheme KB and eligibility rules; fix the attribute
  schema and normalization.
- **Week 2** — Construct and natively validate the code-mixed persona query set and its
  clean-English parallel; compute ground-truth eligible sets; measure annotator agreement.
- **Week 3** — Run agents on the RAG baseline; measure the retrieval-vs-matching gap (RQ1)
  and establish baseline false-positive rates.
- **Week 4** — Build and evaluate the structured eligibility-grounding pipeline including
  elicitation (RQ3).
- **Week 5** — Code-mix ablation (RQ2), error analysis, and write-up.

## 8. Risks, limitations, and honesty notes

**Applied, not frontier, novelty.** The grounding mechanism (RQ3) and the "LLMs mis-apply
threshold rules" finding (RQ1) are established in adjacent domains. The paper's weight rests
on the new task framing, the regional benchmark, and the code-mixing robustness result
(RQ2). We state this plainly rather than overclaiming.

**Crowded and warming space.** Public-sector citizen-query benchmarking is active (e.g.
CitizenQuery-UK), and Indian scheme tooling is already deployed. The window for the specific
eligibility-reasoning + code-mixed-Tamil framing is open but not indefinitely; the project
is scoped to five weeks partly for this reason.

**Patent caution.** A "structured eligibility-grounding layer" is unlikely to be cleanly
patentable: the extract→normalize→evaluate-against-rules pattern is prior art in
clinical-trial matching (Criteria2Query and successors) and is deployed in myScheme's own
eligibility engine. If a provisional filing is still desired, it should be reviewed by a
patent attorney against those specific references before posting, and any claim should focus
on the narrower code-mixed front-end rather than the grounding pattern. *(This is a
research-planning note, not legal advice.)*

**KB coverage and staleness.** Forty to sixty schemes is a modest slice; rules change. Every
rule is dated and sourced so the benchmark is auditable and refreshable, and coverage is
stated as a limitation rather than implied to be exhaustive.

**Construct validity of synthetic personas.** Personas are constructed, not sampled from
real citizens; ground truth is only as correct as the hand-encoded rules. Native validation
and released rule provenance mitigate but do not eliminate this.

## 9. Contributions

1. A new task framing: eligibility matching (not retrieval) for Indian welfare schemes from
   underspecified, code-mixed queries, with false-positive harm as the primary metric.
2. A hand-verified, dated, machine-readable eligibility-rule KB of ~40–60 Tamil Nadu and
   central schemes.
3. A natively validated code-mixed Tamil–English persona query benchmark with ground-truth
   eligible sets and a clean-English parallel for ablation.
4. An evaluation of a structured grounding pipeline versus RAG, and the first measurement of
   code-mixing-induced degradation in welfare eligibility matching (RQ2).

## 10. Target venues

Indic-NLP, NLP-for-social-good, and public-sector-AI workshops at ACL / EMNLP / NAACL —
receptive to regional, high-impact, benchmark-and-resource contributions, and far less
saturated than agent main tracks.

## References (to verify and format for the target venue)

- *AgriGov: A Structured Multilingual Dataset Curation for Indian Government Schemes for
  Farmers.* arXiv:2606.08272.
- *RULEARENA: A Benchmark for Rule-Guided Reasoning with LLMs in Real-World Scenarios.*
  ACL 2025.
- *The CitizenQuery Benchmark: A Novel Dataset and Evaluation Pipeline for Measuring LLM
  Performance in Citizen Query Tasks.* arXiv:2602.04064.
- *SATIR: Scalable High-Recall Constraint-Satisfaction-Based Information Retrieval for
  Clinical Trials Matching.* arXiv:2604.08849.
- *Neurosymbolic Clinical Trial Matching via LLM-Driven Abduction and Logical Verification
  (αNeSy-CTM).* arXiv:2606.20895.
- *LLM-Match: An Open-Sourced Patient Matching Model Based on LLMs and RAG.* arXiv:2503.13281.
- *EC2Seq2Sql: Patient-trial matching with LLM agents.* PMC12900307.
- Chakravarthi et al. *DravidianCodeMix: sentiment analysis and offensive language
  identification dataset for Dravidian languages in code-mixed text* (2022).
- myScheme portal and Eligibility Engine (rules.myscheme.in), Government of India.

---

## Implementation notes (added during the week-1 build)

Decisions made while building that are not in the proposal above, and that a reader of the
code will want explained:

**Three-valued rather than boolean rule evaluation.** The proposal assumes rules evaluate to
eligible/ineligible. With underspecified queries that forces a guess. The implementation
uses Kleene logic so `UNDETERMINED` is a first-class outcome, which is what makes the
elicitation loop well-defined and lets a system decline to assert eligibility.

**"Necessary questions" needed two definitions, not one.** §6 treats elicitation efficiency
as precision/recall against a single set. In practice the set that should *drive* the next
question (attributes that can settle something immediately) differs from the set that should
*judge* a question's legitimacy (attributes any still-open clause reads). Using the narrow
set for judging penalises reasonable questions — PM-KISAN's Class IV carve-out is only
decisive after employment status is known. Both are implemented and documented.

**Elicitation targets the positive set, not total resolution.** Fully settling every scheme
takes 12–19 questions even on a 10-scheme KB. But schemes left undetermined are reported as
not-eligible, which is already correct for everything the person fails, so only the eligible
set must be confirmed — 3–9 questions on the seed personas. Both numbers are computed and
reported; the gap is a result in its own right.

**The false-positive rate needed an abstention guard.** Defined naively it rewards silence:
a system returning nothing scores a perfect 0.0. It now returns `None` for empty answers,
and aggregation reports scored-versus-skipped counts.

**Retrieval is a confound for RQ2 and must be controlled, not assumed away.** Lexical
retrieval degrades under code-mixing for reasons unrelated to reasoning. An oracle retriever
(returns everything) and a dense multilingual arm are both implemented so the retrieval and
reasoning components of any observed gap can be separated.

**Reproducibility no longer comes from temperature.** The Anthropic API stopped accepting
`temperature`, `top_p` and `top_k` (API version 2026-10-21; the 1.x Python SDK already
refuses them as arguments, and current models reject them). A run therefore cannot be made
repeatable by pinning temperature to zero. Instead every raw model response is saved to
`<run>/responses.jsonl`, and `run_experiment.py --replay` re-scores from that file without
calling the model. The saved responses, not a decoding seed, are the experimental record.
