/* The anonymous report: counts across a camp or everyone saved, small counts suppressed
   by the server before they ever reach the page. */

import { api, el, $ } from './api.js';

function table(head, rows) {
  return el('div', { class: 'scroll-x' }, el('table', { class: 'data' },
    el('thead', {}, el('tr', {}, ...head.map((h) => el('th', {}, h)))),
    el('tbody', {}, ...rows.map((row) => el('tr', {}, ...row.map((cell) => el('td', {}, String(cell))))))));
}

async function render(cid) {
  const report = await api.report(cid || null);
  const box = $('report');
  if (report.suppressed) {
    box.replaceChildren(el('p', { class: 'muted' }, report.message));
    return;
  }
  box.replaceChildren(
    el('div', { class: 'stat-grid' },
      el('div', { class: 'stat' }, el('div', { class: 'n' }, String(report.n_people)), el('div', { class: 'l' }, `people · ${report.scope}`)),
      report.yearly_unclaimed_text ? el('div', { class: 'stat' }, el('div', { class: 'n' }, report.yearly_unclaimed_text),
        el('div', { class: 'l' }, 'a year in schemes they qualify for but have not applied to')) : null),
    el('h2', {}, 'Schemes'),
    table(['Scheme', 'Qualify', 'Applied', 'Not yet applied'],
      report.schemes.map((s) => [s.name, s.eligible, s.applied, s.not_applied])),
    el('h2', {}, 'Papers most needed'),
    table(['Document', 'People who need it'], report.documents_needed.map((d) => [d.label, d.people])),
    el('h2', {}, 'Where'),
    table(['District', 'People'], report.districts.map((d) => [d.district, d.people])));
}

(async function init() {
  const { camps } = await api.camps();
  const wanted = new URLSearchParams(location.search).get('camp') || '';
  $('scope').replaceChildren(el('option', { value: '' }, 'Everyone saved here'),
    ...camps.map((c) => el('option', { value: c.id }, c.name)));
  $('scope').value = wanted;
  $('scope').addEventListener('change', () => {
    history.replaceState(null, '', $('scope').value ? `/reports?camp=${$('scope').value}` : '/reports');
    render($('scope').value);
  });
  await render(wanted);
}());
