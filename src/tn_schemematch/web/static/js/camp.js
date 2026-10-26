/* Camp mode: screen many families in a day.

   One form per person — the few questions that decide most schemes — saved with the
   person's consent, then a line in the queue with what they qualify for and what to
   collect. Everything deeper (documents, applications) is on their profile page. */

import { api, el, $ } from './api.js';

let campId = null;
let intake = [];
let consentLang = 'en';

function control(field) {
  if (field.type === 'bool') {
    return el('select', { name: field.name }, el('option', { value: '' }, '—'),
      el('option', { value: 'true' }, 'Yes'), el('option', { value: 'false' }, 'No'));
  }
  if (field.type === 'enum') {
    return el('select', { name: field.name }, el('option', { value: '' }, '—'),
      ...field.options.map((o) => el('option', { value: o.value }, o.label)));
  }
  return el('input', { name: field.name, type: 'text', inputmode: 'decimal',
    placeholder: field.unit_text || '', 'aria-label': field.label });
}

function renderIntake() {
  $('intake-fields').replaceChildren(...intake.map((field) => el('label', { class: 'field' },
    el('span', { class: 'tiny muted' }, field.label), control(field))));
}

async function renderConsent(lang) {
  consentLang = lang;
  const notice = await api.notice(lang);
  $('consent-langs').replaceChildren(...[['en', 'English'], ['ta', 'தமிழ்'], ['ml', 'മലയാളം']].map(([code, label]) =>
    el('button', { type: 'button', class: `btn small${code === lang ? ' primary' : ''}`, onclick: () => renderConsent(code) }, label)));
  $('consent-text').replaceChildren(el('b', {}, notice.title),
    el('ul', { class: 'tiny' }, ...notice.points.map((point) => el('li', {}, point))));
}

async function loadCamps() {
  const { camps, intake: fields } = await api.camps();
  intake = fields;
  $('camps').replaceChildren(...(camps.length ? camps.map((camp) => el('button', {
    type: 'button', class: `person${camp.id === campId ? ' on' : ''}`, onclick: () => openCamp(camp.id),
  }, el('b', {}, camp.name), el('span', { class: 'tiny muted' },
    [camp.place, camp.held_on, `${camp.n_people} people`].filter(Boolean).join(' · '))))
    : [el('p', { class: 'tiny muted' }, 'No camps yet.')]));
}

function queueRow(person) {
  return el('div', { class: 'scheme-row' },
    el('div', {},
      el('b', {}, person.name), person.relation ? el('span', { class: 'tiny muted' }, ` · ${person.relation}`) : null,
      el('div', { class: 'tiny' }, `${person.n_eligible} scheme${person.n_eligible === 1 ? '' : 's'}`,
        person.yearly_text ? ` · at least ${person.yearly_text} a year` : '',
        person.one_time_text ? ` · ${person.one_time_text} one-time` : ''),
      person.schemes.length ? el('div', { class: 'tiny muted' }, person.schemes.join(', ')) : null,
      person.documents_to_collect.length ? el('div', { class: 'tiny' }, 'Collect: ', person.documents_to_collect.join(', ')) : null,
      person.n_undetermined ? el('div', { class: 'tiny muted' }, `${person.n_undetermined} schemes need more answers — open the profile`) : null),
    el('div', { class: 'row', style: 'flex-wrap:nowrap;gap:6px' },
      el('a', { class: 'btn small', href: `/print/${person.id}`, target: '_blank' }, 'Print'),
      el('a', { class: 'btn small', href: `/profile?id=${person.id}` }, 'Profile')));
}

async function openCamp(id) {
  campId = id;
  await loadCamps();
  const { camp, people } = await api.camp(id);
  $('camp-empty').hidden = true;
  $('camp-view').hidden = false;
  $('camp-title').textContent = camp.name;
  $('camp-meta').textContent = [camp.place, camp.held_on].filter(Boolean).join(' · ');
  $('camp-print').href = `/print/camp/${id}`;
  $('camp-report').href = `/reports?camp=${id}`;
  $('queue-count').textContent = `· ${people.length}`;
  $('queue').replaceChildren(...(people.length ? people.slice().reverse().map(queueRow)
    : [el('p', { class: 'tiny muted' }, 'Nobody yet.')]));
  $('intake-family').replaceChildren(el('option', { value: '' }, 'New family'),
    ...people.map((p) => el('option', { value: p.id }, `Same family as ${p.name}`)));
  history.replaceState(null, '', `/camp?id=${id}`);
}

$('new-camp').addEventListener('submit', async (event) => {
  event.preventDefault();
  const camp = await api.createCamp({ name: $('camp-name').value, place: $('camp-place').value,
    held_on: $('camp-date').value || undefined });
  $('new-camp').reset();
  await openCamp(camp.id);
});

$('intake').addEventListener('submit', async (event) => {
  event.preventDefault();
  const note = $('intake-note');
  if (!$('consent-given').checked) {
    note.textContent = 'Read the notice and tick “They agree” first.';
    note.className = 'tiny err';
    return;
  }
  const facts = {};
  for (const field of $('intake-fields').querySelectorAll('[name]')) {
    if (field.value === '') continue;
    facts[field.name] = field.value === 'true' ? true : field.value === 'false' ? false : field.value;
  }
  $('intake-go').disabled = true;
  try {
    const person = await api.intake(campId, {
      name: $('intake-name').value, relation: $('intake-relation').value,
      household_of: $('intake-family').value || undefined, facts, consent: true, lang: consentLang,
    });
    note.textContent = `${person.name}: ${person.n_eligible} scheme(s).`;
    note.className = 'tiny';
    $('intake').reset();
    renderConsent(consentLang);
    await openCamp(campId);
  } catch (error) {
    const fields = error.payload?.error?.fields;
    note.textContent = fields ? Object.entries(fields).map(([k, v]) => `${k}: ${v}`).join('; ') : error.message;
    note.className = 'tiny err';
  } finally {
    $('intake-go').disabled = false;
  }
});

(async function init() {
  await loadCamps();
  renderIntake();
  renderConsent('en');
  const wanted = new URLSearchParams(location.search).get('id');
  if (wanted) await openCamp(wanted);
}());
