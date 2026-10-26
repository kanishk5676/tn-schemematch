# Demo runbook

## Setup, the night before

```bash
pip install -e ".[dev,models]"
python -m pytest -q                       # offline, no key needed
schemematch validate                      # rules, questions, documents, test profiles
python scripts/make_sample_documents.py   # four SPECIMEN photos in data/sample_documents/
```

Open the page once in **Chrome on the phone you will demo with**, and check it has a Tamil
voice (Settings → Text-to-speech → Google → Tamil). Without one, Tamil replies are shown
but not read aloud — the page says so, but it is a worse demo.

## Running it

The default demo needs nothing:

```bash
python scripts/serve.py --backend none --vault-dir /tmp/demo-vault
```

With a key, to show free conversation — use Haiku and a cap so the demo cannot spend the
credit:

```bash
export ANTHROPIC_API_KEY='...'
python scripts/serve.py --model claude-haiku-5-5 --daily-budget 0.50 --vault-dir /tmp/demo-vault
```

To show helper mode, also `export HELPER_PIN=2468` before starting. Open
**http://127.0.0.1:5001** (port 5001 because macOS gives 5000 to AirPlay). To reach it
from the phone, add `--host 0.0.0.0` and open the laptop's address on the same wifi.

## The demo, in order

The story is **speak → hear → take the sheet → the helper follows up**. One rule holds all
the way through: the rule engine decides; words and voice are only how it is said.

**1. A widow, by voice, in Tamil.** `/` on the phone. Tap the mic, allow the privacy note
(read it out — it is the honest part), and answer: *"அறுபத்தெட்டு"* for age, then tap
பெண், கணவனை இழந்தவர், கிராமம். Point at:

- the question in Tamil with the English under it, and *"இந்தப் பதில் 30 திட்டங்களை
  முடிவு செய்யும்"* — the engine chose the question to settle as much as possible;
- "தெரியாது" on every question, and the skip note on caste and income;
- "நீங்கள் சொன்னவை" filling in, in Tamil.

**2. Hear the result.** Tap **எனக்கு என்ன கிடைக்கும்?** It reads the schemes aloud in
plain words, the papers to bring, and *"confirm at the office"* — because no rule is
human-verified yet, and the app says so out loud. Point at "coming up for you" if she is
under 60.

**3. Take the sheet.** Save her details, then **📋 விண்ணப்பத் தாள்** on the old-age
pension. One A4 page: the checklist, the taluk office, and *what the officer may ask* —
the clauses the rule checked, with her own answers. Print it, read it aloud, or tap
WhatsApp.

**4. Out of money, mid-conversation.** (With a key.) Start the server with a tiny cap,
`--daily-budget 0.001`. The first free-conversation turn spends past it; on the next
message the chat says it will carry on with simple questions, and does. Nothing breaks, and
`/admin` shows what was spent.

**5. The helper.** `/helper`, log in with the PIN. Everyone saved, most actionable first:
papers missing, one condition away, turning 60. Mark her application as applied with a
reference number and a date two months ago — she moves to the top, flagged to follow up.

**6. Under the hood, if asked.** `/interview` (the detailed check) shows the rule trace for
any scheme; `/schemes` shows each rule beside its published wording; `/admin` shows
coverage and today's model spend.

## What to say

- **The model never decides eligibility.** In guided mode there is no model at all. In
  free conversation the model can only reach a verdict through the rule engine, and the
  engine's own result is read aloud after the model speaks.
- **It works with no money.** Every question, answer, result and sheet is fixed text and
  rules; the model is an upgrade.
- **Honest about drafts.** Unchecked rules are said as "you may be able to — confirm at the
  office", never "you can apply".
- **Private by default.** Data stays on the machine; photos are deleted once read; with a
  PIN, a citizen sees only their own profile.

## If something breaks

| Symptom | Fix |
|---|---|
| No key, or no wifi | `--backend none`. That *is* the product; nothing on the demo path needs a model. |
| The mic button is missing | The browser has no speech recognition — use Chrome. Typing and buttons still work. |
| Tamil is not read aloud | No Tamil voice on the device; install one (see setup) or switch to English. |
| You want zero typing | `/interview?persona=p001` replays a whole interview from a test profile. |
| Port 5001 busy | `python scripts/serve.py --port 5055` |
| The browser stack fails | `python scripts/demo.py --backend none --persona p001` — the terminal demo. |

## Honest caveats, if asked

No rule is human-verified; the Tamil wording has not been reviewed by a native speaker; the
app has not yet been tested with the people it is for (`docs/field-test.md` is the plan).
All three are stated in the README and in the app itself.
