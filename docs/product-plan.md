# Product plan: from research project to a scheme assistant for rural citizens

**Goal.** A person in a Tamil Nadu village who cannot read the form — or does not understand
official Tamil or English — speaks to the app in their own words and comes away knowing which
schemes they can get, what to bring, and where to go. A volunteer or e-Sevai operator can do
this for many families.

**What does not change.** The model listens, reads and talks; the rule engine decides who is
eligible. Every verdict a citizen hears must come from `rules.py`, never from model text. This is
the product's safety guarantee, and every phase below keeps it.

---

## How to run this plan

Do **one phase per session**, in order, on its own branch (`product/phase-N-<name>`). Start each
session with:

> Read `docs/product-plan.md`. Do Phase N only. Run `python -m pytest -q` before you start and
> before you commit. Commit on branch `product/phase-N-<name>`; end commit messages with the
> Co-Authored-By line. Do not push without asking me.

Finish a phase only when its **Done when** list holds and the test suite is green.

### Facts the session needs

- **Repo:** `github.com/kanishk5676/tn-schemematch`, default branch `master`. Python 3.11, Flask,
  vanilla ES modules (no build step), SQLite vault in `data/vault/` (git-ignored).
- **Tests:** about 299 cases, all offline. Model paths are tested with `ScriptedClient`
  (`systems/base.py`): `responses` keyed by prompt substring, `turns` for agent steps.
- **Model:** default `claude-opus-5-5` via `systems/clients.py`. The API no longer accepts
  `temperature`/`top_p`/`top_k`; decoding uses `effort`. The user's last API key was rejected
  (401), so **assume no working key**: every phase below except 2b works without one.
- **Pages today:** `/` assistant, `/profile`, `/interview`, `/schemes`, `/dashboard`.
- **Run the app:** `python scripts/serve.py --backend none` (rules only) or with a key,
  `python scripts/serve.py`.

---

## Phase 0 — Remove the research scaffolding (half a day)

The benchmark, the code-mixing experiment and the baseline comparisons served a research
question the project no longer asks. They make the product harder to read and the README
harder to believe. Archive them, then remove them.

**First:** tag the current state so nothing is lost: `git tag research-benchmark-v1`.

| Item | Action | Why |
|---|---|---|
| `systems/rag_baseline.py`, `systems/retrieval.py`, `systems/synthetic.py`, `systems/grounding.py` | **Delete** | Baselines and probes for the experiment |
| `eval/` (runner, metrics, report) | **Delete** | Experiment scoring |
| `scripts/run_experiment.py`, `scripts/pilot.py` | **Delete** | Experiment drivers |
| `data/runs/`, `data/queries/` | **Delete** | Experiment output |
| `tests/test_metrics.py`, `tests/test_systems.py` | **Delete**, after moving any test that still checks product behaviour (extraction normalization, "unparseable value is dropped") into `test_interview.py` | Test the deleted code |
| "Compare with asking the model directly" button + `web/compare.py` + `/compare` route | **Delete** | A research demo, confusing for a citizen |
| `docs/proposal.md`, `docs/annotation-guide.md` | **Move** to `docs/archive/` | Research history, still citable |
| `data/personas/` (247) + `personas.py` | **Keep**, renamed in prose to "test profiles" | They are regression tests: the rule engine's answer for each is the gold set, so a rule change that breaks someone is caught |
| `scripts/gold_diff.py`, `schemematch validate` | **Keep** | They guard rule changes — more important in a product |
| `/interview` page | **Keep**, remove from the citizen nav; link it from helper mode as "Detailed check" | Useful for helpers, too dense for citizens |
| `/dashboard` | **Move** to `/admin` (not in nav) | Curator view: coverage and verification status |
| `docs/retrieval-log.md`, `verification-*.md`, `rule-language.md` | **Keep** | Provenance and rule-writing guides |

**Required code moves before deleting** (otherwise imports break):
- `EXTRACTION_SYSTEM_PROMPT` lives in `systems/grounding.py` and is imported by `interview.py`
  and `scripts/demo.py` → move it into `interview.py`.
- `systems/base.py` imports `Persona` for `SimulatedCitizen`/`MatchResult`/`MatchSystem` (benchmark
  only). Keep `LLMClient`, `ScriptedClient`, `ScriptedBlock`, `ScriptedMessage`,
  `parse_json_response`, `attribute_catalogue`; delete the benchmark classes.
- `DEFAULT_QUESTION_BUDGET` in `__init__.py` stays (the assistant uses it).
- `pyproject.toml`: drop the `retrieval` extra; update the description and keywords.

**Done when:** `python -m pytest -q` is green; `grep -rn "rag_baseline\|eval\.\|run_experiment\|RQ2" src tests scripts` finds nothing;
the app runs in rules-only mode with no import errors; the README no longer has "Research
framing" or "RQ" sections (full rewrite is Phase 7).

---

## Phase 1 — Voice first (1–2 days, no API key needed)

Most users cannot read, so the assistant must work by speaking and listening.

1. **Speak in.** A large microphone button (push to talk) on the assistant, using the browser's
   `SpeechRecognition` (`webkitSpeechRecognition` in Chrome) with `lang = 'ta-IN'`, and a
   தமிழ் / English toggle (`en-IN`). Show the words as they are heard; send when the person
   stops. If the browser has no speech recognition, hide the button and keep typing.
2. **Speak out.** Read every assistant reply aloud with `speechSynthesis`, choosing a Tamil voice
   when the device has one (`voice.lang` starting `ta`), else English. A speaker button on each
   reply; an "auto-read replies" switch, on by default.
3. **The verdict is spoken by the server, not the model.** Add a `spoken` field to the chat
   response, built deterministically from the rule engine's result (eligible schemes, the next
   step, documents to bring) in Tamil and English templates. The page reads `reply`, then
   `spoken`. This keeps the guarantee: what the person hears about eligibility comes from
   `rules.py`. Unit-test the templates in a new `tests/test_spoken.py`.
4. **Privacy notice, once.** Chrome sends audio to Google for recognition. Before the first
   recording, show and speak a one-line Tamil notice; remember the choice in `localStorage`.
5. **Phone-sized.** Mic button at least 72 px, reachable by thumb; test at 390 px wide.

**Optional 1b — offline speech (only if time allows):** `POST /api/speech` taking a short audio
clip and returning text from a local open model (Whisper via `faster-whisper`, or AI4Bharat's
Indic ASR). Lets the app work without sending audio to Google. Put the dependency in a
`speech` extra so the core stays light.

**Done when:** in Chrome you can hold the mic, say "naan vivasayi, rendu ekkar nilam irukku",
see it transcribed, get a reply read aloud in Tamil, and hear the eligible schemes and documents;
without speech support the page still works by typing; tests green.

---

## Phase 2 — Plain-language scheme content (1–2 days)

"Kalaignar Magalir Urimai Thogai" means nothing to the person who needs it. "₹1,000 every month
for the woman who heads the family" does.

1. Add optional fields to every scheme YAML and to `kb.py`'s loader:
   ```yaml
   plain:
     ta: { what: "...", who: "...", where: "..." }   # spoken Tamil, one short sentence each
     en: { what: "...", who: "...", where: "..." }
     reviewed: false                                  # true only after a person checks it
   ```
   `where` names the office type (VAO, taluk office, e-Sevai centre, agriculture office, school,
   online portal) — never an invented address.
2. **2a, by hand:** write these for the 10–15 most common schemes first (old age, widow,
   KMUT, PM-KISAN, CMCHIS, PM-JAY, MGNREGA, PMFBY, scholarships, maternity).
   **2b, with a key:** draft the rest with the model from `benefit_prose`/`eligibility_prose`,
   saved with `reviewed: false` for a person to check.
3. Use `plain` everywhere a citizen sees or hears a scheme: chat cards, the profile page,
   `explain_scheme`, and Phase 1's spoken summary. Keep the official name small underneath.
4. `schemematch validate` reports how many schemes have reviewed plain text (a count, not an error).

**Done when:** the 15 common schemes show and speak plain Tamil; validation prints coverage;
tests cover the loader and the fallback when `plain` is missing.

---

## Phase 3 — Help them apply (2 days)

Eligibility is half the job; the other half is walking into the right office with the right papers.

1. **Application pack** per eligible scheme at `/profile/<pid>/pack/<scheme_id>` (and an API
   route): plain description, the documents with have / missing marks, the office type to visit,
   "what the officer may ask" (the facts the rule checked, from the trace, in plain words), and the
   person's own relevant facts. Print-friendly CSS (A4, large type).
2. **Read it aloud** with the Phase 1 voice.
3. **Share** with a WhatsApp share link (`https://wa.me/?text=...`) containing the plain summary
   and checklist — no WhatsApp account or API needed.
4. The assistant's `show` tool gains `application_pack`.

**Done when:** for a saved person, each eligible scheme has a pack that prints on one page, reads
aloud, and shares; tests cover the route and that only eligible schemes get a pack.

---

## Phase 4 — Helper mode and basic login (2 days)

In villages one person often helps many: an e-Sevai operator, an anganwadi or ASHA worker, a
panchayat volunteer, an NSS student.

1. **Helper home** at `/helper`: all saved families and people, with "who needs what" — pending
   documents, schemes missed by one condition, open conflicts — sorted by what is most actionable.
2. **Quick add person** with voice, and "start assistant for this person".
3. **Basic login.** Today there is none (a profile id is a bearer token). Add a helper PIN set by an
   environment variable (`HELPER_PIN`), stored hashed, checked on login, held in a signed Flask
   session cookie. Every `/api/profiles` route and `/helper` require it; the citizen assistant
   works without it but only sees the profile it created in that browser.
4. **Photos:** default to deleting the photo once it has been read (keep only the extracted facts),
   with a per-document "keep the photo" option.

**Done when:** without the PIN, profile APIs return 401; with it, the helper sees all families;
tests cover login, logout and the 401s.

---

## Phase 5 — Tamil-first, low-literacy interface (2 days)

All interface text is English today (`<html lang="en">`).

1. **Language:** a small `static/js/i18n.js` with `ta` and `en` strings for every label; Tamil by
   default, a switch in the top bar; set `<html lang>` to match.
2. **Simplify the citizen screens:** hide attribute names (`is_secc_deprived_household`), raw
   JSON and the 47-cell grid; show "N schemes found for you" with large cards and an icon per
   sector (health, pension, farming, education, housing, women).
3. **Install on a phone:** a web app manifest and a small service worker so the app shell loads
   on slow connections and can be added to the home screen. Rules-only mode already works offline
   on the server side.
4. Keep `/interview` and `/admin` as they are — they are for helpers and curators.

**Done when:** a first-time user sees only Tamil, large buttons and icons; Lighthouse
accessibility score 90+; the app installs on Android Chrome.

---

## Phase 6 — Make every "yes" trustworthy (ongoing, start early)

For a product, a wrong "yes" costs a poor family a day's wages and a wasted trip. Today 0 of 47
rules are human-verified.

1. Follow `docs/verification-protocol.md` for the 10–15 schemes from Phase 2a: check each rule
   against the official Government Order, record it in `docs/verification-log.md`, set
   `status: verified`.
2. In the UI and the spoken summary: verified schemes say "you can apply"; unverified ones say
   "you may be able to — confirm at the office".
3. Settle the open item in `kb/schemes/central/apy.yaml`: its own note says income-tax payers
   may have been barred from enrolling since a 2022 notification, which the rule does not encode.
   Find the notification; if confirmed, add the exclusion and cite it.
4. Keep `scripts/gold_diff.py` in the workflow for every rule change.

**Done when:** at least 10 schemes are `verified`, and the UI and speech treat verified and
unverified schemes differently.

---

## Phase 7 — Test with real people, then rewrite the story (1 week, mostly field work)

1. **Field test** with 5–10 people (family, neighbours, a village or an e-Sevai centre). Use
   `docs/field-test.md` (write it in this phase): five tasks — "find what you can get", "say what
   documents you need", "save your details", "upload a document", "hear where to go" — and
   record, for each person: language, could read? (y/n), task done? (y/n), time, help needed,
   what confused them, and whether the schemes found were right (a helper checks).
2. **Fix the top three problems** they hit.
3. **Rewrite `README.md` and the project report as a product:** problem, who it is for, a typical
   user's journey (with screenshots), how it works, how it stays safe (rules decide, verified
   schemes, privacy), field-test results, and the roadmap below. Remove research framing.

---

## Phase 8 — Money and correctness in the scheme data

1. **Benefit amounts as data.** An optional `value` block on each scheme (`amount`, `per`
   = month / year / once, optional `max`, `per_family`) and `cover` for insurance. Every
   figure must appear in the scheme's sourced `benefit_prose` — `schemematch validate`
   fails otherwise — so an amount is never typed in from memory.
2. **Schemes that cannot be taken together.** `cannot_combine_with: [{id, reason}]`, kept
   symmetric by validation. The reason quotes the source. Totals count only the better one
   of a group, and the UI says "you can take only one of these".

## Phase 9 — From "eligible" to "money received"

1. **How to get each missing document** (`how_to_get` in `kb/spec/documents.yaml`, per
   state with a national default): which office issues it, where to apply, what to bring.
   Marked `reviewed: false` until a person checks it; the UI says so.
2. **Application tracker** in the vault: planned → applied → approved / rejected →
   received, as an append-only event log like facts. Follow-up reminders after 30 days.
3. **Rejections explained.** A vocabulary of common reasons (`kb/spec/rejections.yaml`),
   each tied to the attributes and documents it concerns, with what to do next.
4. **Outcome feedback.** A rejection of someone the rules called eligible flags that
   scheme for review on the admin page — the loop that finds wrong rules.
5. **Complaint drafts** from a template (English, Tamil, Malayalam), grounded in the
   clauses the person meets, addressed to the state's grievance channel.
6. **Calendar**: follow-ups, birthdays that open or close a scheme, and dated
   application windows where a source gives one.

## Phase 10 — Families and what comes next

1. **Household view**: every member's schemes, a yearly total that counts per-family
   schemes once and respects can't-combine groups, and documents shared across the family.
2. **Unlock view**: near misses a person can act on (open a bank account, register at the
   employment exchange) and unanswered questions that gate the most money, ranked by value.
3. **Coming up**: schemes that open or close with age, worked out by re-running the rules
   with the person older, never guessed.

## Phase 11 — Kerala and Malayalam

1. Text normalizer keeps every Indic script (it used to break Malayalam words apart).
2. `state` gains `KL`; districts are tied to their state in `jurisdictions.yaml`;
   aliases that mean different things in different states ("white card") are scoped by
   state; ration cards gain Kerala's NPS / NPNS classes.
3. `name_ml` / `label_ml` beside the Tamil fields; Malayalam and Manglish aliases;
   assistant, document reader and explanations accept Malayalam.
4. Kerala schemes, sourced and logged like the Tamil Nadu ones, with Kerala test profiles.

## Phase 12 — Helpers, partners and privacy

1. **Camp mode** (`/camp`): screen many families in a day, quick intake, one printed sheet
   per family (`/print/<pid>`).
2. **Anonymous reports** for panchayats and NGOs, with counts under 5 suppressed.
3. **Partner API**: `POST /api/v1/check` with a key (`schemematch keys create`), stateless
   — nothing a partner sends is stored.
4. **Consent and audit** (DPDP Act 2023): consent recorded per person, a notice in the
   person's language, data export, and a log of who opened or changed a profile.
5. **Source watcher** (`schemematch watch-sources`): re-fetch each scheme's sources, flag
   changed or unreachable ones for re-verification.
6. **PDF documents** read the same way as photos.

**Still needs infrastructure, not code in this repo:** HTTPS hosting, Postgres instead of
SQLite for many users, encrypted storage and backups, DigiLocker (needs partner approval).

### Status of Phases 8–12 (2026-10-26)

Built and tested (394 test cases, offline). What is left:

- **Human review**: `document_guides.yaml`, `rejections.yaml` and `grievance.yaml` are all
  `reviewed: false`. Check each against the department's page and add `source:`.
- **Application windows**: the mechanism exists (a window must cite a source); no scheme
  has one yet, because crop-insurance cut-offs are set by each state every season.
- **Kerala**: more schemes (LIFE Mission housing, KASP, Snehapoorvam), the OEC category,
  attributes for house area and vehicle engine size, more Kerala test profiles, and a
  second look at the welfare-pension portal, which refused the connection.
- **Source watcher**: run `schemematch watch-sources --update` once to record fingerprints,
  then schedule it weekly.
- **Login for saved profiles** is still Phase 4; the helper PIN covers only helper pages.

---

## Later — not this semester

- **WhatsApp bot** taking voice notes (needs a WhatsApp Business account and approval).
- **Phone line (IVR)** for people without smartphones: call a number, speak, hear the answer.
- **SMS reminders** for documents still missing and application deadlines.
- **More languages** for migrant workers (Hindi, Telugu), and other states' schemes.

---

## Order and effort at a glance

| Phase | What | Needs an API key? | Effort |
|---|---|---|---|
| 0 | Remove research scaffolding | No | ½ day |
| 1 | Voice in and out | No (1b optional) | 1–2 days |
| 2 | Plain Tamil scheme content | Only for 2b | 1–2 days |
| 3 | Application pack, read aloud, share | No | 2 days |
| 4 | Helper mode, PIN login, photo privacy | No | 2 days |
| 5 | Tamil-first simple UI, installable | No | 2 days |
| 6 | Verify 10–15 rules | No (human work) | ongoing |
| 7 | Field test, fixes, rewrite README and report | No | 1 week |
| 8 | Benefit amounts, can't-combine rules | No | built |
| 9 | Guides, tracker, rejections, outcomes, complaints, calendar | No | built; data needs review |
| 10 | Family, unlock, coming up | No | built |
| 11 | Kerala and Malayalam | No | started: 5 pensions |
| 12 | Camp, reports, partner API, consent, audit, watcher, PDF | No | built |
