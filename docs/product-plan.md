# Product plan: from research project to a scheme assistant for rural citizens

**Goal.** A person in a Tamil Nadu village who cannot read the form — or does not understand
official Tamil or English — speaks to the app in their own words and comes away knowing
which schemes they can get, what to bring, and where to go. A volunteer or e-Sevai operator
can do this for many families.

**What does not change.** The model listens, reads and talks; the rule engine decides who is
eligible. Every verdict a citizen hears must come from `rules.py`, never from model text.
This is the product's safety guarantee, and every phase below keeps it.

**What the model is for, and what it is not.** The app must work fully with no API key and
no credit: questions, answers, verdicts, documents and the spoken summary are all
deterministic. The model is an upgrade that lets a person speak freely instead of answering
one question at a time. When the key is missing, the credit is spent or the daily cap is
reached, the assistant switches to guided mode and keeps going.

## How to run this plan

Do one phase per session, in order. Start each session with:

> Read docs/product-plan.md. Do Phase N only. Run `python -m pytest -q` before you start and
> before you commit.

Finish a phase only when its **Done when** list holds and the test suite is green.

## Facts a session needs

- Repo: github.com/kanishk5676/tn-schemematch, default branch `master`. Python 3.11+,
  Flask, vanilla ES modules (no build step), SQLite vault in `data/vault/` (git-ignored).
- Tests are all offline. Model paths are tested with `ScriptedClient` (`systems/base.py`):
  responses keyed by prompt substring, `turns` for agent steps. CI runs them on every push
  (`.github/workflows/tests.yml`).
- Model: default `claude-opus-5-5` via `systems/clients.py`; choose another with
  `--model`. The API no longer accepts `temperature`/`top_p`/`top_k`; decoding uses
  `effort`.
- Budget: the project runs on a small prepaid credit ($5–15). Rough cost of one 8-message
  assistant chat: Opus 5.5 ~$0.30–0.50, Sonnet 5.5 ~$0.15–0.25, Haiku 5.5 ~$0.01. Day to
  day, run Haiku 5.5 with a daily cap (`--daily-budget`), and keep Opus for demos.
- Run the app: `python scripts/serve.py --backend none` (no model) or, with a key,
  `python scripts/serve.py --model claude-haiku-5-5`.

## Phase 0 — Remove the research scaffolding

The benchmark, the code-mixing experiment and the baseline comparisons served a research
question the project no longer asks. Tag the current state (`git tag
research-benchmark-v1`), then remove them.

| Item | Action |
|---|---|
| `systems/rag_baseline.py`, `retrieval.py`, `synthetic.py`, `grounding.py` | Delete |
| `eval/`, `scripts/run_experiment.py`, `scripts/pilot.py`, `data/runs/` | Delete |
| `tests/test_metrics.py`, `tests/test_systems.py` | Delete after moving product tests into `test_interview.py` |
| "Compare with asking the model directly", `web/compare.py`, `/compare` | Delete |
| `docs/proposal.md`, `docs/annotation-guide.md` | Move to `docs/archive/` |
| `data/personas/` + `personas.py` | Keep, called "test profiles": regression tests for the rules |
| `scripts/gold_diff.py`, `schemematch validate` | Keep — they guard rule changes |
| `/interview` | Keep, out of the citizen nav; linked from helper mode as "Detailed check" |
| `/dashboard` | Move to `/admin` |

**Done when:** tests green; `grep -rn "rag_baseline\|eval\.\|run_experiment\|RQ2" src tests
scripts` finds nothing; the app runs in rules-only mode.

## Phase A — The app must never stop working (no-model assistant, budget guard)

Without a model the assistant page used to refuse to start, and a spent credit turned the
next message into a 503.

- **Question wording as data.** Add `ask: {ta, en}` to every askable attribute in
  `kb/spec/attributes.yaml`, in spoken Tamil and plain English. The elicitation policy picks
  the question; this text says it.
- **Guided mode.** The assistant runs with no model: the next question comes from
  `next_best_question`, answers are big buttons (yes / no / don't know / skip), a number pad,
  or a typed or spoken answer read by the deterministic parser (aliases, Tamil numbers and
  units).
- **Budget guard.** Log `response.usage` for every model call; a daily cap in US dollars
  (`--daily-budget`). When the cap is reached, or the API says the credit is spent, the chat
  continues in guided mode with a one-line notice instead of an error. Spend shows on
  `/admin`.

**Done when:** with `--backend none` a person can finish a whole conversation on the
assistant page and hear their result; a scripted credit error mid-chat switches to guided
mode; tests cover both.

## Phase 1 — Voice first

- **Speak in.** A large push-to-talk mic button using the browser's `SpeechRecognition`
  (`webkitSpeechRecognition`), `lang = 'ta-IN'`, with a தமிழ் / English toggle (`en-IN`).
  Show words as they are heard; send when the person stops. No speech support → hide the
  button, keep typing.
- **Speak out.** Read replies aloud with `speechSynthesis`, choosing a Tamil voice when the
  device has one. A speaker button on each reply; "auto-read replies" on by default.
- **The verdict is spoken by the server, not the model.** A `spoken` field on every chat
  response, built from the rule engine's result in Tamil and English templates
  (`spoken.py`, tested in `tests/test_spoken.py`).
- **Privacy notice, once.** Chrome sends audio to Google for recognition. Before the first
  recording, show and speak a one-line Tamil notice; remember the choice.
- **Phone-sized.** Mic button at least 72 px; works at 390 px wide.

**Done when:** in Chrome you can hold the mic, say "naan vivasayi, rendu ekkar nilam irukku",
see it transcribed, get a reply read aloud in Tamil, and hear the eligible schemes and
documents; without speech support the page still works.

## Phase 2 — Plain-language scheme content

"Kalaignar Magalir Urimai Thogai" means nothing to the person who needs it. "₹1,000 every
month for the woman who heads the family" does.

```yaml
plain:
  ta: { what: "...", who: "...", where: "..." }   # spoken Tamil, one short sentence each
  en: { what: "...", who: "...", where: "..." }
  reviewed: false                                  # true only after a person checks it
```

`where` names the office type (VAO, taluk office, e-Sevai centre, agriculture office,
school, online portal) — never an invented address. Write these for the most common schemes
first, drawn only from each scheme's own `benefit_prose` / `eligibility_prose`. Use `plain`
everywhere a citizen sees or hears a scheme; keep the official name small underneath.
`schemematch validate` reports coverage.

## Phase 3 — Help them apply

- **Application pack** per eligible scheme at `/profile/<pid>/pack/<scheme_id>`: plain
  description, documents with have / missing marks, the office to visit, "what the officer
  may ask" (the facts the rule checked, from the trace), the person's own facts, and the
  scheme's sources. Prints on one A4 page.
- Read it aloud; share with a `https://wa.me/?text=...` link (no WhatsApp API needed).
- **Coming up for you:** re-run the rules with the person's age plus one to five years and
  list schemes that open later (old-age pension at 60, a scheme at 18). No model needed.

## Phase 4 — Helper mode and basic login

- **Helper home** at `/helper`: every saved person with "who needs what" — missing
  documents, schemes missed by one condition, open conflicts — most actionable first.
- **Login:** a helper PIN from `HELPER_PIN`, stored hashed, checked on login, held in a
  signed Flask session cookie. Every `/api/profiles` route and `/helper` require it when a
  PIN is set; the citizen assistant only sees the profile it created in that browser.
- **Photos:** delete the photo once it has been read by default; "keep the photo" per
  document.
- **Application tracker:** per person and scheme — applied (date, reference number),
  sanctioned, rejected — so a helper can follow up.

## Phase 5 — Tamil-first, low-literacy interface

- `static/js/i18n.js` with `ta` and `en` strings; Tamil by default; `<html lang>` matches.
- Citizen screens hide attribute ids, raw JSON and the scheme grid; show "N schemes found
  for you" with large cards and an icon per sector.
- A web app manifest and a small service worker, so the app installs on Android and the
  shell loads on slow connections.

## Phase 6 — Make every "yes" trustworthy (ongoing, human work)

Follow `docs/verification-protocol.md` for the most common schemes; record each check in
`docs/verification-log.md` and set `status: verified`. Verified schemes say "you can apply";
unverified ones say "you may be able to — confirm at the office". Settle the open item in
`kb/schemes/central/apy.yaml` (the 2022 income-tax-payer bar). Run `scripts/gold_diff.py`
for every rule change.

## Phase 7 — Test with real people, then tell the story

Field test with 5–10 people using `docs/field-test.md`; fix the top three problems; rewrite
the README and report around a real user's journey and the field-test results.

## Ideas for later

- **Fake-scheme checker:** paste a WhatsApp forward; the app says whether that scheme is in
  the knowledge base, with a fixed line: "No government officer asks for money or an OTP."
- **"Fix your papers first":** compare documents with each other (name or date-of-birth
  mismatch between Aadhaar, ration card and passbook; bank account not seeded for DBT).
- **How to get each missing document** (`how_to_get` in `documents.yaml`).
- **Deadlines:** a `window:` field (PMFBY season cut-offs, fishermen's ban-period relief,
  scholarship dates).
- **"Wrong answer" reports** from helpers into a review queue on `/admin`.
- **Pre-recorded audio** for the fixed spoken text, for phones with no Tamil voice
  (Bhashini or AI4Bharat text-to-speech).
- **Kiosk mode** for e-Sevai centres: wipe everything after each family.
- **Missing schemes rural users need:** PMAY-Gramin, NSAP's National Family Benefit Scheme,
  the construction and unorganised workers' welfare boards, e-Shram, Kisan Credit Card,
  PM-Kisan Maandhan, Sukanya Samriddhi; "you get this automatically" cards.
- WhatsApp bot, phone line (IVR), SMS reminders, more languages and states.
