# Verification protocol for the scheme rule KB

Every scheme starts at `status: draft`. Nothing may be reported from a draft KB. This
document is the checklist for moving a scheme to `verified`.

Run `schemematch verify-queue` to see what is outstanding, including the specific
`TO VERIFY` questions each scheme already flags.

## Why this is not optional

Ground truth is computed from these rules. An encoding error does not produce a crash or
an obviously wrong output — it produces a plausible eligible set that is wrong for a whole
class of personas, and every downstream number inherits the error. The rule KB is the
single point of failure for the entire benchmark.

## The pass, per scheme

**1. Reach the primary source.** Not an aggregator, not a news report, not a bank's
explainer blog. The Government Order, the scheme guidelines PDF, or the issuing
department's own page. Secondary sources are acceptable only as corroboration, and only
when the primary source is genuinely unavailable — in which case say so in `notes:`.

**2. Read the eligibility wording against `eligibility_prose`.** They must say the same
thing. `eligibility_prose` is the audit trail and the RAG baseline's input; if it drifts
from the source, the baseline is being tested on a document that does not exist.

**3. Check each clause against the wording, one at a time.** For each:

- Is the threshold value right, and in the right unit? (Annual or monthly? Acres or
  hectares? Wet land or total land?)
- Is the comparison inclusive or exclusive? `lte` versus `lt` decides real cases.
- Is the constraint on the *applicant* or the *family*? If the source says family and the
  rule tests the applicant, that is a modelling limitation to document, not a detail to
  wave through.
- Are the enum values complete? A missing category in an `in` list is a false negative for
  everyone in it.

**4. Check for clauses that exist in the source but not in the rule.** Missing exclusions
are the highest-risk error class: they produce false positives, which is the harm this
project is built to measure.

**5. Confirm the scheme is still live.** Renamed, merged, subsumed, or discontinued
schemes are common. If discontinued, set `status: deprecated` and keep it — the benchmark
needs dead schemes to catch systems recommending them.

**6. Resolve or restate the `TO VERIFY` notes.** Either settle the question against the
source, or rewrite the note so it names precisely what remains open.

**7. Record the verification.**

```yaml
status: verified
verified_on: 2026-08-22
verified_by: "name or initials"
sources:
  - url: https://...
    title: "..."
    publisher: "..."
    retrieved: 2026-08-22
```

`load_scheme` refuses to load a `verified` scheme with no sources, and `validate_kb`
flags one with no `verified_on` date.

## Second-reader requirement

Rules with any of the following need a second independent verifier, working from the
source without seeing the first encoding:

- more than one numeric threshold
- any `any:` / `not:` block (disjunctions and exclusions are where encoding errors hide)
- any clause the first verifier marked as a judgement call

Record disagreements rather than silently reconciling them. Inter-verifier disagreement
rate on encoded clauses is a number the paper should report — it is the honest measure of
how ambiguous these published rules actually are, and it is a contribution in itself.

## Re-verification

Welfare rules change: ceilings are revised, schemes merge, new exclusions appear. Every
rule carries its `retrieved` date for this reason. Re-verify before any release, and treat
a rule older than six months as stale.

The PM-KISAN two-hectare ceiling — withdrawn in 2019 and still repeated across the web
today — is the standing example of what staleness costs.
