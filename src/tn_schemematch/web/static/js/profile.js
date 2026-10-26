/* The profile page: one person's facts, documents, schemes and checklist.

   Everything here is a view of the vault. Editing a fact posts it and redraws from the
   response, which carries the eligibility diff — so a life event shows its consequence
   ("now eligible for the old-age pension") right where it was made. */

import { api, el, $ } from './api.js';
import { checklistView, sourceBadge } from './cards.js';
import { currentProfile, rememberProfile } from './picker.js';
import { lang, sectorIcon, t } from './i18n.js';

let pid = null;
let people = [];
let docTypes = {};
let attributes = {};

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
  renderSchemes(eligibility);
  renderDocuments(detail.documents);
  renderChecklist(checklist);
  renderFacts(detail.facts);
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
    el('span', { class: 'badge open' }, `${counts.undetermined} need more answers`)));

  if (result.eligible.length) {
    // Plain words first, in the reader's language; the official name small underneath.
    box.append(el('div', { class: 'scheme-rows' }, ...result.eligible.map((s) => {
      const plain = (s.plain && s.plain[lang()]) || {};
      return el('div', { class: 'scheme-row' },
        el('div', {},
          el('b', {}, `${sectorIcon(s.sectors)} ${plain.name || s.name}`),
          plain.what ? el('div', { class: 'tiny' }, plain.what) : null,
          el('div', { class: 'tiny muted' }, `${t('official_name')}: ${s.name}`)),
        el('div', { class: 'row' },
          el('a', { class: 'btn small primary', href: `/profile/${pid}/pack/${s.id}?lang=${lang()}` }, `📋 ${t('pack')}`),
          s.apply_url ? el('a', { class: 'btn small', href: s.apply_url, target: '_blank', rel: 'noopener' }, t('apply_online')) : null));
    })));
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
  // A photo is deleted once read unless kept; what was read from it stays.
  const thumb = doc.has_photo
    ? el('a', { href: doc.file_url, target: '_blank', rel: 'noopener', class: 'thumb' },
      el('img', { src: doc.file_url, alt: type ? type.label : 'uploaded document', loading: 'lazy' }))
    : el('div', { class: 'thumb gone', title: t('photo_deleted') }, '🗑️', el('span', { class: 'tiny' }, t('photo_deleted')));
  const tile = el('div', { class: 'doc' },
    thumb,
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
    const result = await api.upload(pid, file, chosen, $('upload-keep').checked);
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
      el('td', { title: fact.attr }, fact.label),
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
  $('new-person').reset();
  $('same-household').checked = true;
  await select(created.id);
});

(async function init() {
  const [types, attrs] = await Promise.all([api.documentTypes(), api.attributes()]);
  types.types.forEach((t) => { docTypes[t.id] = t; });
  attrs.attributes.forEach((a) => { attributes[a.name] = a; });
  fillTypeSelect($('upload-type'), { includeAuto: types.can_read });

  ({ profiles: people } = await api.profiles());
  const wanted = new URLSearchParams(location.search).get('id') || currentProfile();
  const start = people.some((p) => p.id === wanted) ? wanted : (people[0]?.id || null);
  await select(start, { push: Boolean(start) });
}());
