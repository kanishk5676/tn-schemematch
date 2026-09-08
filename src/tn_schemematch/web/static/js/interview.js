/* Page controller for the interview.

   The server holds the interview state; this file holds only the session id and whatever
   the last response said to draw. Every turn is one request in, one screen out. */

import { api, el, $ } from './api.js';
import { paintBoard, paintProfile } from './board.js';
import { traceDisclosure } from './trace.js';

let sid = null;
let current = null;      // the question object currently on screen
let hasModel = false;

const show = (id) => $(id).classList.remove('hidden');
const hide = (id) => $(id).classList.add('hidden');

/* ------------------------------------------------------------------ start */

async function loadSamples() {
  try {
    const { samples } = await api.samples();
    $('samples').replaceChildren(...samples.map((sample) => el('button',
      { class: 'sample', onclick: () => { $('query').value = sample.query; $('query').focus(); } },
      el('b', {}, sample.label), sample.query)));
  } catch { /* samples are a convenience; never block the page on them */ }
}

async function start(query) {
  const useAi = $('use-ai').checked;
  const maxQuestions = Number($('maxq').value) || 15;
  $('go').disabled = true;
  $('go').textContent = useAi ? 'Reading your sentence…' : 'Starting…';

  try {
    const data = await api.start(query, useAi, maxQuestions);
    sid = data.session_id;
    hasModel = Boolean(data.has_model);
    hide('ask');
    // Only claim the model read the sentence when it actually did.
    if (data.extraction.used_ai || data.extraction.error) renderExtraction(data.extraction);
    else if (useAi && query && !hasModel) noModelNotice();
    applyTurn(data);
  } catch (error) {
    $('go').disabled = false;
    $('go').textContent = 'Find my schemes';
    alert(error.message);
  }
}

/* -------------------------------------------------------------- extraction */

function noModelNotice() {
  show('extract-card');
  $('extract-card').replaceChildren(el('div', { style: 'padding:14px 16px' },
    el('div', { class: 'eyebrow', style: 'margin:0 0 6px' }, 'Running rules only'),
    el('div', { class: 'tiny muted' },
      'This server was started without a model, so the sentence was not read \u2014 '
      + 'the interview will ask for everything instead. Restart with a key to enable '
      + 'AI extraction.')));
}

function renderExtraction(extraction) {
  show('extract-card');
  $('raw-json').textContent = JSON.stringify(extraction.raw || {}, null, 2);
  $('extract-time').textContent = extraction.latency_ms ? `· ${(extraction.latency_ms / 1000).toFixed(1)}s` : '';

  const rows = [...(extraction.normalized || []), ...(extraction.derived || [])];
  $('normalized').replaceChildren(...(rows.length ? rows : [null]).map((row) => (row
    ? el('div', { class: 'map' },
        el('span', { class: 'k' }, row.attr),
        el('span', { class: 'arrow' }, '→'),
        el('span', { class: 'v' }, row.display),
        row.derived ? el('span', { class: 'badge det' }, 'derived') : null)
    : el('div', { class: 'muted tiny' }, 'the sentence stated nothing the rules can use'))));

  if (extraction.error) {
    $('dropped').classList.remove('hidden');
    $('dropped').textContent = `extraction failed: ${extraction.error} — continuing with rules only`;
  } else if (extraction.rejected?.length) {
    $('dropped').classList.remove('hidden');
    $('dropped').textContent = extraction.rejected.map((r) => `✕ dropped: ${r}`).join('\n');
  }
}

/* ---------------------------------------------------------------- one turn */

function applyTurn(data) {
  paintBoard(data.board, data.settled);
  if (data.done || !data.question) { finish(); return; }
  current = data.question;
  renderQuestion(current, data.progress);
  show('interview');
}

function renderQuestion(question, progress) {
  $('qnum').textContent = `Q${question.index}`;
  $('qbudget').textContent = `at most ${progress.max_questions}`;
  $('progress-bar').style.width = `${Math.min(100, (progress.asked / progress.max_questions) * 100)}%`;
  $('qtext').textContent = question.question;
  $('qattr').textContent = `${question.attr} · ${question.hint}`;
  $('notice').classList.add('hidden');
  hide('free');

  const why = $('why');
  if (question.why?.settles > 0) {
    why.classList.remove('hidden');
    why.textContent = `answering this could settle ${question.why.settles} scheme${question.why.settles === 1 ? '' : 's'}`;
  } else { why.classList.add('hidden'); }

  const answers = $('answers');
  answers.replaceChildren();

  if (question.control === 'buttons') {
    answers.append(
      el('button', { class: 'opt yes', onclick: () => answerValue(true) }, 'Yes', el('small', {}, 'ஆம்')),
      el('button', { class: 'opt no', onclick: () => answerValue(false) }, 'No', el('small', {}, 'இல்லை')));
  } else if (question.control === 'chips') {
    question.options.forEach((option) => answers.append(
      el('button', { class: 'opt', onclick: () => answerValue(option.value) }, option.label)));
  } else if (question.control === 'select') {
    const select = el('select', {}, el('option', { value: '' }, 'choose…'),
      ...question.options.map((o) => el('option', { value: o.value }, o.label)));
    select.addEventListener('change', () => { if (select.value) answerValue(select.value); });
    answers.append(el('div', { style: 'max-width:340px;width:100%' }, select));
  } else {
    const input = el('input', { type: 'number', id: 'num', min: question.min, max: question.max, step: 'any', placeholder: '0' });
    const submit = () => { if (input.value !== '') answerValue(Number(input.value)); };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') submit(); });
    answers.append(el('div', { class: 'numrow' }, input,
      question.unit_text ? el('span', { class: 'unit' }, question.unit_text) : null,
      el('button', { class: 'btn', onclick: submit }, 'Answer')));
    setTimeout(() => input.focus(), 30);
  }
}

function receipt(data) {
  if (!data.accepted && !data.source) return;
  const kind = data.source === 'model' ? 'ai' : 'det';
  $('receipt').replaceChildren(...[
    el('span', {}, data.source === 'skipped' ? 'skipped' : `${current?.attr} = ${data.display ?? '—'}`),
    el('span', { class: `badge ${kind}` }, data.source),
    data.settled ? el('span', { class: 'muted' }, `settled ${data.settled}`) : null,
  ].filter(Boolean));
}

async function answerValue(value) {
  const data = await api.answerValue(sid, current.attr, value);
  receipt(data);
  applyTurn(data);
}

async function answerText(text) {
  const data = await api.answerText(sid, current.attr, text);
  receipt(data);
  if (!data.accepted) {
    // Not understood — the same question stays up so it can be rephrased.
    $('notice').classList.remove('hidden');
    $('notice').textContent = data.message;
    paintBoard(data.board);
    return;
  }
  if (data.message) { $('notice').classList.remove('hidden'); $('notice').textContent = data.message; }
  $('free-text').value = '';
  applyTurn(data);
}

/* ---------------------------------------------------------------- results */

async function finish() {
  const data = await api.result(sid);
  hide('interview');
  hide('extract-card');
  renderResults(data);
  show('results');
}

function schemeCard(scheme, { miss = false } = {}) {
  const card = el('div', { class: `scheme${miss ? ' miss' : ''}` });
  const top = el('div', { class: 'scheme-top' },
    el('h3', {}, scheme.name),
    scheme.name_ta ? el('p', { class: 'ta' }, scheme.name_ta) : null,
    scheme.benefit_prose ? el('p', { class: 'benefit' }, scheme.benefit_prose.split('\n')[0]) : null);

  const meta = el('div', { class: 'scheme-meta' },
    el('span', { class: 'pill' },
      scheme.level === 'central' ? 'Central' : (scheme.jurisdiction_name || scheme.jurisdiction)),
    ...(scheme.sectors || []).slice(0, 3).map((s) => el('span', { class: 'pill' }, s.replace(/_/g, ' '))),
    el('span', { class: 'badge open', title: 'no human has checked this rule against the Government Order' }, 'draft'));
  top.append(meta);

  if (miss) {
    top.append(el('p', { class: 'missing-line' },
      'You would qualify if ', el('b', {}, scheme.missing.human.toLowerCase()),
      scheme.missing.observed_text && scheme.missing.observed_text !== '—'
        ? ` — you said ${scheme.missing.observed_text}.` : '.'));
  } else {
    const actions = el('div', { class: 'scheme-actions' });
    if (scheme.apply_url) {
      actions.append(el('a', { class: 'btn', href: scheme.apply_url, target: '_blank', rel: 'noopener' }, 'Apply →'));
    }
    if (hasModel) {
      actions.append(
        el('button', { class: 'btn', onclick: (e) => explain(scheme.id, 'en', e.target) }, 'Explain in plain words'),
        el('button', { class: 'btn', onclick: (e) => explain(scheme.id, 'ta', e.target) }, 'தமிழில்'));
    }
    top.append(actions);
    top.append(el('div', { id: `explain-${scheme.id}` }));
  }

  card.append(top);
  if (scheme.trace) card.append(traceDisclosure(scheme.trace));
  return card;
}

async function explain(schemeId, lang, button) {
  const box = $(`explain-${schemeId}`);
  box.replaceChildren(el('div', { class: 'explain-box' }, el('span', { class: 'spinner' }), ' phrasing it from the trace…'));
  button.disabled = true;
  try {
    const data = await api.explain(sid, schemeId, lang);
    box.replaceChildren(el('div', { class: 'explain-box' }, data.text,
      el('span', { class: 'src' },
        'Wording generated by the model from the rule trace below. The verdict is not — that is the rule engine.')));
  } catch (error) {
    box.replaceChildren(el('div', { class: 'explain-box' }, error.message));
  } finally { button.disabled = false; }
}

function renderResults(data) {
  const root = $('results');
  const wrap = el('div');

  wrap.append(el('div', { class: 'card' },
    el('div', { class: 'result-head' },
      el('h1', {}, data.counts.eligible
        ? `Eligible for ${data.counts.eligible} scheme${data.counts.eligible === 1 ? '' : 's'}`
        : 'No scheme is confirmed on what we know'),
      el('span', { class: 'pill' }, `${data.questions_asked} questions asked`),
      data.used_ai ? el('span', { class: 'badge ai' }, 'ai extraction') : el('span', { class: 'badge det' }, 'rules only')),
    el('p', { class: 'muted tiny', style: 'margin:6px 0 0' },
      'Every verdict below is a rule evaluation, not a model assertion. Open a trace to see the clauses.'),
    el('div', { class: 'row', style: 'margin-top:14px' },
      el('button', { class: 'btn', onclick: () => location.reload() }, 'Start over'),
      hasModel
        ? el('button', { class: 'btn', id: 'cmp-btn', onclick: runComparison },
            'Compare with asking the model directly')
        : null)));

  wrap.append(el('div', { id: 'comparison' }));

  if (data.eligible.length) {
    wrap.append(el('div', { class: 'eyebrow', style: 'margin-top:20px' }, 'Eligible'));
    data.eligible.forEach((scheme) => wrap.append(schemeCard(scheme)));
  }

  if (data.near_misses.length) {
    wrap.append(el('div', { class: 'eyebrow', style: 'margin-top:20px' },
      `Missed by a single condition (${data.near_misses.length})`));
    data.near_misses.forEach((scheme) => wrap.append(schemeCard(scheme, { miss: true })));
  }

  if (data.undetermined.length) {
    wrap.append(el('details', { class: 'card', style: 'margin-top:20px' },
      el('summary', { class: 'muted tiny', style: 'cursor:pointer' },
        `${data.undetermined.length} scheme(s) still undetermined — reported as not eligible`),
      el('div', { class: 'chips', style: 'margin-top:10px' },
        ...data.undetermined.map((s) => el('span', { class: 'chip' }, s.name,
          el('b', {}, ` ${s.n_unknown} unknown`))))));
  }

  root.replaceChildren(wrap);
  paintProfile(data.profile);
}

/* ------------------------------------------------------------- comparison */

async function runComparison() {
  const box = $('comparison');
  const button = $('cmp-btn');
  button.disabled = true;
  box.replaceChildren(el('div', { class: 'card', style: 'margin-top:14px' },
    el('span', { class: 'spinner' }), ' asking the model the same question, with no rules in the loop…'));
  try {
    const data = await api.compare(sid);
    const list = (items, klass) => el('div', { class: 'vs-list' },
      ...(items.length ? items.map((s) => el('div', { class: klass || '' }, s.name || s))
        : [el('div', { class: 'muted' }, 'none')]));

    box.replaceChildren(el('div', { class: 'card', style: 'margin-top:14px' },
      el('div', { class: 'eyebrow' }, 'Same person, two systems'),
      el('div', { class: 'vs' },
        el('div', { class: 'vs-col grounded' },
          el('h3', {}, `Grounded pipeline — ${data.counts.grounded}`),
          el('div', { class: 'tiny muted' }, 'every entry carries a rule trace'),
          list(data.grounded)),
        el('div', { class: 'vs-col direct' },
          el('h3', {}, `Model answering directly — ${data.counts.direct}`),
          el('div', { class: 'tiny muted' }, 'no rules, no trace, no way to check'),
          list(data.direct))),
      data.false_positives.length ? el('div', { style: 'margin-top:14px' },
        el('div', { class: 'eyebrow' }, `False positives — ${data.counts.false_positives}`),
        el('div', { class: 'tiny muted' },
          'the rules rule these out; a citizen sent to a district office for one loses a day of work'),
        list(data.false_positives, 'fp')) : null,
      data.hallucinated.length ? el('div', { style: 'margin-top:14px' },
        el('div', { class: 'eyebrow' }, `Schemes that do not exist — ${data.counts.hallucinated}`),
        list(data.hallucinated, 'hall')) : null,
      !data.false_positives.length && !data.hallucinated.length
        ? el('p', { class: 'tiny muted', style: 'margin-top:14px' },
            'The model agreed with the rules this time. It still cannot show why — there is no trace to open on the right.')
        : null));
  } catch (error) {
    box.replaceChildren(el('div', { class: 'card', style: 'margin-top:14px' }, error.message));
  } finally { button.disabled = false; }
}

/* -------------------------------------------------------------- listeners */

/* Replay mode: /?persona=p001 runs a whole interview from a benchmark persona and lands
   on the results. Nothing is typed and nothing leaves the machine. */
async function replay(personaId) {
  hide('ask');
  $('results').classList.remove('hidden');
  $('results').replaceChildren(el('div', { class: 'card' },
    el('span', { class: 'spinner' }), ` replaying ${personaId}…`));
  try {
    const data = await api.replay(personaId);
    sid = data.session_id;
    hasModel = Boolean(data.has_model);
    paintBoard(data.board);
    await finish();
  } catch (error) {
    $('results').replaceChildren(el('div', { class: 'card' }, error.message));
  }
}

async function loadPersonas() {
  try {
    const { personas } = await api.personas();
    if (!personas?.length) return;
    $('personas').replaceChildren(...personas.map((person) => el('button',
      { class: 'sample', onclick: () => replay(person.id) },
      el('b', {}, `${person.id} — hands-free replay`), person.sketch)));
    $('personas-block').hidden = false;
  } catch { /* optional */ }
}

$('go').addEventListener('click', () => start($('query').value.trim()));
$('skip-query').addEventListener('click', () => start(''));
$('query').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) start($('query').value.trim());
});
$('skip-q').addEventListener('click', async () => applyTurn(await api.skip(sid, current.attr)));
$('finish').addEventListener('click', finish);
$('type-instead').addEventListener('click', () => {
  $('free').classList.toggle('hidden');
  $('free-text').focus();
});
$('free-go').addEventListener('click', () => answerText($('free-text').value.trim()));
$('free-text').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && $('free-text').value.trim()) answerText($('free-text').value.trim());
});

loadSamples();
loadPersonas();

const requestedPersona = new URLSearchParams(location.search).get('persona');
if (requestedPersona) replay(requestedPersona);
