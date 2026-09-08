# The eligibility rule language

A scheme's `eligibility:` block is a tree of typed predicates over the attribute
vocabulary in `kb/spec/attributes.yaml`. It is parsed and validated at load time, so a
malformed rule fails loudly rather than silently mis-deciding someone's eligibility.

## Predicates

```yaml
{attr: annual_family_income, op: lte, value: 250000}
{attr: social_category, op: in, value: [SC, ST, MBC]}
{attr: age, op: between, value: [30, 59]}
{attr: state, op: eq, value: TN, note: "TN state scheme"}
```

| Operator | Meaning | Applies to |
|---|---|---|
| `eq`, `ne` | equality | any type |
| `lt`, `lte`, `gt`, `gte` | ordering | **number only** |
| `in`, `not_in` | set membership | any type |
| `between` | inclusive range `[low, high]` | number |
| `is_known`, `is_unknown` | is the attribute present at all | any type |

`note:` is optional prose kept for provenance — write down *why* a clause exists,
especially when it encodes a judgement call.

## Combinators

```yaml
eligibility:
  all:                                    # conjunction
    - {attr: state, op: eq, value: TN}
    - any:                                # disjunction
        - {attr: social_category, op: in, value: [SC, ST]}
        - {attr: annual_family_income, op: lte, value: 100000}
    - not: {attr: is_income_tax_payer, op: eq, value: true}   # exclusion
```

A bare list is read as `all`. Empty `all`/`any` blocks are rejected: a vacuous conjunction
is `TRUE` and a vacuous disjunction is `FALSE`, and neither is ever what an author meant.

## Three-valued semantics

A predicate on a missing attribute evaluates to `UNKNOWN`. Propagation is Kleene's strong
three-valued logic:

| | `AND` | `OR` |
|---|---|---|
| any `FALSE` | `FALSE` | — |
| any `TRUE` | — | `TRUE` |
| otherwise, any `UNKNOWN` | `UNKNOWN` | `UNKNOWN` |
| all `TRUE` / all `FALSE` | `TRUE` | `FALSE` |

`NOT` maps `TRUE↔FALSE` and fixes `UNKNOWN`.

The practical consequence: **a single disqualifying fact settles a scheme immediately.**
A male applicant is ruled out of Pudhumai Penn without knowing his income, school, or
district. This is what keeps elicitation short.

`is_known` and `is_unknown` are the only operators that are never `UNKNOWN` — they ask
about the *state of knowledge*, not the value.

## Validation at load time

The parser rejects:

- references to attributes not in the vocabulary
- enum values outside an attribute's declared domain
- ordering operators (`lt`, `gte`, …) applied to categorical attributes — `social_category > BC`
  is meaningless and must never silently compare strings
- inverted `between` bounds
- empty `all` / `any` blocks

Rule values are **canonicalized at parse time**, so a rule may be authored with surface
forms (`value: ["scheduled caste", "ஆதிதிராவிடர்"]`) and is stored canonically (`{SC}`).

Beyond per-file parsing, `validate_kb` enforces two structural invariants:

1. Every `level: state` scheme must constrain `state`, or personas from outside Tamil Nadu
   would wrongly match.
2. **No scheme may return `UNDETERMINED` under a fully-specified profile.** A scheme that
   does reads an attribute personas can never supply, and every gold label computed from
   it would be quietly wrong.

## Writing a good rule

- **Encode the published wording, not your reading of its intent.** Where sources disagree
  about `lte` versus `lt`, pick the reading and record the disagreement in `notes:` as a
  `TO VERIFY` item. Do not average them.
- **Prefer the stricter reading when it reduces false positives**, and say so. The
  generous reading is the one that sends people to district offices.
- **Do not encode what the vocabulary cannot express.** Record it as a `MODELLING
  LIMITATION` in `notes:` instead. Family-scoped conditions and refugee status are current
  examples. A silent approximation is worse than a documented gap.
- **Every clause needs a source.** If you cannot point at wording that justifies it, it
  does not go in.
