# Annotation guide: personas and code-mixed queries

Annotators validate **rules** and **query wording**. Annotators never write down eligible
sets — those are computed by the rule engine from the full profile. If a computed gold set
looks wrong, the fix is to the rule or the profile, never to the label.

## What a persona is

A complete attribute profile, plus two renderings of the same underspecified question: one
code-mixed Tamil–English, one clean English. The pairing *is* the experiment. Because the
profile, the KB, and the revealed facts are held fixed, any difference in a system's
output between conditions is attributable to the query language and nothing else.

That only holds if both variants really do reveal the same facts. Checking that is the
single most important thing an annotator does.

## Building the profile

**Set every attribute the KB's rules reference.** `schemematch validate` fails a persona
whose profile leaves any scheme `UNDETERMINED` — an incomplete profile produces an
unreliable gold set. Run it after every edit.

**Make the person plausible.** A 19-year-old with a `postgraduate` education level, or a
`landless` `farmer` with 40 acres of wet land, will produce technically valid ground truth
about someone who does not exist. Internal consistency checks catch some of this
(`wetland_acres + dryland_acres` must equal `land_owned_acres`); judgement catches the rest.

**Aim for informative cases, not comfortable ones.** The benchmark learns nothing from
personas who obviously qualify for everything or nothing. What it needs:

- **Near misses.** Family income of ₹1,25,000 against a ₹1,20,000 ceiling. Age 20 against
  a 21 floor. These are where threshold reasoning either happens or does not.
- **Surface-cue traps.** p002 is the model: widowed, low income, female — every cue points
  at the destitute widow pension, and she fails it, because she has a regular income and
  is not certified destitute.
- **Minimal pairs.** p003 and p004 have identical queries and profiles differing in exactly
  one attribute, with disjoint gold sets. These isolate a single categorical constraint
  from every other source of difficulty.
- **Empty gold sets.** Some people qualify for nothing, and "nothing here fits you" is a
  correct and useful answer. The metrics score it as such.

## Writing the code-mixed query

**Write what someone would actually type**, not a translation exercise. Real messages mix
Tamil script and romanized Tamil in the same sentence, use English nouns inside Tamil
grammar ("ration card irukku"), and drop case markers. Keep all of that. Do not normalize
to one script — p002's query deliberately mixes both, and that mixture is the phenomenon.

**Underspecify.** The query should state two to five attributes and leave the rest silent.
A query that gives everything away is not a citizen query, it is a form submission.

**Do not name schemes.** "enna scheme kedaikum?" is the task. "Am I eligible for PM-KISAN?"
is a different, much easier one.

**Keep quantities in the citizen's own idiom.** "rendu ekkar", "month-ku 8000", "80 cent".
Normalizing these is the pipeline's job and part of what is being measured.

## Writing the English parallel

Same facts, same number of facts, natural English. Not a gloss of the Tamil word order —
what a fluent English speaker would write to ask the same question.

The test: could a careful reader extract exactly the same attribute set from both? If the
English version accidentally reveals gender through a pronoun that the Tamil version
leaves open, the pair is broken and RQ2 is measuring the leak.

## `stated_in_query`

List the attributes a perfect extractor would recover from the query — no more. This drives
the elicitation ground truth, so over-listing makes the benchmark think the system knows
things it was never told.

The list applies to **both** variants. If they differ in what they reveal, fix the queries
rather than the list.

## Annotation fields

```yaml
annotation:
  author: "who wrote the persona"
  validated_by: "native Tamil speaker who checked it"
  validated_on: 2026-08-22
  codemix_naturalness: 4      # 1-5: would a real person write this?
  profile_plausibility: 4     # 1-5: could this person exist?
  parallel_faithful: true     # do both variants reveal exactly the same facts?
  notes: "design intent, traps, anything a later reader needs"
```

`parallel_faithful: false` excludes the persona from RQ2 analysis. Mark it rather than
quietly fixing a pair you are unsure about.

Until `validated_by` is filled, the notes must contain `NOT YET NATIVELY VALIDATED` — a
test enforces this, specifically so seed data cannot end up in a reported result.

## Agreement

Every persona needs two independent native-speaker validations of the code-mixed query.
Report inter-annotator agreement on `codemix_naturalness` (weighted κ or Krippendorff's α)
and on `parallel_faithful` (Cohen's κ) in the paper.

Where the two disagree on `parallel_faithful`, a third annotator adjudicates. Do not
average a disagreement about whether the experiment's central control holds.
