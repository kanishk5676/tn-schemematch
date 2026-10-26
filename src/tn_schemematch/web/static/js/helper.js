/* The helper's page: everyone saved on this computer, most actionable first.

   One card per person: what they can get, papers still to collect, schemes one condition
   away, what opens soon, and where each application stands. Every decision on it comes
   from the server's rule engine; this file only draws and records. */

import { api, el, $ } from './api.js';
import { lang, t } from './i18n.js';
import { rememberProfile } from './picker.js';

const STATUSES = ['planned', 'applied', 'sanctioned', 'rejected'];

const post = async (url, body) => {
  const response = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data?.error?.message || 'error');
    error.code = data?.error?.code;
    throw error;
  }
  return data;
};

function stat(n, label, warn = false) {
  return el('div', { class: `stat${warn ? ' warn' : ''}` }, el('div', { class: 'n' }, String(n)), el('div', { class: 'l' }, label));
}

function talkTo(pid) {
  rememberProfile(pid);
  try { sessionStorage.removeItem('udhavi.chat'); } catch { /* storage blocked */ }
  window.location.href = `/?profile=${pid}`;
}

function applicationRow(person, scheme) {
  const current = person.applications.find((a) => a.scheme_id === scheme.id);
  const status = el('select', { 'aria-label': t('status') },
    el('option', { value: '' }, '—'),
    ...STATUSES.map((s) => el('option', { value: s }, t(`status_${s}`))));
  status.value = current?.status || '';
  const reference = el('input', { type: 'text', maxlength: '60', placeholder: t('reference'), value: current?.reference || '' });
  const when = el('input', { type: 'date', value: current?.applied_on || '' });
  const note = el('span', { class: 'tiny muted' });
  const save = async () => {
    if (!status.value) return;
    try {
      await post(`/api/profiles/${person.id}/applications`, {
        scheme_id: scheme.id, status: status.value, reference: reference.value,
        applied_on: when.value || null,
      });
      note.textContent = '✓';
    } catch (error) { note.textContent = error.message; }
  };
  [status, reference, when].forEach((field) => field.addEventListener('change', save));
  return el('li', { class: 'app-row' },
    el('a', { href: `/profile/${person.id}/pack/${scheme.id}?lang=${lang()}` }, `📋 ${scheme.name}`),
    el('div', { class: 'app-fields' }, status, reference, when, note));
}

function personCard(person) {
  const badges = [];
  if (person.follow_up.length) badges.push(el('span', { class: 'badge no' }, `⏰ ${t('follow_up')}: ${person.follow_up.map((a) => a.name).join(', ')}`));
  if (person.conflicts) badges.push(el('span', { class: 'badge open' }, `⚠️ ${t('conflicts')}`));
  if (person.n_eligible) badges.push(el('span', { class: 'badge ok' }, `${person.n_eligible} ${t('schemes')}`));
  if (person.to_collect.length && person.n_eligible) badges.push(el('span', { class: 'badge open' }, `🗂️ ${t('papers_missing')}: ${person.to_collect.length}`));

  const parts = [
    el('div', { class: 'person-head' },
      el('h2', {}, person.name, person.relation ? el('span', { class: 'muted' }, ` · ${person.relation}`) : null),
      el('div', { class: 'row' }, ...badges)),
  ];
  if (person.to_collect.length && person.n_eligible) {
    parts.push(el('p', {}, el('b', {}, `${t('bring_title')}: `), person.to_collect.join(', ')));
  }
  if (person.near.length) {
    parts.push(el('p', {}, el('b', {}, `${t('near_title')}: `),
      person.near.map((n) => `${n.name} (${n.missing})`).join('; ')));
  }
  if (person.soon.length) {
    parts.push(el('p', {}, el('b', {}, `⏳ ${t('later_title')}: `),
      person.soon.map((s) => `${s.name} — ${t('later_at', { age: s.at_age, years: s.in_years })}`).join('; ')));
  }
  if (person.eligible.length) {
    parts.push(el('ul', { class: 'apps' }, ...person.eligible.map((scheme) => applicationRow(person, scheme))));
  } else if (!person.n_facts) {
    parts.push(el('p', { class: 'muted' }, t('no_answers_yet')));
  }
  parts.push(el('div', { class: 'row person-actions' },
    el('button', { type: 'button', class: 'btn primary', onclick: () => talkTo(person.id) }, `🎤 ${t('nav_assistant')}`),
    el('a', { class: 'btn', href: `/profile?id=${person.id}` }, t('nav_profile')),
    el('a', { class: 'btn', href: '/interview' }, t('detailed_check'))));
  return el('article', { class: 'card person' }, ...parts);
}

async function load() {
  const data = await (await fetch(`/api/helper/overview?lang=${lang()}`)).json();
  const totals = data.totals;
  $('totals').replaceChildren(
    stat(totals.people, t('people')),
    stat(totals.households, t('families')),
    stat(totals.schemes_found, t('schemes_found')),
    stat(totals.papers_missing, t('papers_missing'), true),
    stat(totals.follow_up, t('follow_up'), true),
    stat(totals.applied, t('applied')));
  $('people').replaceChildren(...(data.people.length
    ? data.people.map(personCard)
    : [el('p', { class: 'muted card' }, t('nobody_yet'))]));
  const households = new Map();
  data.people.forEach((p) => { if (!households.has(p.household)) households.set(p.household, p); });
  $('add-household').replaceChildren(el('option', { value: '' }, t('new_family')),
    ...[...households.values()].map((p) => el('option', { value: p.id }, `${p.name}${p.relation ? ` (${p.relation})` : ''}`)));
}

async function show() {
  const me = await (await fetch('/api/helper/me')).json();
  const in_ = me.helper;
  $('login').hidden = in_;
  $('desk').hidden = !in_;
  $('logout').hidden = !me.pin_required;
  if (in_) await load(); else $('pin').focus();
}

$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('login-error').textContent = '';
  try {
    await post('/api/helper/login', { pin: $('pin').value });
    $('pin').value = '';
    await show();
  } catch (error) {
    $('login-error').textContent = error.code === 'too_many_tries' ? t('too_many_tries') : t('wrong_pin');
  }
});
$('logout').addEventListener('click', async () => { await post('/api/helper/logout'); await show(); });
$('refresh').addEventListener('click', load);
$('add-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const profile = await api.createProfile($('add-name').value.trim(), $('add-relation').value.trim(),
    $('add-household').value || null);
  talkTo(profile.id);
});
document.addEventListener('languagechange', () => { if (!$('desk').hidden) load(); });

show();
