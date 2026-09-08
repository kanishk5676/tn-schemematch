# Demo runbook

## Setup, tonight

```bash
export ANTHROPIC_API_KEY='...'          # put it in ~/.zshrc so a new terminal keeps it
pip install -e ".[dev,models]"
python -m pytest -q                      # 219 tests, no key needed
```

Then the one smoke test that matters, because it is the only thing that proves the model
id and the key are both right:

```bash
python scripts/demo.py --query "naan vivasayi, rendu ekkar nilam irukku"
```

If that prints an extracted profile, every AI path in the app works. Do this tonight, not
in the morning.

## Running it

```bash
python scripts/serve.py
```

Then open **http://127.0.0.1:5001**. Rules-only, no network at all:

```bash
python scripts/serve.py --backend none
```

`schemematch serve` is the same thing. Port 5001, not 5000 — macOS gives 5000 to
AirPlay/ControlCenter by default.

## The demo, in order

**1. Open with the problem.** `/schemes` — 41 schemes, and click one. The published
eligibility wording sits on the left, the encoded rule on the right. Say the number that
matters: **0 of 41 are human-verified**, it is in the README, and owning it is stronger
than being asked.

**2. The interview.** `/` — paste or click the farmer sample. Three things to point at:

- The **extraction panel**: Tamil script and `"2 ekkar"` on the left, canonical `farmer`
  and `2.0` on the right, and anything outside the vocabulary dropped in red. That split
  is the whole architecture in one screen.
- The **41-cell grid** in the left rail. Every answer flips cells from amber to green and
  red. It is three-valued logic you can watch.
- The **`why this question?`** chip. The interview is ranked, not a fixed form.

Answer four or five questions, then hit **show my results now**.

**3. The trace.** Open `Why? (rule trace)` on any eligible scheme. Each clause shows as a
sentence, the exact machine clause underneath, the observed value, and the KB's own note
in italics. Say: *this is the same tree `schemematch explain` prints — the page did not
invent a rendering.*

**4. Near misses.** "You would qualify if your age were 60 or above — you said 45." The
most citizen-useful thing in the app, and it falls straight out of the three-valued engine.

**5. The AI, twice more.** `Explain in plain words`, then **தமிழில்**. Then
`Compare with asking the model directly` — two columns, and any scheme the model added
that the rules rule out is a false positive, the project's headline harm metric.

**6. `/dashboard`** if there is time: coverage, attribute leverage, and any scored runs.

## What to say

- **The model never decides eligibility.** It fills attribute slots and phrases
  explanations. Every verdict is a rule evaluation with a printable trace.
- **`UNDETERMINED` is a real answer**, not a failure. Schemes left open are reported as
  not-eligible, which is why the interview can stop early instead of asking all 64.
- **One `FALSE` settles a conjunction.** Answer "male" and Kalaignar Magalir Urimai Thogai
  is ruled out instantly, with nothing else known.
- **Watch the source badges.** `aliases` grey means the deterministic normalizer handled
  it; `model` purple means the LLM was needed. Over ten questions the model is needed
  rarely — that is the design claim, visible without narration.

## If something breaks

| Symptom | Fix |
|---|---|
| No key, or the wifi is down | Untick **Use AI extraction**, or start with `--backend none`. Everything except the two explanation buttons still works. |
| You want zero typing | `http://127.0.0.1:5001/?persona=p001` replays a whole interview and lands on the results. No model, no network. |
| Port 5001 busy | `python scripts/serve.py --port 5055` |
| An answer is not understood | It falls back to the model, then retires the question after two tries. Say "skip". |
| The whole browser stack fails | `python scripts/demo.py --backend none --persona p001` — the terminal demo, unchanged and working. |

**Rehearse the `--backend none` path once.** It is the difference between a wifi problem
being invisible and being the demo.

## Honest caveats, if asked

No scheme is human-verified and the personas are author-written, not native-validated.
Both are enforced in code — `schemematch verify-queue` lists the first, and a test fails
if a seed persona does not declare the second. Every screen carries the draft banner. The
web layer keeps sessions in memory, so they do not survive a restart; that is stated in
the README rather than hidden.
