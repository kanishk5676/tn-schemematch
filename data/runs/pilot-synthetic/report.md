# TN-SchemeMatch pilot — metric discrimination check

> **These numbers must not be reported.** No scheme in this KB has been
> verified against a primary source, so the ground truth they are scored
> against is provisional. See `docs/verification-protocol.md`.

> **Personas are not natively validated.** Any code-mixing effect below is
> diagnostic only — the queries have not been checked by a native speaker,
> so a measured gap could be an artefact of unnatural phrasing.

## Run configuration

- **backend**: `none`
- **model**: `none`
- **n_schemes**: `10`
- **n_personas**: `5`
- **kb_verified**: `False`
- **personas_validated**: `False`
- **metric_checks_passed**: `True`

## Results

| System | Condition | P | R | F1 | **FP rate** | Harmful FP | Exact | Retr. recall | Match recall | Gap | Questions | Q-precision | Errors |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `ablation:no_elicitation` | code_mixed | 0.000 | 0.000 | 0.000 | **—** | — | 0.00 | 1.000 | 0.000 | 1.000 | 0.0 | — | 0 |
| `ablation:no_elicitation` | english | 0.000 | 0.000 | 0.000 | **—** | — | 0.00 | 1.000 | 0.000 | 1.000 | 0.0 | — | 0 |
| `probe:abstain` | code_mixed | 0.000 | 0.000 | 0.000 | **—** | — | 0.00 | 1.000 | 0.000 | 1.000 | 0.0 | — | 0 |
| `probe:abstain` | english | 0.000 | 0.000 | 0.000 | **—** | — | 0.00 | 1.000 | 0.000 | 1.000 | 0.0 | — | 0 |
| `probe:exclusion_blind` | code_mixed | 0.933 | 1.000 | 0.960 | **0.067** | 0.000 | 0.80 | 1.000 | 1.000 | 0.000 | 0.0 | — | 0 |
| `probe:exclusion_blind` | english | 0.933 | 1.000 | 0.960 | **0.067** | 0.000 | 0.80 | 1.000 | 1.000 | 0.000 | 0.0 | — | 0 |
| `probe:oracle` | code_mixed | 1.000 | 1.000 | 1.000 | **0.000** | 0.000 | 1.00 | 1.000 | 1.000 | 0.000 | 0.0 | — | 0 |
| `probe:oracle` | english | 1.000 | 1.000 | 1.000 | **0.000** | 0.000 | 1.00 | 1.000 | 1.000 | 0.000 | 0.0 | — | 0 |
| `probe:threshold_blind` | code_mixed | 0.667 | 1.000 | 0.787 | **0.333** | 0.000 | 0.20 | 1.000 | 1.000 | 0.000 | 0.0 | — | 0 |
| `probe:threshold_blind` | english | 0.667 | 1.000 | 0.787 | **0.333** | 0.000 | 0.20 | 1.000 | 1.000 | 0.000 | 0.0 | — | 0 |
| `probe:topical[k=5]` | code_mixed | 0.280 | 0.900 | 0.419 | **0.720** | 0.000 | 0.00 | 0.900 | 0.900 | 0.000 | 0.0 | — | 0 |
| `probe:topical[k=5]` | english | 0.280 | 0.900 | 0.419 | **0.720** | 0.000 | 0.00 | 0.900 | 0.900 | 0.000 | 0.0 | — | 0 |

## RQ2 — degradation under code-mixing

| System | Metric | Code-mixed | English | Δ | 95% CI | p | Pairs |
|---|---|---|---|---|---|---|---|
| `ablation:no_elicitation` | f1 | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `ablation:no_elicitation` | exact_match | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `ablation:no_elicitation` | recall | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `ablation:no_elicitation` | retrieval_recall | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:abstain` | f1 | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:abstain` | exact_match | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:abstain` | recall | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:abstain` | retrieval_recall | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:exclusion_blind` | f1 | 0.960 | 0.960 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:exclusion_blind` | fpr | 0.067 | 0.067 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:exclusion_blind` | exact_match | 0.800 | 0.800 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:exclusion_blind` | recall | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:exclusion_blind` | retrieval_recall | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:oracle` | f1 | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:oracle` | fpr | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:oracle` | exact_match | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:oracle` | recall | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:oracle` | retrieval_recall | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:threshold_blind` | f1 | 0.787 | 0.787 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:threshold_blind` | fpr | 0.333 | 0.333 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:threshold_blind` | exact_match | 0.200 | 0.200 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:threshold_blind` | recall | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:threshold_blind` | retrieval_recall | 1.000 | 1.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:topical[k=5]` | f1 | 0.419 | 0.419 | 0.000 | [-0.171, 0.171] | 1.000 | 5 |
| `probe:topical[k=5]` | fpr | 0.720 | 0.720 | 0.000 | [-0.120, 0.120] | 1.000 | 5 |
| `probe:topical[k=5]` | exact_match | 0.000 | 0.000 | 0.000 | [0.000, 0.000] | 1.000 | 5 |
| `probe:topical[k=5]` | recall | 0.900 | 0.900 | 0.000 | [-0.300, 0.300] | 1.000 | 5 |
| `probe:topical[k=5]` | retrieval_recall | 0.900 | 0.900 | 0.000 | [-0.300, 0.300] | 1.000 | 5 |

**bold** = 95% interval excludes zero.

## Most-often wrongly offered schemes

| Scheme | Times wrongly offered |
|---|---|
| `pm-vishwakarma` | 12 |
| `pm-kisan` | 11 |
| `cmchis` | 6 |
| `tn-old-age-pension` | 5 |
| `mrmbs` | 4 |
| `kmut` | 2 |
| `pudhumai-penn` | 2 |
| `tamil-pudhalvan` | 2 |
| `tn-widow-pension` | 2 |

## Errors

- `ablation:no_elicitation` / **p001** / code_mixed: missed ['cmchis', 'pm-kisan']
- `ablation:no_elicitation` / **p001** / english: missed ['cmchis', 'pm-kisan']
- `ablation:no_elicitation` / **p002** / code_mixed: missed ['cmchis', 'kmut']
- `ablation:no_elicitation` / **p002** / english: missed ['cmchis', 'kmut']
- `ablation:no_elicitation` / **p003** / code_mixed: missed ['pudhumai-penn']
- `ablation:no_elicitation` / **p003** / english: missed ['pudhumai-penn']
- `ablation:no_elicitation` / **p004** / code_mixed: missed ['tamil-pudhalvan']
- `ablation:no_elicitation` / **p004** / english: missed ['tamil-pudhalvan']
- `ablation:no_elicitation` / **p005** / code_mixed: missed ['cmchis', 'kmut']
- `ablation:no_elicitation` / **p005** / english: missed ['cmchis', 'kmut']
- `probe:threshold_blind` / **p002** / code_mixed: wrongly offered ['pm-kisan']
- `probe:threshold_blind` / **p002** / english: wrongly offered ['pm-kisan']
- `probe:threshold_blind` / **p003** / code_mixed: wrongly offered ['cmchis']
- `probe:threshold_blind` / **p003** / english: wrongly offered ['cmchis']
- `probe:threshold_blind` / **p004** / code_mixed: wrongly offered ['cmchis']
- `probe:threshold_blind` / **p004** / english: wrongly offered ['cmchis']
- `probe:threshold_blind` / **p005** / code_mixed: wrongly offered ['pm-kisan']
- `probe:threshold_blind` / **p005** / english: wrongly offered ['pm-kisan']
- `probe:exclusion_blind` / **p005** / code_mixed: wrongly offered ['pm-vishwakarma']
- `probe:exclusion_blind` / **p005** / english: wrongly offered ['pm-vishwakarma']
- `probe:topical[k=5]` / **p001** / code_mixed: wrongly offered ['kmut', 'mrmbs', 'pm-vishwakarma', 'tn-old-age-pension'] missed ['pm-kisan']
- `probe:topical[k=5]` / **p001** / english: wrongly offered ['kmut', 'pm-vishwakarma', 'tn-widow-pension']
- `probe:topical[k=5]` / **p002** / code_mixed: wrongly offered ['mrmbs', 'pm-kisan', 'pm-vishwakarma']
- `probe:topical[k=5]` / **p002** / english: wrongly offered ['mrmbs', 'pm-kisan', 'pm-vishwakarma', 'tn-old-age-pension'] missed ['cmchis']
- `probe:topical[k=5]` / **p003** / code_mixed: wrongly offered ['cmchis', 'pm-kisan', 'pm-vishwakarma', 'tamil-pudhalvan']
- `probe:topical[k=5]` / **p003** / english: wrongly offered ['pm-kisan', 'pm-vishwakarma', 'tamil-pudhalvan', 'tn-old-age-pension']
- `probe:topical[k=5]` / **p004** / code_mixed: wrongly offered ['cmchis', 'pm-kisan', 'pm-vishwakarma', 'pudhumai-penn']
- `probe:topical[k=5]` / **p004** / english: wrongly offered ['pm-kisan', 'pm-vishwakarma', 'pudhumai-penn', 'tn-old-age-pension']
- `probe:topical[k=5]` / **p005** / code_mixed: wrongly offered ['mrmbs', 'pm-kisan', 'pm-vishwakarma']
- `probe:topical[k=5]` / **p005** / english: wrongly offered ['pm-vishwakarma', 'tn-old-age-pension', 'tn-widow-pension']
- `probe:abstain` / **p001** / code_mixed: missed ['cmchis', 'pm-kisan']
- `probe:abstain` / **p001** / english: missed ['cmchis', 'pm-kisan']
- `probe:abstain` / **p002** / code_mixed: missed ['cmchis', 'kmut']
- `probe:abstain` / **p002** / english: missed ['cmchis', 'kmut']
- `probe:abstain` / **p003** / code_mixed: missed ['pudhumai-penn']
- `probe:abstain` / **p003** / english: missed ['pudhumai-penn']
- `probe:abstain` / **p004** / code_mixed: missed ['tamil-pudhalvan']
- `probe:abstain` / **p004** / english: missed ['tamil-pudhalvan']
- `probe:abstain` / **p005** / code_mixed: missed ['cmchis', 'kmut']
- `probe:abstain` / **p005** / english: missed ['cmchis', 'kmut']

## Reading these numbers

- `probe:*` rows are not models. They are reasoners with a known, named defect, included so a real model's numbers can be read against reference points rather than in the abstract.
- `ablation:no_elicitation` is the grounding pipeline forbidden to ask questions. Its gap from the full pipeline is what elicitation is worth.
- The FP-rate column shows `(scored/total)` whenever a system returned nothing for some personas — a rate over an empty answer is undefined, not zero.
- Retrieval recall is reported beside matching recall because lexical retrieval is not language-neutral: part of any code-mix gap is retrieval, not reasoning. The `rag[oracle_all]` arm removes retrieval error entirely.
