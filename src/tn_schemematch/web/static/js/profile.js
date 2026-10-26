/* The profile page: one person's facts, documents, schemes and checklist.

   Everything here is a view of the vault. Editing a fact posts it and redraws from the
   response, which carries the eligibility diff — so a life event shows its consequence
   ("now eligible for the old-age pension") right where it was made. */

import { api, el, $ } from './api.js';
import { checklistView, sourceBadge } from './cards.js';
import { currentProfile, rememberProfile } from './picker.js';
import {
  applicationsView, calendarView, familyView, moneyLine, onlyOneOf, trackButtons, unlockView,
} from './planning.js';

let pid = null;
let people = [];
let docTypes = {};
let attributes = {};
let reasons = [];
let tracked = new Set();

/* ------------------------------------------------------------- helpers */

function ago(seconds) {
  if (!seconds) return '';
  const delta = Date.now() / 1000 - seconds;
  if (delta < 60) return 'just now';
  if (delta < 3600) return `${Math.round(delta / 60)} min ago`;
  if (delta < 86400) return `${Math.round(delta / 3600)} h ago`;
  return new Date(seconds * 1000).toLocaleDateString();
}

function flash(node, text, klass = '') {
  node.replaceChildren(el('div', { class: `tiny ${klass}` }, text));
}

/* ---------------------------------------------------------------- people */

async function loadPeople() {
  ({ profiles: people } = await api.profiles());
  $('people').replaceChildren(...(people.length ? people.map((person) => el('button', {
    class: `person${person.id === pid ? ' on' : ''}`, type: 'button', onclick: () => select(person.id),
  }, el('b', {}, person.name),
    el('span', { class: 'tiny muted' },
      [person.relation, `${person.n_facts} facts`, `${person.n_documents} docs`].filter(Boolean).join(' · '))))
    : [el('p', { class: 'tiny muted' }, 'Nobody saved yet.')]));
  $('same-household-label').hidden = !pid;
}

async function select(id, { push = true } = {}) {
  pid = id;
  rememberProfile(pid);
  if (push) history.replaceState(null, '', pid ? `/profile?id=${pid}` : '/profile');
  await loadPeople();
  $('empty').hidden = Boolean(pid);
  $('profile-view').hidden = !pid;
  if (!pid) return;
  const [detail, eligibility, checklist] = await Promise.all([
    api.profile(pid), api.eligibility(pid), api.checklist(pid)]);
  renderHead(detail);
  renderChanges(null);
  await refreshApplications();
  renderSchemes(eligibility);
  renderDocuments(detail.documents);
  renderChecklist(checklist);
  renderFacts(detail.facts);
  refreshOutlook(detail);
  renderPrivacy(detail.consent);
}

/* Unlock, calendar and family depend on every fact, so they redraw after any change. */
async function refreshOutlook(detail) {
  const [unlock, calendar] = await Promise.all([api.unlock(pid), api.calendar(pid)]);
  $('unlock').replaceChildren(unlockView(unlock));
  $('calendar').replaceChildren(calendarView(calendar.items));
  const family = (detail || await api.profile(pid)).household;
  $('family-card').hidden = !family.length;
  if (family.length) {
    const household = await api.household(pid);
    $('family').replaceChildren(familyView(household, pid, (id) => select(id)));
  }
}

async function refreshApplications() {
  const { applications } = await api.applications(pid);
  tracked = new Set(applications.map((a) => a.scheme_id));
  $('applications').replaceChildren(applicationsView(pid, applications, reasons, async () => {
    await refreshApplications();
    renderSchemes(await api.eligibility(pid));
    refreshOutlook();
  }));
}

async function renderPrivacy(consent) {
  const box = $('privacy');
  const log = (await api.audit(pid)).log;
  box.replaceChildren(
    consent
      ? el('div', { class: 'tiny' }, el('span', { class: 'badge ok' }, 'consent recorded'),
        ` ${new Date(consent.given_at * 1000).toLocaleDateString('en-IN')}, given by ${consent.given_by === 'self' ? 'the person' : 'a helper on their behalf'}, notice of ${consent.notice}.`)
      : el('div', { class: 'tiny' }, el('span', { class: 'badge open' }, 'no consent recorded'), ' ',
        el('button', { class: 'btn small', type: 'button', onclick: async () => {
          await api.giveConsent(pid, { given_by: 'self', lang: 'en' });
          renderPrivacy((await api.profile(pid)).consent);
        } }, 'Record consent now')),
    el('div', { class: 'row' },
      el('a', { class: 'btn small', href: `/api/profiles/${pid}/export` }, 'Download all my data'),
      el('a', { class: 'btn small', href: `/print/${pid}`, target: '_blank' }, 'Print my sheet')),
    el('details', { class: 'tiny' }, el('summary', {}, `Who opened or changed this profile (${log.length})`),
      el('ul', { class: 'audit' }, ...log.slice(0, 50).map((entry) => el('li', {},
        el('span', { class: 'mono muted' }, new Date(entry.at * 1000).toLocaleString('en-IN')), ' ',
        entry.actor, ' — ', entry.action, entry.detail ? ` (${entry.detail})` : '')))),
    el('p', { class: 'tiny muted' }, 'To withdraw consent, delete this person (button at the top): every fact and photo goes with it.'));
}

function renderHead(detail) {
  const { profile, household } = detail;
  $('p-name').textContent = profile.name;
  $('p-meta').textContent = [
    profile.relation,
    household.length ? `family: ${household.map((p) => p.name).join(', ')}` : null,
    `saved ${ago(profile.created_at)}`,
  ].filter(Boolean).join(' · ');
}

/* --------------------------------------------------------------- schemes */

function renderChanges(changes) {
  const box = $('changes');
  if (!changes || changes.first_check || (!changes.gained.length && !changes.lost.length)) {
    box.replaceChildren();
    return;
  }
  box.replaceChildren(el('section', { class: 'card changes' },
    el('div', { class: 'eyebrow' }, 'What that changed'),
    ...changes.gained.map((s) => el('div', { class: 'gain' }, '+ Now eligible: ', el('b', {}, s.name))),
    ...changes.lost.map((s) => el('div', { class: 'loss' }, '− No longer eligible: ', el('b', {}, s.name)))));
}

function renderSchemes(result) {
  const counts = result.board.counts;
  const box = $('schemes');
  box.replaceChildren(el('div', { class: 'row', style: 'margin-bottom:10px' },
    el('span', { class: 'badge ok' }, `${counts.eligible} eligible`),
    el('span', { class: 'badge no' }, `${counts.ineligible} ruled out`),
    el('span', { class: 'badge open' }, `${counts.undetermined} need more answers`)),
  moneyLine(result.money) || '', onlyOneOf(result.only_one_of) || '');

  if (result.eligible.length) {
    box.append(el('div', { class: 'scheme-rows' }, ...result.eligible.map((s) => el('div', { class: 'scheme-row' },
      el('div', {}, el('b', {}, s.name), s.name_ta ? el('div', { class: 'ta tiny' }, s.name_ta) : null,
        s.name_ml ? el('div', { class: 'ta tiny' }, s.name_ml) : null,
        s.value_text ? el('div', { class: 'worth tiny' }, s.value_text) : null,
        el('div', { class: 'tiny muted' }, (s.benefit_prose || '').split('\n')[0])),
      el('div', { class: 'row', style: 'gap:6px;flex-wrap:nowrap' },
        tracked.has(s.id) ? el('span', { class: 'badge det' }, 'tracked')
          : trackButtons(pid, s, () => refreshApplications().then(() => renderSchemes(result))),
        s.apply_url ? el('a', { class: 'btn small', href: s.apply_url, target: '_blank', rel: 'noopener' }, 'Apply →') : null)))));
  } else {
    box.append(el('p', { class: 'muted tiny' }, 'Nothing is confirmed yet. Answer more questions in the assistant or the interview.'));
  }
  if (result.near_misses.length) {
    box.append(el('details', { class: 'near' },
      el('summary', { class: 'tiny muted' }, `${result.near_misses.length} missed by a single condition`),
      ...result.near_misses.map((m) => el('div', { class: 'tiny' }, el('b', {}, m.name), ' — would qualify if ',
        m.missing.human.toLowerCase()))));
  }
}

/* ------------------------------------------------------------- documents */

function fillTypeSelect(select, { includeAuto }) {
  select.replaceChildren(
    el('option', { value: '' }, includeAuto ? 'Let the model identify it' : 'What is this document?'),
    ...Object.values(docTypes).map((t) => el('option', { value: t.id }, `${t.label} — ${t.label_ta}`)));
}

function conflictRow(doc, conflict) {
  const row = el('div', { class: 'conflict' },
    el('div', { class: 'tiny' }, el('b', {}, conflict.label), `: you said ${conflict.current_display}; `
      + `the document says ${conflict.document_display}.`));
  const choose = async (keep) => {
    const result = await api.resolve(pid, doc.id, conflict.attr, keep);
    renderFacts(result.facts);
    renderSchemes(result.eligibility);
    renderChanges(result.eligibility.changes);
    row.replaceChildren(el('span', { class: 'tiny muted' }, 'Settled.'));
  };
  row.append(el('div', { class: 'row' },
    el('button', { class: 'btn small', onclick: () => choose('document') }, 'Use the document'),
    el('button', { class: 'btn small', onclick: () => choose('mine') }, 'Keep mine')));
  return row;
}

function docTile(doc) {
  const reading = doc.reading || {};
  const type = docTypes[doc.doc_type];
  const status = { read: ['ai', 'read by model'], manual: ['det', 'filed by you'], unread: ['open', 'needs a type'] }[doc.status]
    || ['det', doc.status];
  const tile = el('div', { class: 'doc' },
    el('a', { href: doc.file_url, target: '_blank', rel: 'noopener', class: 'thumb' },
      doc.media_type === 'application/pdf'
        ? el('span', { class: 'pdf-thumb', 'aria-label': 'PDF document' }, 'PDF')
        : el('img', { src: doc.file_url, alt: type ? type.label : 'uploaded document', loading: 'lazy' })),
    el('div', { class: 'doc-body' },
      el('b', {}, type ? type.label : 'Unidentified document'),
      type ? el('div', { class: 'ta tiny' }, type.label_ta) : null,
      el('div', { class: 'row', style: 'gap:6px;margin-top:4px' },
        el('span', { class: `badge ${status[0]}` }, status[1]),
        el('span', { class: 'tiny muted' }, ago(doc.uploaded_at))),
      reading.facts?.length ? el('ul', { class: 'doc-facts tiny' }, ...reading.facts.map((f) => el('li', {},
        `${f.label}: `, el('b', {}, f.display), f.implied ? el('span', { class: 'muted' }, ' (from having it)') : null)))
        : null,
      reading.type_mismatch ? el('div', { class: 'tiny notice' }, 'This did not look like the type you chose.') : null,
      reading.rejected?.length ? el('details', { class: 'tiny' },
        el('summary', { class: 'muted' }, `${reading.rejected.length} value(s) ignored`),
        ...reading.rejected.map((r) => el('div', { class: 'muted' }, `${r.attr}: ${r.reason}`))) : null,
      ...(reading.conflicts || []).map((c) => conflictRow(doc, c))));

  const body = tile.querySelector('.doc-body');
  if (doc.status === 'unread') {
    const select = el('select', {});
    fillTypeSelect(select, { includeAuto: false });
    body.append(el('div', { class: 'row', style: 'margin-top:6px' }, select,
      el('button', { class: 'btn small', onclick: async () => {
        if (!select.value) return;
        const result = await api.setDocumentType(pid, doc.id, select.value);
        afterDocumentChange(result);
      } }, 'Set type')));
  }
  body.append(el('button', { class: 'btn ghost danger tiny', onclick: async () => {
    if (!window.confirm('Delete this photo? Facts already read from it stay saved.')) return;
    await api.deleteDocument(pid, doc.id);
    await refreshDocuments();
  } }, 'Delete photo'));
  return tile;
}

function renderDocuments(documents) {
  $('documents').replaceChildren(...(documents.length ? documents.map(docTile)
    : [el('p', { class: 'tiny muted' }, 'No documents yet. Upload a photo of a ration card, income certificate, Aadhaar…')]));
}

async function refreshDocuments() {
  const [detail, checklist, eligibility] = await Promise.all([
    api.profile(pid), api.checklist(pid), api.eligibility(pid)]);
  renderDocuments(detail.documents);
  renderChecklist(checklist);
  renderFacts(detail.facts);
  renderSchemes(eligibility);
  renderChanges(eligibility.changes);
  refreshOutlook();
  loadPeople();
}

function afterDocumentChange(result) {
  renderFacts(result.facts);
  renderSchemes(result.eligibility);
  renderChanges(result.eligibility.changes);
  renderChecklist(result.checklist);
  api.profile(pid).then((detail) => renderDocuments(detail.documents));
  loadPeople();
}

async function upload(event) {
  event.preventDefault();
  const file = $('upload-file').files[0];
  const note = $('upload-note');
  if (!file) { flash(note, 'Choose a photo first.', 'notice'); return; }
  const chosen = $('upload-type').value || null;
  if (!window.CAN_READ && !chosen) { flash(note, 'Choose what kind of document it is.', 'notice'); return; }
  $('upload-go').disabled = true;
  note.replaceChildren(el('span', { class: 'spinner' }), window.CAN_READ ? ' reading the photo…' : ' filing…');
  try {
    const result = await api.upload(pid, file, chosen);
    const added = result.applied.length + result.confirmed.length;
    flash(note, `${result.type_label || 'Document'} saved. ${added} fact(s) added or confirmed`
      + `${result.conflicts.length ? `, ${result.conflicts.length} to check below` : ''}.`);
    $('upload-form').reset();
    afterDocumentChange(result);
  } catch (error) {
    flash(note, error.message, 'err');
  } finally {
    $('upload-go').disabled = false;
  }
}

/* ------------------------------------------------------------- checklist */

function renderChecklist(checklist) {
  $('checklist').replaceChildren(checklistView(checklist, {
    onUpload: (type) => {
      $('upload-type').value = type;
      $('docs-card').scrollIntoView({ behavior: 'smooth' });
      $('upload-file').click();
    },
  }));
}

/* ------------------------------------------------------------------ facts */

function editorFor(attr, current, onDone) {
  const form = attributes[attr];
  let input;
  if (form.type === 'bool') {
    input = el('select', {}, el('option', { value: 'true' }, 'Yes'), el('option', { value: 'false' }, 'No'));
    if (current !== undefined) input.value = String(current);
  } else if (form.type === 'enum') {
    input = el('select', {}, ...form.options.map((o) => el('option', { value: o.value }, o.label)));
    if (current !== undefined) input.value = current;
  } else {
    input = el('input', { type: 'number', step: 'any', min: form.min, max: form.max, value: current ?? '' });
  }
  const status = el('span', { class: 'tiny' });
  const save = async () => {
    let value = input.value;
    if (form.type === 'bool') value = value === 'true';
    if (form.type === 'number') { if (value === '') return; value = Number(value); }
    try {
      const result = await api.recordFact(pid, { attr, value });
      renderFacts(result.facts);
      renderSchemes(result.eligibility);
      renderChanges(result.eligibility.changes);
      api.checklist(pid).then(renderChecklist);
      refreshOutlook();
      loadPeople();
      onDone?.();
    } catch (error) {
      status.textContent = error.message;
      status.className = 'tiny err';
    }
  };
  return el('span', { class: 'editor' }, input,
    form.unit_text ? el('span', { class: 'tiny muted' }, form.unit_text) : null,
    el('button', { class: 'btn small', type: 'button', onclick: save }, 'Save'), status);
}

function renderFacts(facts) {
  $('facts-count').textContent = `· ${facts.filter((f) => !f.derived).length} facts`;
  const table = $('facts');
  table.replaceChildren(el('thead', {}, el('tr', {},
    el('th', {}, 'Fact'), el('th', {}, 'Value'), el('th', {}, 'Source'), el('th', {}, 'Said or read as'), el('th', {}, ''))));
  const body = el('tbody');
  facts.forEach((fact) => {
    const valueCell = el('td', {}, el('b', {}, fact.display));
    const actions = el('td', { class: 'actions' });
    if (!fact.derived && attributes[fact.attr]) {
      actions.append(
        el('button', { class: 'btn ghost tiny', type: 'button', onclick: () => {
          valueCell.replaceChildren(editorFor(fact.attr, fact.value));
        } }, 'change'),
        el('button', { class: 'btn ghost tiny', type: 'button', title: 'forget this fact', onclick: async () => {
          const result = await api.recordFact(pid, { attr: fact.attr, value: null });
          renderFacts(result.facts);
          renderSchemes(result.eligibility);
          renderChanges(result.eligibility.changes);
        } }, '×'));
    }
    body.append(el('tr', { class: fact.derived ? 'derived' : '' },
      el('td', {}, fact.label, el('div', { class: 'mono tiny muted' }, fact.attr)),
      valueCell,
      el('td', {}, sourceBadge(fact.source), el('div', { class: 'tiny muted' }, ago(fact.recorded_at))),
      el('td', { class: 'evidence' }, fact.evidence ? `“${fact.evidence}”` : ''),
      actions));
  });
  table.append(body);

  // "Add a fact": any stateable attribute not already known.
  const known = new Set(facts.map((f) => f.attr));
  const pick = el('select', {}, el('option', { value: '' }, 'Choose…'),
    ...Object.values(attributes).filter((a) => !known.has(a.name))
      .map((a) => el('option', { value: a.name }, a.label)));
  const slot = el('span');
  pick.addEventListener('change', () => slot.replaceChildren(pick.value
    ? editorFor(pick.value, undefined, () => { $('add-fact').open = false; }) : ''));
  $('add-fact-row').replaceChildren(pick, slot);
}

/* -------------------------------------------------------------- listeners */

$('upload-form').addEventListener('submit', upload);
$('p-delete').addEventListener('click', async () => {
  const person = people.find((p) => p.id === pid);
  if (!window.confirm(`Delete ${person?.name || 'this person'} and every fact and photo saved for them?`)) return;
  await api.deleteProfile(pid);
  rememberProfile(null);
  await loadPeople();
  await select(people[0]?.id || null);
});
$('new-person').addEventListener('submit', async (event) => {
  event.preventDefault();
  const sameFamily = pid && $('same-household').checked;
  const created = await api.createProfile($('new-name').value.trim(), $('new-relation').value.trim(),
    sameFamily ? pid : null);
  await api.giveConsent(created.id, { given_by: 'self', lang: 'en' });
  $('new-person').reset();
  $('same-household').checked = true;
  await select(created.id);
});

(async function init() {
  const [types, attrs, why] = await Promise.all([
    api.documentTypes(), api.attributes(), api.rejectionReasons()]);
  reasons = why.reasons;
  types.types.forEach((t) => { docTypes[t.id] = t; });
  attrs.attributes.forEach((a) => { attributes[a.name] = a; });
  fillTypeSelect($('upload-type'), { includeAuto: types.can_read });
  api.notice('en').then((notice) => $('new-consent-text').replaceChildren(
    el('ul', {}, ...notice.points.map((point) => el('li', {}, point)))));

  ({ profiles: people } = await api.profiles());
  const wanted = new URLSearchParams(location.search).get('id') || currentProfile();
  const start = people.some((p) => p.id === wanted) ? wanted : (people[0]?.id || null);
  await select(start, { push: Boolean(start) });
}());
