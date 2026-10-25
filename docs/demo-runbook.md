# Demo runbook

## Setup, tonight

```bash
export ANTHROPIC_API_KEY='...'          # put it in ~/.zshrc so a new terminal keeps it
pip install -e ".[dev,models]"
python -m pytest -q                      # 299 tests, no key needed
python scripts/make_sample_documents.py  # four SPECIMEN photos in data/sample_documents/
```

Then the one smoke test that matters, because it is the only thing that proves the model
id and the key are both right:

```bash
python scripts/demo.py --query "naan vivasayi, rendu ekkar nilam irukku"
```

If that prints an extracted profile, every AI path in the app works. Do this tonight, not
in the morning. A `401 invalid x-api-key` means the key is wrong or revoked — make a new
one in the Anthropic Console.

## Running it

```bash
python scripts/serve.py
```

Then open **http://127.0.0.1:5001**. The default model is `claude-opus-5-5`; pass
`--model claude-sonnet-5-5` to halve the cost. Rules-only, no network at all:

```bash
python scripts/serve.py --backend none
```

`schemematch serve` is the same thing. Port 5001, not 5000 — macOS gives 5000 to
AirPlay/ControlCenter by default. Saved profiles live in `data/vault/`; for a clean demo
start with `--vault-dir /tmp/demo-vault`.

## The demo, in order

The story is **discover → verify → prepare → apply**, and one rule holds all the way
through: the model talks, reads and remembers; the rule engine decides.

**1. The assistant.** `/` — type, or click the widow-in-Madurai starter. Point at three
things under each reply:

- **The agent steps** (collapsed): `get_profile → record_facts → next_best_question`. The
  engine chose the question; the model only phrased it, in the language the person used.
- **The verdict chips**: every scheme the reply names, checked against the rule engine.
  If the model ever claims a scheme the rules rule out, the chip is red right beside the
  sentence. That is the guard, visible.
- **The live board** in the right rail, flipping amber to green and red as answers land.

Answer three or four questions, then ask *"enna documents venum?"* — the agent calls the
checklist tool and puts it on screen.

**2. Save and upload.** Click **Save my profile**, give a name, then 📎 and upload
`data/sample_documents/income_certificate.png`. If you said *"month-ku 3000"* earlier, the
certificate's Rs 72,000 a year comes back as a **conflict** with two buttons — the document
never silently overwrites what the person said. Upload `community_certificate.png` too and
watch "Community certificate" leave the to-collect list.

**3. My profile.** `/profile` — every fact with its source badge (said / answered /
document / computed) and the person's own words as evidence. Then a **life event**: change
age from 55 to 61 and the banner says what it did — *"+ now eligible for the old-age
pension"*. Point at **Get ready to apply**: one list, ranked by how many schemes need each
paper.

**4. The engine underneath.** `/interview` — pick the saved person in **Continue as** and
start: nothing on file is asked again. Open `Why? (rule trace)` on any eligible scheme:
each clause as a sentence, the exact machine clause under it, the observed value, and the
KB's own note. Say: *this is the same tree `schemematch explain` prints.*

**5. Near misses and the comparison.** "You would qualify if your age were 60 or above."
Then `Compare with asking the model directly` — any scheme the model adds that the rules
rule out is a false positive, the project's headline harm metric.

**6. `/schemes` and `/dashboard`** if there is time: published wording beside the encoded
rule, **0 of 47 human-verified** (say it before you are asked), and scored runs.

## What to say

- **The model never decides eligibility.** It fills attribute slots, reads documents,
  phrases questions and explanations. Every verdict is a rule evaluation with a trace.
- **The AI is boxed in by schemas, not just prompts.** Attribute and scheme ids in the
  tool and vision schemas are enums: the model cannot name one that does not exist. A
  document fact survives only if that type of document can prove it.
- **`UNDETERMINED` is a real answer**, not a failure. Schemes left open are reported as
  not-eligible, which is why the interview can stop early instead of asking all 64.
- **Memory with provenance.** Every saved fact says how it was learned and when; a life
  event is a new fact, not an overwrite, so "why does it think my income is 72,000?" always
  has an answer.

## If something breaks

| Symptom | Fix |
|---|---|
| No key, or the wifi is down | Start with `--backend none`. The assistant page points to the interview; profiles, uploads (choose the type by hand) and the checklist all still work. |
| You want zero typing | `http://127.0.0.1:5001/interview?persona=p001` replays a whole interview and lands on the results. No model, no network. |
| The assistant answers slowly | It is thinking between tool calls. `--model claude-sonnet-5-5` is faster. |
| Port 5001 busy | `python scripts/serve.py --port 5055` |
| A photo is not recognised | It is stored as "needs a type"; pick the type on the profile page. |
| The whole browser stack fails | `python scripts/demo.py --backend none --persona p001` — the terminal demo. |

**Rehearse the `--backend none` path once.** It is the difference between a wifi problem
being invisible and being the demo.

## Honest caveats, if asked

No scheme is human-verified and the personas are author-written, not native-validated.
Both are enforced in code — `schemematch verify-queue` lists the first, and a test fails
if a seed persona does not declare the second. Document reading and the assistant's
conversations are not yet evaluated against labelled data; what is tested is structural
(the guard, the schemas, the conflict rule). Profiles have no login — a profile id is a
bearer token — which is fine on one laptop and stated in the README.
