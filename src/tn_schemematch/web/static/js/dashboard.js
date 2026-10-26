/* The curator's view: KB coverage and verification status. Bars are CSS widths — no chart
   library, nothing loaded from a CDN, so the page renders identically with the network
   unplugged. */

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
})();
