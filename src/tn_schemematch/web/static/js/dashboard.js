/* Coverage statistics and any scored runs on disk. Bars are CSS widths — no chart library,
   nothing loaded from a CDN, so the page renders identically with the network unplugged. */

import { api, el, $ } from './api.js';

const stat = (n, label, warn = false) =>
  el('div', { class: `stat${warn ? ' warn' : ''}` },
    el('div', { class: 'n' }, String(n)), el('div', { class: 'l' }, label));

function bars(container, rows, unit = '') {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  $(container).replaceChildren(...rows.map(([label, value]) => el('div', { class: 'bar' },
    el('span', { class: 'lbl', title: label }, label),
    el('span', { class: 'track' }, el('i', { class: 'fill', style: `width:${(value / max) * 100}%` })),
    el('span', { class: 'n' }, `${value}${unit}`))));
}

const pct = (x) => (x === null || x === undefined ? '—' : x.toFixed(3));

function renderRuns(runs) {
  if (!runs.length) {
    $('runs').replaceChildren(el('div', { class: 'muted tiny' },
      'No scored runs recorded yet. Produce one with ',
      el('span', { class: 'mono' }, 'python scripts/run_experiment.py --backend anthropic --allow-unverified'),
      '.'));
    return;
  }
  $('runs').replaceChildren(...runs.map((run) => {
    const meta = run.metadata || {};
    const table = el('table', { class: 'data' },
      el('thead', {}, el('tr', {},
        ...['System', 'Condition', 'P', 'R', 'F1', 'FP rate', 'Harmful', 'Exact', 'Qs', 'Runs', 'Errors']
          .map((h) => el('th', {}, h)))),
      el('tbody', {}, ...run.systems.map((row) => el('tr', {},
        el('td', {}, row.system),
        el('td', {}, row.condition),
        el('td', {}, pct(row.precision)),
        el('td', {}, pct(row.recall)),
        el('td', {}, pct(row.f1)),
        el('td', { class: 'fpr' }, pct(row.fpr)),
        el('td', {}, pct(row.harmful_fpr)),
        el('td', {}, pct(row.exact_match)),
        el('td', {}, row.n_questions === null || row.n_questions === undefined
          ? '—' : row.n_questions.toFixed(1)),
        el('td', {}, String(row.n_runs ?? '—')),
        el('td', {}, String(row.n_errors ?? '—'))))));

    return el('div', { style: 'margin-bottom:22px' },
      el('div', { class: 'row', style: 'margin-bottom:8px' },
        el('span', { class: 'mono tiny' }, run.dir),
        /* Show the backend, not just the model name. run_experiment.py records --model
           even when --backend none, so a rules-only run would otherwise display
           "model: claude-sonnet-5" and read as though a model had been called. */
        el('span', { class: 'pill' },
           (meta.backend && meta.backend !== 'none')
             ? `model: ${meta.model || 'unknown'}`
             : 'rules only — no model called'),
        el('span', { class: 'pill' }, `${meta.n_personas ?? '?'} personas`),
        meta.kb_verified ? el('span', { class: 'badge ok' }, 'kb verified')
          : el('span', { class: 'badge open' }, 'kb unverified — not reportable')),
      el('div', { class: 'scroll-x' }, table));
  }));
}

(async () => {
  const data = await api.stats();
  const kb = data.kb;
  const spec = data.spec;

  $('kb-stats').replaceChildren(
    stat(kb.n_schemes, 'schemes encoded'),
    stat((kb.by_status || {}).verified || 0, 'human-verified', true),
    stat(kb.by_level?.state ?? 0, 'state schemes'),
    stat(kb.by_level?.central ?? 0, 'central'),
    stat(Object.keys(kb.by_jurisdiction || {}).length, 'states covered'),
    stat(spec.n_attributes, 'attributes'),
    stat(spec.n_elicitable, 'can be asked'),
    stat(spec.n_derived, 'computed'),
    stat(kb.mean_rule_nodes?.toFixed?.(1) ?? kb.mean_rule_nodes, 'mean rule size'));

  if (Object.keys(kb.by_jurisdiction || {}).length > 1) {
    bars('sector-bars', Object.entries(kb.by_jurisdiction).sort((a, b) => b[1] - a[1]));
    document.querySelector('#sector-bars').closest('.card').querySelector('h2')
      .textContent = 'Schemes by jurisdiction';
    return;
  }
  bars('sector-bars', Object.entries(kb.by_sector || {}).sort((a, b) => b[1] - a[1]).slice(0, 14));
  bars('attr-bars', (data.attribute_usage || []).map((row) => [row.attr, row.n_schemes]));
  renderRuns(data.runs || []);
})();
