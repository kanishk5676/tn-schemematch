# Verification log

`docs/verification-protocol.md` says what a verification pass is. This file records what
has actually been done, by whom, and what it changed. It is append-only.

**No scheme in this KB has been promoted to `status: verified`.** A web pass is not a human
sign-off against a primary Government Order, and the protocol reserves `verified` for the
latter. Everything below is a *draft-level* correction: it changes what the KB says, and it
still needs a person with the GO in front of them.

---

## Pass 1 — web sources, 2026-09-04

Scope: all ten v0.1 seed schemes, plus the sourcing of the 32 schemes added in the same
session. Method: retrieve the scheme's own portal where it renders, otherwise a government
department or district administration page, otherwise the Press Information Bureau,
otherwise a secondary source explicitly labelled as such in the scheme file.

### Resolved — the encoded rule changed

| Scheme | v0.1 said | Source found | Change |
|---|---|---|---|
| `pm-kisan` | income-tax and government-service exclusions tested the applicant only, flagged as an approximation | family is "the husband, wife, and any minor children" and the exclusions run against any member | rule now reads `family_has_income_tax_payer`, and tests applicant **and** spouse for government service |
| `pm-vishwakarma` | same applicant-level approximation | guideline: "the person/family member should not be employed in government service", family = husband, wife, unmarried children | added `spouse_is_government_employee` to the exclusion |
| `kmut` | land ceilings flagged as possibly exclusive; scope of exclusions unknown | "family land holding not exceeding 5 acres (wetland) and 10 acres (dryland)"; exclusions stated at family level | ceilings confirmed inclusive (no change); exclusions moved to family scope (**substantive**: a woman whose husband is a government clerk was eligible in v0.1 and is not now) |
| `cmchis` | refugee and inter-state-migrant routes not encodable | both routes published, and no income limit applies to refugees | rule is now a three-branch disjunction; `is_srilankan_tamil_refugee` and `is_inter_state_migrant` added to the vocabulary |
| `mrmbs` | two-pregnancy limit not encodable | limit restated in the scheme's own wording | `pregnancy_order` added to the vocabulary; limit encoded |
| `tn-deserted-wives-pension` (new) | every number came from an unofficial blog | district administration page states all of them independently and agrees exactly | citation upgraded, both kept so the agreement is visible |
| `nsap-igndps` (new) | 80 % was an inference from "severe and multiple disabilities" | state implementation page says "disability level 80% or above" | inference corroborated, clause unchanged |

### Opened — conflicts the pass could not settle

- **`tn-widow-pension`: minimum age 30 or 40?** The encoded rule says 30. A district
  administration page publishing the whole pension cluster gives 40 for the widow pension,
  30 for deserted wives, 50 for unmarried women; the central IGNWPS floor is also 40. If 40
  is right the rule asserts eligibility for every destitute widow aged 30-39 who does not
  have it. **Left at 30 pending the Government Order**, and flagged in the scheme file. No
  result involving widows in their thirties should be reported until it is settled.
- **`kmut`: does a tractor disqualify?** The departmental wording carves out tractors,
  autorickshaws and other livelihood vehicles; the guideline digest retrieved on 2026-09-04
  names tractors among the disqualifying vehicles. Encoded at the stricter reading, which
  produces false *negatives* for farming families — the cheaper direction of error, but the
  more common household.
- **`kmut`: income ceiling at exactly Rs 2,50,000.** The same page says both "less than
  Rs 2.5 lakh" and "income exceeding Rs 2.5 lakh … ineligible". They differ at one point.
  Encoded as `lte`.
- **`evr-maniammaiyar-marriage`: is a 10th pass required?** Kancheepuram says "10th pass or
  no qualification required"; Virudhunagar says a 10th pass certificate is required. Encoded
  without the education gate.
- **`apy`: income tax payers.** Barred from enrolling since a 2022 notification, which the
  retrieved source does not state. Under the convention that every clause must point at cited
  wording, the exclusion is **not** encoded — so the rule currently reports an
  income-tax-paying 30-year-old as eligible. Highest-priority item in the queue.
- **`pudhumai-penn`: the 33 % minimum mark and the distance-education exclusion** are in the
  v0.1 rule but were not restated by the source re-read on 2026-09-04.

### Sourcing quality, stated plainly

Nine of the schemes added in this pass rest on **secondary sources** — Wikipedia for
`pm-svanidhi`, `pmjjby`, `apy`, `pmjay`, `pmay-clss`, `pmfby`; a newspaper explainer for
`kalaignar-kanavu-illam`; an unofficial digest for the `kmut` re-check; an unofficial guide
(now corroborated) for `tn-deserted-wives-pension`. Each says so in its own `sources[].note`
and `notes` block. Several official portals — myScheme, tn.gov.in, pmsvanidhi.mohua.gov.in,
jansuraksha.gov.in, kviconline.gov.in, tnadw.tn.gov.in — could not be retrieved at all
(single-page applications, robots policies, or TLS failures), which is itself worth
recording: the primary sources for Indian welfare eligibility are substantially harder to
read by machine than the secondary ones, and that asymmetry is exactly what puts stale
figures into retrieval corpora.

### Known approximations introduced deliberately

Recorded here so they are not mistaken for oversights. Each is also in its scheme file.

- `pm-sym` converts a **personal** monthly income ceiling into a **family** annual one.
- `tn-ambedkar-merit-scholarship` substitutes a 90 % mark for "top three in the state", a
  rank condition no profile can express.
- `pmmvy` cannot encode "second child only if a girl" before the birth.
- `pmfby` cannot encode "a notified crop in a notified area", so it is near-constant for
  landholding farmers.
- `tn-fishermen-ban-relief` uses a **constructed** coastal-district list, not the
  department's own. It is the only rule in the KB that reads `district`.
- `tn-da-maintenance-allowance` encodes only the 75 % route; the 40 % routes are gated on
  disability *type*, which the vocabulary does not carry.
- `pmay-clss` and `pm-vishwakarma` still approximate whole-family conditions with a
  two-person (applicant + spouse) test.

### What a human pass must do next, in priority order

1. `apy` — decide the income-tax exclusion. It is the clearest known false-positive source.
2. `tn-widow-pension` — settle 30 versus 40.
3. `kmut` — settle the tractor carve-out.
4. Replace the nine secondary citations with scheme guidelines or Government Orders.
5. Re-read `pudhumai-penn` and `tamil-pudhalvan` against the departmental orders.
6. Decide whether `pmay-clss` is still open to new applicants; if not, it belongs at
   `status: deprecated`, where recommending it counts as harm.
