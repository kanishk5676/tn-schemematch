/* The assistant page.

   The server holds the conversation; this file draws it. Each reply arrives with three
   things besides its text, and all three are drawn because they are the point:
   - the steps the agent took (which tools, with what result) — collapsed under the reply;
   - the rule engine's verdict on every scheme the reply names — chips under the text;
   - components the agent asked to show — scheme cards, the checklist, upload buttons. */

import { api, el, $ } from './api.js';
import { paintBoard, paintProfile } from './board.js';
import { checklistView, schemeCard, verdictChip } from './cards.js';
import { currentProfile, fillPicker, rememberProfile } from './picker.js';

const CHAT_KEY = 'tnsm.chat';
let chatId = null;
let profileId = null;
let busy = false;
let pendingUploadType = null;

const STARTERS = [
  'enakku ration card irukku, vivasayi, rendu ekkar nilam — enna scheme kedaikum?',
  'naan widow, 55 vayasu, Madurai la irukken. enna udhavi kidaikum?',
  'My daughter is in 12th standard in a government school. Any scholarship?',
  'என் அம்மாவுக்கு 70 வயது. ஓய்வூதியம் கிடைக்குமா?',
];

/* ---------------------------------------------------------------- drawing */

function scrollDown() {
  const box = $('messages');
  box.scrollTop = box.scrollHeight;
}

/** Text with **bold** honoured and everything else literal. */
function richText(text) {
  const out = el('div', { class: 'bubble-text' });
  String(text || '').split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
    if (part.startsWith('**') && part.endsWith('**')) out.append(el('b', {}, part.slice(2, -2)));
    else if (part) out.append(document.createTextNode(part));
  });
  return out;
}

function shortName(name) {
  const acronym = name.match(/\(([^)]{2,25})\)/);
  return acronym ? acronym[1] : name.length > 38 ? `${name.slice(0, 36)}…` : name;
}

function stepsView(steps) {
  if (!steps?.length) return null;
  return el('details', { class: 'steps' },
    el('summary', {}, `${steps.length} step${steps.length === 1 ? '' : 's'} by the agent`),
    el('ol', {}, ...steps.map((step) => el('li', { class: step.ok ? '' : 'err' },
      el('span', { class: 'mono tool' }, step.tool), ' ', el('span', { class: 'muted' }, step.summary)))));
}

function mentionsView(mentions) {
  if (!mentions?.length) return null;
  return el('div', { class: 'mentions', title: 'Every scheme named above, checked against the rule engine' },
    el('span', { class: 'tiny muted' }, 'Rule engine check:'),
    ...mentions.map((m) => verdictChip(m.verdict, shortName(m.name))));
}

function uiView(action) {
  if (action.type === 'scheme') {
    return schemeCard(action.scheme, { verdict: action.scheme.trace?.verdict });
  }
  if (action.type === 'checklist') {
    return el('div', { class: 'card inline' }, checklistView(action.checklist, { onUpload: requestUpload }));
  }
  if (action.type === 'upload') {
    return el('button', { class: 'btn', onclick: () => requestUpload(action.doc_type) },
      `📎 Upload ${action.label ? `your ${action.label.toLowerCase()}` : 'a document'}`);
  }
  if (action.type === 'save_profile') {
    return profileId ? null
      : el('button', { class: 'btn primary', onclick: () => saveProfile() }, 'Save my profile');
  }
  if (action.type === 'link') {
    return el('a', { class: 'btn', href: action.href }, `${action.label} →`);
  }
  return null;
}

function addUser(text) {
  $('messages').append(el('div', { class: 'msg user' }, el('div', { class: 'bubble' }, richText(text))));
  scrollDown();
}

function addAssistant(turn, { note = false } = {}) {
  const ui = (turn.ui || []).map(uiView).filter(Boolean);
  $('messages').append(el('div', { class: `msg bot${note ? ' note' : ''}` },
    el('div', { class: 'bubble' },
      richText(turn.reply || turn.text),
      mentionsView(turn.mentions)),
    ui.length ? el('div', { class: 'ui-actions' }, ...ui) : null,
    stepsView(turn.steps)));
  scrollDown();
}

function addNote(...children) {
  const node = el('div', { class: 'msg bot note' }, el('div', { class: 'bubble' }, ...children));
  $('messages').append(node);
  scrollDown();
  return node;
}

function greet() {
  addAssistant({ reply: 'Vanakkam! 🙏 Tell me a little about yourself — your work, your age, '
    + 'where you live — and I will find the schemes you can get.\n'
    + 'தமிழிலோ ஆங்கிலத்திலோ பேசலாம்.' }, { note: true });
}

function paint(data) {
  paintBoard(data.board);
  paintProfile(data.profile);
  if ('profile_id' in data) setProfile(data.profile_id, data.profile_name);
}

function setProfile(pid, name) {
  profileId = pid || null;
  rememberProfile(profileId);
  $('save').hidden = Boolean(profileId);
  $('open-profile').href = profileId ? `/profile?id=${profileId}` : '/profile';
  $('who-note').textContent = profileId
    ? `Everything you tell me is saved to ${name || 'this profile'}.`
    : 'Not saved yet — your answers are forgotten when you leave.';
}

/* ------------------------------------------------------------- the chat */

async function startChat(pid) {
  const data = await api.startChat(pid);
  chatId = data.chat_id;
  try { sessionStorage.setItem(CHAT_KEY, chatId); } catch { /* fine */ }
  $('messages').replaceChildren();
  paint(data);
  greet();
  showStarters(true);
}

async function resumeChat(id) {
  const data = await api.chat(id);
  chatId = id;
  $('messages').replaceChildren();
  paint(data);
  greet();
  data.transcript.forEach((entry) => (entry.role === 'user' ? addUser(entry.text) : addAssistant(entry)));
  showStarters(!data.transcript.length);
  $('who').value = data.profile_id || '';
}

function showStarters(visible) {
  $('starters').replaceChildren(...(visible ? STARTERS.map((text) => el('button',
    { class: 'sample', type: 'button', onclick: () => send(text) }, text)) : []));
}

async function send(text) {
  text = (text || '').trim();
  if (!text || busy) return;
  busy = true;
  $('send').disabled = true;
  showStarters(false);
  addUser(text);
  $('input').value = '';
  autosize();
  const thinking = addNote(el('span', { class: 'spinner' }), ' thinking…');
  try {
    const turn = await api.say(chatId, text);
    thinking.remove();
    addAssistant(turn);
    paint(turn);
  } catch (error) {
    thinking.remove();
    addNote(el('span', { class: 'err' }, error.message));
    if (error.code === 'no_such_chat') await startChat(profileId);
  } finally {
    busy = false;
    $('send').disabled = false;
    $('input').focus();
  }
}

/* ------------------------------------------------------- profile & upload */

function askName() {
  const dialog = $('save-dialog');
  $('save-name').value = '';
  dialog.showModal();
  $('save-name').focus();
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => resolve(
      dialog.returnValue === 'save' ? $('save-name').value.trim() : null), { once: true });
  });
}

async function saveProfile() {
  if (profileId) return profileId;
  const name = await askName();
  if (!name) return null;
  const saved = await api.save(chatId, { name });
  setProfile(saved.profile_id, saved.profile.name);
  await fillPicker($('who'), { selected: saved.profile_id });
  addNote(`Saved as ${saved.profile.name}. I will remember this next time. `,
    el('a', { href: `/profile?id=${saved.profile_id}` }, 'Open your profile →'));
  return saved.profile_id;
}

async function requestUpload(docType) {
  if (!(await saveProfile())) return;
  pendingUploadType = docType || null;
  $('file').click();
}

function readingSummary(result) {
  const reading = result.reading;
  const label = (result.type_label || 'document').toLowerCase();
  const parts = [el('b', {}, `📄 ${reading.mode === 'model' ? 'Read' : 'Filed'} your ${label}.`)];
  const applied = [...result.applied, ...result.confirmed];
  if (applied.length) {
    parts.push(el('div', { class: 'tiny' }, 'Saved: ',
      applied.map((f) => `${f.label} = ${f.display}`).join(', ')));
  }
  if (reading.rejected?.length) {
    parts.push(el('div', { class: 'tiny muted' },
      `Ignored ${reading.rejected.length} thing(s) this kind of document cannot prove.`));
  }
  if (result.document.status === 'unread') {
    parts.push(el('div', { class: 'tiny' }, 'I could not tell what this is. ',
      el('a', { href: `/profile?id=${profileId}` }, 'Choose its type on your profile →')));
  }
  result.conflicts.forEach((conflict) => {
    const row = el('div', { class: 'conflict' },
      el('div', {}, el('b', {}, conflict.label), `: you said ${conflict.current_display}, `
        + `the document says ${conflict.document_display}.`));
    const choose = async (keep) => {
      const outcome = await api.resolve(profileId, result.document.id, conflict.attr, keep);
      row.replaceChildren(el('span', { class: 'tiny muted' },
        `Kept ${keep === 'document' ? conflict.document_display : conflict.current_display}.`));
      paintBoard(outcome.eligibility.board);
    };
    row.append(el('div', { class: 'row' },
      el('button', { class: 'btn small', onclick: () => choose('document') }, 'Use the document'),
      el('button', { class: 'btn small', onclick: () => choose('mine') }, 'Keep mine')));
    parts.push(row);
  });
  return parts;
}

async function uploadFile(file) {
  const working = addNote(el('span', { class: 'spinner' }), ` reading ${file.name}…`);
  try {
    const result = await api.upload(profileId, file, pendingUploadType);
    working.remove();
    addNote(...readingSummary(result));
    paintBoard(result.eligibility.board);
    // Tell the agent, so its next reply knows the document is on file.
    if (result.document.status !== 'unread') {
      await send(`I uploaded my ${(result.type_label || 'document').toLowerCase()}.`);
    }
  } catch (error) {
    working.remove();
    if (error.code === 'needs_type') {
      addNote('Choose what kind of document it is on your profile page. ',
        el('a', { href: `/profile?id=${profileId}` }, 'Open profile →'));
    } else {
      addNote(el('span', { class: 'err' }, error.message));
    }
  } finally {
    pendingUploadType = null;
    $('file').value = '';
  }
}

/* -------------------------------------------------------------- listeners */

function autosize() {
  const box = $('input');
  box.style.height = 'auto';
  box.style.height = `${Math.min(box.scrollHeight, 160)}px`;
}

$('composer').addEventListener('submit', (event) => { event.preventDefault(); send($('input').value); });
$('input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    send($('input').value);
  }
});
$('input').addEventListener('input', autosize);
$('attach').addEventListener('click', () => requestUpload(null));
$('file').addEventListener('change', () => { if ($('file').files[0]) uploadFile($('file').files[0]); });
$('save').addEventListener('click', () => saveProfile());
$('who').addEventListener('change', async () => {
  const hasTalk = $('messages').querySelectorAll('.msg.user').length > 0;
  if (hasTalk && !profileId && !window.confirm('Start a new conversation? This one is not saved.')) {
    $('who').value = '';
    return;
  }
  await startChat($('who').value || null);
});

(async function init() {
  await fillPicker($('who'));
  let resumed = false;
  try {
    const saved = sessionStorage.getItem(CHAT_KEY);
    if (saved) { await resumeChat(saved); resumed = true; }
  } catch { /* expired or storage blocked — start fresh */ }
  if (!resumed) await startChat(currentProfile());
  $('input').focus();
}());
