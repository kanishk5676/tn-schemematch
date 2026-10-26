/* The assistant page: speak or tap, hear the answer.

   The server holds the conversation and decides everything; this file draws it and does
   the speaking and listening. A chat is in one of two modes:
   - guided: one question at a time, answered with big buttons, a number, or by voice;
   - agent:  free conversation with the model, by voice or typing.
   The server moves a chat from agent to guided by itself when the model is unavailable,
   and says why in one line. Every reply arrives with `say` (what to read aloud) and, when
   anything was decided, `spoken`: the result as the rule engine states it. */

import { api, el, $ } from './api.js';
import { lang, sectorIcon, t } from './i18n.js';
import { currentProfile, fillPicker, rememberProfile } from './picker.js';
import {
  autoRead, canListen, canSpeak, hasVoice, listen, micConsented, setAutoRead, setMicConsent,
  speak, stopSpeaking,
} from './speech.js';
import { verdictChip } from './cards.js';

const CHAT_KEY = 'udhavi.chat';
let chat = null;          // the last chat payload: chat_id, mode, reason, question, ...
let profileId = null;
let busy = false;
let stopListening = null;
let pendingUploadType = null;
let warnedNoVoice = false;

/* ---------------------------------------------------------------- reading */

function warnNoVoice() {
  if (warnedNoVoice || lang() !== 'ta' || !canSpeak()) return;
  warnedNoVoice = true;
  addNote(t('no_tamil_voice'));
}

/** Read a turn: what the assistant said, then the rule engine's result if there is one. */
async function readTurn(turn, { force = false } = {}) {
  if (!force && !autoRead()) return;
  const text = [turn.say || turn.reply, turn.spoken].filter(Boolean).join(' ');
  if (!text) return;
  if (!hasVoice(lang())) { warnNoVoice(); return; }
  await speak(text, lang());
}

function speakerButton(text) {
  if (!canSpeak()) return null;
  return el('button', {
    type: 'button', class: 'btn icon speaker', title: t('read_aloud'), 'aria-label': t('read_aloud'),
    onclick: () => (hasVoice(lang()) ? speak(text, lang()) : warnNoVoice()),
  }, '🔊');
}

/* ---------------------------------------------------------------- drawing */

function scrollDown() {
  const box = $('messages');
  box.scrollTop = box.scrollHeight;
}

function richText(text) {
  const out = el('div', { class: 'bubble-text' });
  String(text || '').split(/(\*\*[^*]+\*\*)/g).forEach((part) => {
    if (part.startsWith('**') && part.endsWith('**')) out.append(el('b', {}, part.slice(2, -2)));
    else if (part) out.append(document.createTextNode(part));
  });
  return out;
}

function addUser(text) {
  if (!text) return;
  $('messages').append(el('div', { class: 'msg user' }, el('div', { class: 'bubble' }, richText(text))));
  scrollDown();
}

function mentionsView(mentions) {
  if (!mentions?.length) return null;
  return el('div', { class: 'mentions' },
    ...mentions.map((m) => verdictChip(m.verdict, m.name.length > 30 ? `${m.name.slice(0, 28)}…` : m.name)));
}

function uiView(action) {
  if (action.type === 'upload') {
    return el('button', { class: 'btn', onclick: () => requestUpload(action.doc_type) },
      `📎 ${action.label || t('upload')}`);
  }
  if (action.type === 'save_profile') {
    return profileId ? null : el('button', { class: 'btn primary', onclick: () => saveProfile() }, t('save'));
  }
  if (action.type === 'link') return el('a', { class: 'btn', href: action.href }, `${action.label} →`);
  return null;
}

// The newest guided bubble says only its lead ("சரி."), because its question is on the
// answer card right below it. When the next turn arrives it gets its question back, so
// the history still reads as a conversation.
let pendingFull = null;

function addAssistant(turn) {
  if (pendingFull) {
    pendingFull.node.replaceWith(richText(pendingFull.text));
    pendingFull = null;
  }
  const ui = (turn.ui || []).map(uiView).filter(Boolean);
  const full = turn.reply || turn.text;
  const short = turn.question && turn.lead ? turn.lead : null;
  const textNode = richText(short || full);
  if (short) pendingFull = { node: textNode, text: full };
  $('messages').append(el('div', { class: 'msg bot' },
    el('div', { class: 'bubble' },
      textNode,
      mentionsView(turn.mentions),
      // In a free conversation the rule engine's own words sit under the model's, so a
      // reply that overstates is visibly corrected. A finished guided chat shows cards.
      turn.spoken && !turn.result ? el('p', { class: 'spoken-line' }, turn.spoken) : null,
      speakerButton([turn.say || full, turn.spoken].filter(Boolean).join(' '))),
    ui.length ? el('div', { class: 'ui-actions' }, ...ui) : null));
  scrollDown();
}

function addNote(...children) {
  const node = el('div', { class: 'msg bot note' }, el('div', { class: 'bubble' }, ...children));
  $('messages').append(node);
  scrollDown();
  return node;
}

/* ------------------------------------------------------------ the answer */

function answerButton(label, alt, onclick, klass = '') {
  return el('button', { type: 'button', class: `answer-btn ${klass}`, onclick },
    el('span', { class: 'answer-main' }, label),
    alt ? el('span', { class: 'answer-alt' }, alt) : null);
}

/** Draw the controls for the open guided question, or nothing in agent mode. */
function drawQuestion(question) {
  const box = $('answer');
  if (!chat || chat.mode !== 'guided' || !question) { box.replaceChildren(); return; }
  const parts = [];
  parts.push(el('div', { class: 'question' },
    el('p', { class: 'question-text' }, question.text),
    question.alt ? el('p', { class: 'question-alt' }, question.alt) : null,
    question.why ? el('p', { class: 'question-why' }, question.why) : null));

  if (question.control === 'yesno') {
    parts.push(el('div', { class: 'answer-grid two' },
      ...question.options.map((o) => answerButton(o.label, o.alt,
        () => answer({ attr: question.attr, value: o.value, label: o.label }),
        o.value ? 'yes' : 'no'))));
  } else if (question.control === 'choice') {
    const many = question.options.length > 8;
    parts.push(el('div', { class: `answer-grid${many ? ' many' : ''}` },
      ...question.options.map((o) => answerButton(o.label, o.alt,
        () => answer({ attr: question.attr, value: o.value, label: o.label })))));
  } else {
    const input = el('input', {
      type: 'number', inputmode: 'decimal', class: 'number-input', id: 'number-input',
      min: question.min ?? undefined, max: question.max ?? undefined, step: 'any',
      'aria-label': question.text, placeholder: t('number_here'),
    });
    const submit = () => {
      const value = parseFloat(input.value);
      if (Number.isFinite(value)) answer({ attr: question.attr, value, label: `${input.value} ${question.unit || ''}`.trim() });
    };
    input.addEventListener('keydown', (event) => { if (event.key === 'Enter') submit(); });
    parts.push(el('div', { class: 'number-row' },
      input,
      question.unit ? el('span', { class: 'number-unit' }, question.unit) : null,
      el('button', { type: 'button', class: 'btn primary big', onclick: submit }, t('ok'))));
  }
  parts.push(el('div', { class: 'answer-skip' },
    el('button', { type: 'button', class: 'btn', onclick: () => answer({ attr: question.attr, skip: true }) },
      question.dont_know_label),
    question.sensitive
      ? el('button', { type: 'button', class: 'btn', onclick: () => answer({ attr: question.attr, skip: true }) },
        question.skip_label)
      : null));
  box.replaceChildren(...parts);
}

/* ------------------------------------------------------------- the result */

function schemeResultCard(line) {
  const links = el('div', { class: 'result-actions' });
  links.append(el('button', {
    type: 'button', class: 'btn',
    onclick: async () => {
      const pid = await saveProfile();
      if (pid) window.location.href = `/profile/${pid}/pack/${line.id}?lang=${lang()}`;
    },
  }, `📋 ${t('pack')}`));
  if (line.apply_url) {
    links.append(el('a', { class: 'btn', href: line.apply_url, target: '_blank', rel: 'noopener' },
      t('apply_online')));
  }
  return el('article', { class: 'result-card' },
    el('div', { class: 'result-icon', 'aria-hidden': 'true' }, sectorIcon(line.sectors)),
    el('div', { class: 'result-body' },
      el('h3', {}, line.name),
      line.what ? el('p', { class: 'result-what' }, line.what) : null,
      line.who ? el('p', { class: 'result-line' }, el('b', {}, `${t('who')}: `), line.who) : null,
      line.where ? el('p', { class: 'result-line' }, el('b', {}, `${t('where')}: `), line.where) : null,
      el('p', { class: 'result-official' }, `${t('official_name')}: ${line.official_name}`),
      el('span', { class: `badge ${line.verified ? 'ok' : 'open'}` }, line.verified ? t('verified') : t('draft')),
      links));
}

function whatsappLink(result) {
  const lines = [result.text, '', ...result.eligible.map((l) => `• ${l.name}`)];
  return `https://wa.me/?text=${encodeURIComponent(lines.join('\n'))}`;
}

function showResult(result) {
  const box = $('result');
  if (!result) { box.replaceChildren(); return; }
  const parts = [el('div', { class: 'result-head' },
    el('h2', {}, result.eligible.length ? `${t('found_title')}: ${t('found_n', { n: result.eligible.length })}` : t('none_found')),
    el('div', { class: 'row' },
      speakerButton(result.text),
      result.eligible.length
        ? el('a', { class: 'btn small', href: whatsappLink(result), target: '_blank', rel: 'noopener' }, `💬 ${t('share')}`)
        : null))];
  result.eligible.forEach((line) => parts.push(schemeResultCard(line)));
  if (result.bring?.length) {
    parts.push(el('div', { class: 'card bring' },
      el('h3', {}, `🗂️ ${t('bring_title')}`),
      el('ul', {}, ...result.bring.map((item) => el('li', {}, item.label)))));
  }
  if (result.near?.length) {
    parts.push(el('div', { class: 'card near' },
      el('h3', {}, t('near_title')),
      el('ul', {}, ...result.near.map((line) => el('li', {}, line.name)))));
  }
  box.replaceChildren(el('section', { class: 'result', 'aria-label': t('found_title') }, ...parts));
  box.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function hearResult() {
  if (!chat) return;
  try {
    const result = await api.chatResult(chat.chat_id, lang());
    showResult(result);
    if (hasVoice(lang())) speak(result.text, lang()); else warnNoVoice();
  } catch (error) {
    addNote(el('span', { class: 'err' }, t('error')));
  }
}

/* ------------------------------------------------------------ state paint */

function paint(data) {
  chat = { ...chat, ...data };
  const board = data.board;
  if (board) {
    $('n-ok').textContent = board.counts.eligible;
    $('n-open').textContent = board.counts.undetermined;
  }
  if (data.told) {
    $('told-card').hidden = !data.told.length;
    $('told').replaceChildren(...data.told.flatMap((row) => [el('dt', {}, row.label), el('dd', {}, row.display)]));
  }
  if ('profile_id' in data) setProfile(data.profile_id, data.profile_name);
  paintMode();
  if ('question' in data || data.mode === 'agent') drawQuestion(data.question);
}

function paintMode() {
  const note = $('mode-note');
  const button = $('mode-switch');
  const guided = chat?.mode === 'guided';
  note.textContent = guided && chat.reason ? t(`reason_${chat.reason}`) : '';
  // "Talk freely" is offered only when the model could plausibly answer.
  const modelGone = ['no_model', 'daily_budget', 'no_credit', 'key_rejected'].includes(chat?.reason);
  button.hidden = guided && modelGone;
  button.textContent = guided ? t('talk_freely') : t('simple_questions');
  // Typing is always possible; the box opens on request, or at once without a microphone.
  $('composer').hidden = !($('composer').dataset.open === '1' || !canListen());
}

function setProfile(pid, name) {
  profileId = pid || null;
  rememberProfile(profileId);
  $('save').hidden = Boolean(profileId);
  $('who-note').textContent = profileId ? t('saved_note', { name: name || '' }) : t('not_saved');
}

/* --------------------------------------------------------------- the chat */

function remember(id) {
  try { sessionStorage.setItem(CHAT_KEY, id); } catch { /* storage blocked */ }
}

async function startChat(pid, mode) {
  stopSpeaking();
  const data = await api.startChat(pid, lang(), mode);
  chat = null;
  pendingFull = null;
  remember(data.chat_id);
  $('messages').replaceChildren();
  showResult(null);
  addAssistant(data.turn);
  paint({ ...data, question: data.turn.question });
  readTurn(data.turn);
}

async function resumeChat(id) {
  const data = await api.chat(id, lang());
  chat = null;
  pendingFull = null;
  $('messages').replaceChildren();
  data.transcript.forEach((entry) => (entry.role === 'user' ? addUser(entry.text) : addAssistant(entry)));
  paint(data);
  $('who').value = data.profile_id || '';
}

async function handleTurn(turn) {
  if (turn.switched) addNote(t(`reason_${turn.reason}`) || t('reason_no_model'));
  addAssistant(turn);
  paint(turn);
  if (turn.done && turn.result) showResult(turn.result);
  await readTurn(turn);
}

/** Send one answer: {text} in either mode, or {attr, value} / {attr, skip} in guided mode. */
async function answer(body) {
  if (busy || !chat) return;
  busy = true;
  stopSpeaking();
  document.body.classList.add('busy');
  addUser(body.text || body.label || (body.skip ? chat.question?.dont_know_label : ''));
  const thinking = chat.mode === 'agent'
    ? addNote(el('span', { class: 'spinner' }), ` ${t('thinking')}`) : null;
  try {
    const payload = { ...body, lang: lang() };
    delete payload.label;
    const turn = await api.say(chat.chat_id, payload);
    thinking?.remove();
    await handleTurn(turn);
  } catch (error) {
    thinking?.remove();
    if (error.code === 'no_such_chat') await startChat(profileId);
    else if (error.code === 'stale_question') await resumeChat(chat.chat_id);
    else addNote(el('span', { class: 'err' }, t('error')));
  } finally {
    busy = false;
    document.body.classList.remove('busy');
  }
}

function sendText(text) {
  text = (text || '').trim();
  if (!text) return;
  $('input').value = '';
  answer({ text });
}

/* ------------------------------------------------------------------ voice */

function askMicConsent() {
  if (micConsented()) return Promise.resolve(true);
  const dialog = $('privacy-dialog');
  dialog.showModal();
  if (hasVoice(lang())) speak(t('privacy_text'), lang());
  return new Promise((resolve) => {
    dialog.addEventListener('close', () => {
      const yes = dialog.returnValue === 'yes';
      setMicConsent(yes);
      if (!yes) openComposer();
      resolve(yes);
    }, { once: true });
  });
}

function setListening(on) {
  $('mic').classList.toggle('on', on);
  $('mic').setAttribute('aria-pressed', on ? 'true' : 'false');
  $('mic-label').textContent = on ? t('listening') : t('mic');
}

async function toggleMic() {
  if (stopListening) { stopListening(); return; }
  if (!(await askMicConsent())) return;
  $('heard').textContent = '';
  setListening(true);
  stopListening = listen(lang(), {
    onInterim: (text) => { $('heard').textContent = text; },
    onFinal: (text) => { $('heard').textContent = ''; sendText(text); },
    onError: (code) => {
      if (code === 'not-allowed' || code === 'service-not-allowed') { addNote(t('mic_denied')); openComposer(); }
      else if (code === 'no-speech') $('heard').textContent = t('heard_nothing');
    },
    onEnd: () => { stopListening = null; setListening(false); },
  });
}

function openComposer() {
  $('composer').dataset.open = '1';
  $('composer').hidden = false;
  $('input').focus();
}

/* ------------------------------------------------------ profile & upload */

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
  const saved = await api.save(chat.chat_id, { name });
  setProfile(saved.profile_id, saved.profile.name);
  await fillPicker($('who'), { selected: saved.profile_id, blank: t('someone_new') });
  addNote(t('saved_as', { name: saved.profile.name }));
  return saved.profile_id;
}

async function requestUpload(docType) {
  if (!(await saveProfile())) return;
  pendingUploadType = docType || null;
  $('file').click();
}

async function uploadFile(file) {
  const working = addNote(el('span', { class: 'spinner' }), ` ${file.name}…`);
  try {
    const result = await api.upload(profileId, file, pendingUploadType);
    working.remove();
    const applied = [...result.applied, ...result.confirmed];
    addNote(`📄 ${result.type_label || ''}`, applied.length
      ? el('div', { class: 'tiny' }, applied.map((f) => `${f.label}: ${f.display}`).join(' · ')) : null,
      result.conflicts.length ? el('div', { class: 'tiny' },
        el('a', { href: `/profile?id=${profileId}` }, `${t('nav_profile')} →`)) : null);
    const fresh = await api.chat(chat.chat_id, lang());
    paint(fresh);
    if (chat.mode === 'agent' && result.document.status !== 'unread') {
      await answer({ text: `I uploaded my ${(result.type_label || 'document').toLowerCase()}.` });
    }
  } catch (error) {
    working.remove();
    addNote(el('span', { class: 'err' }, error.message));
  } finally {
    pendingUploadType = null;
    $('file').value = '';
  }
}

/* -------------------------------------------------------------- listeners */

$('mic').hidden = !canListen();
if (!canListen()) openComposer();
$('mic').addEventListener('click', toggleMic);
$('composer').addEventListener('submit', (event) => { event.preventDefault(); sendText($('input').value); });
$('input').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    sendText($('input').value);
  }
});
$('type-toggle').addEventListener('click', openComposer);
$('result-btn').addEventListener('click', hearResult);
$('attach').addEventListener('click', () => requestUpload(null));
$('file').addEventListener('change', () => { if ($('file').files[0]) uploadFile($('file').files[0]); });
$('save').addEventListener('click', () => saveProfile());
$('restart').addEventListener('click', () => startChat(profileId));
$('autoread').checked = autoRead();
$('autoread').addEventListener('change', () => {
  setAutoRead($('autoread').checked);
  if (!$('autoread').checked) stopSpeaking();
});
$('mode-switch').addEventListener('click', async () => {
  if (!chat || busy) return;
  try {
    const next = chat.mode === 'guided' ? 'agent' : 'guided';
    const data = await api.chatMode(chat.chat_id, next, lang());
    addAssistant(data.turn);
    paint({ ...data, question: data.turn.question });
    readTurn(data.turn);
  } catch (error) {
    paint({ reason: error.code });
  }
});
$('who').addEventListener('change', () => startChat($('who').value || null));
document.addEventListener('languagechange', async () => {
  stopSpeaking();
  warnedNoVoice = false;
  await fillPicker($('who'), { blank: t('someone_new'), selected: profileId });
  if (chat) await resumeChat(chat.chat_id);
});

(async function init() {
  await fillPicker($('who'), { blank: t('someone_new') });
  let resumed = false;
  try {
    const saved = sessionStorage.getItem(CHAT_KEY);
    if (saved) { await resumeChat(saved); resumed = true; }
  } catch { /* expired or storage blocked — start fresh */ }
  if (!resumed) await startChat(currentProfile());
}());
