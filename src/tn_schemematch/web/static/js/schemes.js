/* The knowledge-base browser.

   All 41 schemes arrive in one payload and every filter runs in the browser, so typing in
   the search box costs nothing. The detail view puts the published eligibility wording
   next to the encoded rule, which is the comparison a reviewer actually needs to make. */

import { api, el, $ } from './api.js';
import { renderTrace } from './trace.js';

let all = [];
let facets = { levels: [], sectors: [] };
const chosenSectors = new Set();
let chosenLevel = null;

const LEVEL_LABEL = { central: 'Central Government', state: 'Government of Tamil Nadu' };

function matches(scheme) {
  if (chosenLevel && scheme.level !== chosenLevel) return false;
  if (chosenSectors.size && !scheme.sectors.some((s) => chosenSectors.has(s))) return false;
  const query = $('q').value.trim().toLowerCase();
  if (!query) return true;
  return [scheme.name, scheme.name_ta, scheme.summary, scheme.authority, scheme.id]
    .join(' ').toLowerCase().includes(query);
}

function render() {
  const visible = all.filter(matches);
  $('count').textContent = `${visible.length} of ${all.length} schemes`;
  $('grid').replaceChildren(...visible.map((scheme) => el('button',
    { class: 'mini', onclick: () => openScheme(scheme.id) },
    el('b', {}, scheme.name),
    scheme.name_ta ? el('div', { class: 'ta' }, scheme.name_ta) : null,
    el('div', { class: 'sum' }, scheme.summary || scheme.benefit_prose || ''),
    el('div', { class: 'scheme-meta' },
      el('span', { class: 'pill' }, scheme.level === 'central' ? 'Central' : 'TN'),
      el('span', { class: 'pill' }, `${scheme.n_attributes} attrs`),
      scheme.is_verified
        ? el('span', { class: 'badge ok' }, 'verified')
        : el('span', { class: 'badge open' }, 'draft')))));
}

async function openScheme(id) {
  const dialog = $('dlg');
  $('d-body').replaceChildren(el('div', { class: 'skeleton', style: 'height:120px' }));
  dialog.showModal();
  const scheme = await api.scheme(id);
  $('d-name').textContent = scheme.name;
  $('d-ta').textContent = scheme.name_ta || '';

  const sources = (scheme.sources || []).map((source) => el('div', { class: 'tiny' },
    el('a', { href: source.url, target: '_blank', rel: 'noopener' }, source.title || source.url),
    el('span', { class: 'muted' }, ` — retrieved ${source.retrieved}`)));

  $('d-body').replaceChildren(
    el('div', { class: 'scheme-meta', style: 'margin-bottom:14px' },
      el('span', { class: 'pill' }, LEVEL_LABEL[scheme.level] || scheme.level),
      ...(scheme.sectors || []).map((s) => el('span', { class: 'pill' }, s.replace(/_/g, ' '))),
      el('span', { class: 'badge open' }, scheme.status)),
    scheme.benefit_prose ? el('p', {}, scheme.benefit_prose) : null,
    el('div', { class: 'two-col', style: 'margin-top:16px' },
      el('div', {},
        el('div', { class: 'eyebrow' }, 'Eligibility, as published'),
        el('div', { class: 'prose-box muted' }, scheme.eligibility_prose || '—')),
      el('div', {},
        el('div', { class: 'eyebrow' }, 'Eligibility, as encoded'),
        renderTrace(scheme.rule_tree))),
    scheme.documents?.length ? el('div', { style: 'margin-top:16px' },
      el('div', { class: 'eyebrow' }, 'Documents required'),
      el('div', { class: 'chips' }, ...scheme.documents.map((d) => el('span', { class: 'chip' }, d)))) : null,
    scheme.notes ? el('div', { style: 'margin-top:16px' },
      el('div', { class: 'eyebrow' }, 'Encoding notes'),
      el('div', { class: 'prose-box muted' }, scheme.notes)) : null,
    sources.length ? el('div', { style: 'margin-top:16px' },
      el('div', { class: 'eyebrow' }, 'Sources'), ...sources) : null,
    scheme.apply_url ? el('div', { style: 'margin-top:16px' },
      el('a', { class: 'btn', href: scheme.apply_url, target: '_blank', rel: 'noopener' }, 'Apply →')) : null);
}

function renderFacets() {
  $('levels').replaceChildren(...facets.levels.map((level) => {
    const input = el('input', { type: 'radio', name: 'level' });
    input.addEventListener('change', () => { chosenLevel = level; render(); });
    return el('label', { class: 'facet' }, input, LEVEL_LABEL[level] || level);
  }));
  $('sectors').replaceChildren(...facets.sectors.map(([sector, count]) => {
    const input = el('input', { type: 'checkbox' });
    input.addEventListener('change', () => {
      if (input.checked) chosenSectors.add(sector); else chosenSectors.delete(sector);
      render();
    });
    return el('label', { class: 'facet' }, input,
      el('span', {}, sector.replace(/_/g, ' ')), el('span', { class: 'n' }, count));
  }));
}

$('q').addEventListener('input', render);
$('clear').addEventListener('click', () => {
  chosenSectors.clear(); chosenLevel = null; $('q').value = '';
  document.querySelectorAll('.facet input').forEach((i) => { i.checked = false; });
  render();
});
$('d-close').addEventListener('click', () => $('dlg').close());

(async () => {
  const data = await api.schemes();
  all = data.schemes;
  facets = data.facets;
  renderFacets();
  render();
})();
