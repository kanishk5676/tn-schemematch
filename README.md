# TN-SchemeMatch

**Eligibility matching for Indian welfare schemes under code-mixed Tamil–English queries.**

A citizen types:

> *"enakku ration card irukku, vivasayi, rendu ekkar nilam — enna scheme kedaikum?"*
> ("I have a ration card, I'm a farmer with two acres — which schemes can I get?")

Knowing that PM-KISAN exists is easy. Deciding whether *this person* qualifies is not,
and getting it wrong has a cost: a citizen takes a day off work, travels to a district
office, and is turned away. This repository builds the benchmark and the tooling to
measure whether current systems get it right — and whether they get it *less* right when
the question is asked in code-mixed Tamil–English rather than clean English.

Status: **research scaffold, week 1.** The machinery runs end to end and is tested. The
knowledge base and benchmark are seeded, not finished — see [What is not done yet](#what-is-not-done-yet).

---

## What is here

| Component | Location | State |
|---|---|---|
| Attribute vocabulary (46 typed attributes, Tamil/English aliases, unit normalization) | `kb/spec/attributes.yaml` | working |
| Machine-readable eligibility rules for 10 schemes, with dated provenance | `kb/schemes/` | seeded, **unverified** |
| Three-valued rule engine | `src/tn_schemematch/rules.py` | working, tested |
| Elicitation ground truth (which questions actually matter) | `src/tn_schemematch/elicitation.py` | working, tested |
| Paired code-mixed / English persona benchmark | `data/personas/` | 4 seed personas, **not natively validated** |
| RAG baseline, direct baseline, grounding pipeline | `src/tn_schemematch/systems/` | working, tested |
| Metrics incl. false-positive rate and paired bootstrap for RQ2 | `src/tn_schemematch/eval/` | working, tested |

```bash
pip install -e ".[dev]"
schemematch validate      # check KB and persona integrity
schemematch ask p001      # see what an agent should ask next, and why
schemematch stats         # coverage and benchmark statistics
schemematch serve         # the browser front end, on http://127.0.0.1:5001
pytest                    # 219 tests, no API key required
```

### The browser front end

`schemematch serve` (or `python scripts/serve.py`) runs an interview in a browser: a
citizen types a code-mixed question, the model fills what attribute slots it can, and the
rest is elicited one ranked question at a time while a live board shows every scheme
moving between eligible, ruled out and still open. Results carry the **rule trace** for
each scheme — the same tree `schemematch explain` prints — plus the near misses, the
schemes standing one condition away.

It needs no build step and no packages beyond Flask. `--backend none` runs the whole thing
with no model and no network, which is also how the offline path is tested. Sessions are
held in memory: they do not survive a restart, they are not shared across workers, and a
session id is a bearer token with no auth behind it. That is adequate for one process
serving a room, and it is stated rather than hidden.

Three AI touchpoints, all of them optional and none of them on the decision path:
extraction from the query, normalization of a free-text answer the alias table cannot
read, and a plain-language explanation — in English or Tamil — generated **from the
satisfied clauses of the rule trace only**, so it can phrase a verdict but never reach a
different one.

---

## The three ideas that make this work

### 1. Three-valued evaluation, so "I don't know" is a first-class answer

A citizen's question mentions three attributes and leaves thirty silent. Two-valued logic
has to guess. We evaluate under Kleene's strong three-valued logic instead, so every
scheme lands in one of three buckets:

```
ELIGIBLE       the rule is satisfied on what we know
INELIGIBLE     the rule is refuted on what we know
UNDETERMINED   we must ask before we may say either
```

`UNDETERMINED` is not a failure state. It is the signal that drives elicitation, and the
reason a grounded system can decline to assert eligibility instead of inventing it.
Crucially, a single `FALSE` clause settles a conjunction regardless of what else is
unknown — so "male" rules out Kalaignar Magalir Urimai Thogai immediately, without
knowing anything else about the person.

### 2. Ground truth is computed, never labelled

Annotators verify *rules* and *query wording*. They never write down eligible sets. Gold
labels are whatever the rule engine returns for a persona's full profile, which means
labels are internally consistent by construction and the whole benchmark regenerates when
a rule is corrected. A validation check enforces the precondition: no scheme may return
`UNDETERMINED` for a fully-specified profile, because that would mean its rule reads an
attribute personas cannot supply, and its label would be a silent guess.

### 3. Two definitions of "the right questions to ask"

Asking all thirty attributes is correct and unusable. Answering from three is fast and
wrong. So we define the target precisely — and it turns out there are two useful targets:

- **Questions to settle every scheme** — the exhaustive interview. On a 10-scheme KB this
  runs to 12–19 questions.
- **Questions to reach the correct answer** (`minimal_confirming_questions`) — far
  smaller, because schemes left `UNDETERMINED` are reported as not-eligible, which is
  already correct for everything the person does not qualify for. Only the *positive* set
  must be established. For persona p001 this is 8 questions instead of 12.

The gap between them is itself a finding: most of an eligibility interview is spent ruling
things out rather than ruling them in.

Two consequences fell out of building the seed policy, both recorded as tests:

- **Ranking questions by "how many schemes would this settle?" is the wrong objective.**
  Settling usually means *ruling out*, which changes nothing — an undetermined scheme is
  already reported as not-eligible. Ranking instead by how close each scheme is to being
  *confirmed* (`question_priority`) reached the correct answer for every seed persona
  within a 15-question budget, where the resolving-power policy needed 25.
- **Asking questions in batches costs accuracy.** Every answer changes which question is
  most informative next, so a batch of three spends questions a prior answer would have
  made unnecessary. On p002 that waste was enough to drop a scheme she genuinely qualified
  for. `ask_batch_size` therefore defaults to 1.

---

## Metrics, and why the headline one is not F1

`false_positive_rate` — the fraction of returned schemes the citizen does not qualify for
— is reported **separately** from F1, not folded into it. The two errors are not
interchangeable. A false negative means someone does not hear about a benefit; that is
bad, and it is the status quo. A false positive sends them to a district office for
nothing. F1 averages those together and hides exactly the thing we care about.

Two consequences are built into the code:

- `false_positive_rate` returns `None` when a system returns nothing, and `aggregate`
  reports `n_scored` against `n_skipped`. Otherwise a system that answers "no schemes" to
  everything would post a perfect false-positive score.
- `harmful_recommendation_rate` isolates *discontinued* schemes. The KB deliberately
  retains `moovalur-marriage-assistance`, dead since 2022–23 but still all over the web
  and still in model priors. Recommending it is the most costly single error available,
  and the benchmark can catch it.

RQ2's code-mix effect is measured with a **paired bootstrap** over shared personas
(`paired_delta`). Pairing by persona is what makes the comparison clean: the two
conditions describe the same person against the same rules, so persona difficulty cancels.
Personas scored in only one condition are dropped, never imputed.

---

## An honest confound, stated up front

BM25 is not language-neutral. A code-mixed query carries fewer English content words, so
lexical retrieval degrades under code-mixing for reasons that have nothing to do with
reasoning. **Attributing the whole code-mix gap to reasoning would be wrong.** The harness
therefore reports `retrieval_recall` and `matching_recall` side by side, and ships two
controls:

- `OracleRetriever` returns every scheme, removing retrieval error entirely. Whatever gap
  survives is reasoning.
- `DenseRetriever` takes an injected multilingual encoder, as a second retrieval condition.

Similarly, `OracleExtractionPipeline` runs the grounding pipeline with extraction replaced
by the persona's annotated facts. Comparing it against the real pipeline splits the
system's error into an extraction share and a KB share — the difference between "the model
misread the query" and "we encoded the scheme wrongly", only one of which is a finding
about models.

---

## What is not done yet

This is week 1 of a five-week plan, and the gaps are load-bearing.

**No scheme is human-verified.** All 10 carry dated sources, but `status: draft` means no
person has yet checked the encoded rule against the primary Government Order. Several
carry explicit `TO VERIFY` notes about specific ambiguities — whether Kalaignar Magalir's
land ceilings are inclusive or exclusive, whether PM-KISAN's exclusions are family-scoped.
Run `schemematch verify-queue` for the list. **No number from this KB should be reported
until that pass is done.**

**No persona is natively validated.** The four seed personas were authored by the project
author to exercise the pipeline. A test (`test_seed_personas_are_marked_unvalidated`)
enforces that unvalidated personas say so in their notes, specifically so seed data cannot
quietly end up in a reported result.

**The KB is 10 schemes, not 40–60**, and the benchmark is 4 personas, not 150–300.

**Known modelling limitations**, recorded in the scheme files rather than left silent:
family-scoped conditions ("no family member in government service") are approximated by
applicant-level tests; CMCHIS's Sri Lankan Tamil refugee and inter-state migrant routes
are not encoded at all, which silently omits some of the populations least well served by
existing tooling; MRMBS's two-pregnancy limit has no parity attribute behind it.

---

## A note on the seed data's most useful accident

PM-KISAN originally capped eligibility at 2 hectares. That ceiling was **withdrawn in
2019**, and the scheme now covers all landholding farmer families. A large share of
secondary sources — including the kind that get scraped into a retrieval corpus — still
state the withdrawn limit. A RAG system reading that prose produces confident false
negatives for farmers with more than 2 hectares.

That is not a hypothetical about stale corpora. It surfaced while sourcing the very first
scheme in this KB, and it is retained as an audit note in `kb/schemes/central/pm-kisan.yaml`.

---

## Repository layout

```
kb/spec/attributes.yaml      the normalized attribute space — the shared substrate
kb/schemes/{central,tn}/     one YAML per scheme: prose + rules + dated provenance
data/personas/               profiles with paired code-mixed / English queries
src/tn_schemematch/
  attributes.py              vocabulary, unit + alias normalization
  rules.py                   rule AST, Kleene evaluator, traces
  kb.py                      loading, validation, the two views of a scheme
  elicitation.py             pivotality, oracle question sequences
  personas.py                persona loading, computed ground truth
  interview.py               resumable, headless interview engine
  serialize.py               JSON projections — rule traces, boards, forms
  systems/                   RAG baseline, direct baseline, grounding pipeline
  eval/                      metrics and the experiment runner
  web/                       Flask app, JSON API, and the browser front end
docs/                        rule language, annotation guide, verification protocol
```

## Related work this positions against

`RULEARENA` (ACL 2025) already shows LLMs mis-apply multi-condition numeric rules, so RQ1
is a domain replication rather than a discovery. The extract-normalize-solve pattern of
RQ3 is established in clinical-trial patient matching (Criteria2Query and successors,
αNeSy-CTM, SATIR) and is deployed in India's own myScheme eligibility engine. `CitizenQuery-UK`
benchmarks citizen queries about government benefits, but in UK English, on
query→response factuality rather than eligibility-set matching, with no code-mixing and no
elicitation. `AgriGov` gives structured Indian farmer schemes in English/Hindi/Marathi, but
no Tamil, no personas, no gold eligible sets.

The unoccupied intersection — and the reason this is worth doing — is code-mixed
Tamil–English **plus** eligibility matching **plus** ground-truth eligible sets **plus**
elicitation efficiency **plus** a false-positive harm metric. RQ2 is the spine; the Tamil
rule KB and the code-mixed persona set are the durable artifacts.

## License

Code: MIT. Data and KB: CC-BY-4.0. Scheme text is reproduced from Government of India and
Government of Tamil Nadu sources, cited and dated per scheme.
