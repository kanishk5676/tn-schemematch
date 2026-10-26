/* Fetch wrappers. Every server error arrives as {error:{code,message}}; this turns that
   into a thrown Error carrying the code, so callers branch on meaning rather than status. */

async function call(url, options) {
  const response = await fetch(url, options);
  let payload = null;
  try { payload = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const error = new Error(payload?.error?.message || `request failed (${response.status})`);
    error.code = payload?.error?.code || 'http_error';
    error.status = response.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

export const post = (url, body) => call(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

const send = (method, url, body) => call(url, {
  method,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

export const api = {
  samples: () => call('/api/samples'),
  start: (query, useAi, maxQuestions, profileId) =>
    post('/api/session', {
      query, use_ai: useAi, max_questions: maxQuestions, profile_id: profileId || undefined,
    }),
  save: (sid, body) => post(`/api/session/${sid}/save`, body),

  // saved profiles
  profiles: () => call('/api/profiles'),
  createProfile: (name, relation, householdOf) =>
    post('/api/profiles', { name, relation, household_of: householdOf || undefined }),
  profile: (pid) => call(`/api/profiles/${pid}`),
  deleteProfile: (pid) => send('DELETE', `/api/profiles/${pid}`),
  recordFact: (pid, body) => post(`/api/profiles/${pid}/facts`, body),
  eligibility: (pid) => call(`/api/profiles/${pid}/eligibility`),
  checklist: (pid) => call(`/api/profiles/${pid}/checklist`),
  unlock: (pid) => call(`/api/profiles/${pid}/unlock`),
  household: (pid) => call(`/api/profiles/${pid}/household`),
  calendar: (pid) => call(`/api/profiles/${pid}/calendar`),

  // applications
  applications: (pid) => call(`/api/profiles/${pid}/applications`),
  // One row per scheme: { scheme_id, status, applied_on?, reference?, reason? }.
  track: (pid, body) => post(`/api/profiles/${pid}/applications`, body),
  complaint: (pid, schemeId, lang) =>
    call(`/api/profiles/${pid}/applications/${schemeId}/complaint?lang=${lang}`),
  rejectionReasons: () => call('/api/rejection-reasons'),

  // helpers and privacy
  camps: () => call('/api/camps'),
  createCamp: (body) => post('/api/camps', body),
  camp: (cid) => call(`/api/camps/${cid}`),
  intake: (cid, body) => post(`/api/camps/${cid}/people`, body),
  report: (cid) => call('/api/reports/summary' + (cid ? `?camp=${cid}` : '')),
  notice: (lang) => call(`/api/privacy/notice?lang=${lang}`),
  giveConsent: (pid, body) => post(`/api/profiles/${pid}/consent`, body),
  audit: (pid) => call(`/api/profiles/${pid}/audit`),
  outcomes: () => call('/api/outcomes'),

  // documents
  documentTypes: () => call('/api/documents/types'),
  attributes: () => call('/api/attributes'),
  upload: (pid, file, docType, keep = false) => {
    const form = new FormData();
    form.append('file', file);
    if (docType) form.append('doc_type', docType);
    if (keep) form.append('keep', '1');
    return call(`/api/profiles/${pid}/documents`, { method: 'POST', body: form });
  },
  setDocumentType: (pid, docId, docType) =>
    post(`/api/profiles/${pid}/documents/${docId}/type`, { doc_type: docType }),
  resolve: (pid, docId, attr, keep) =>
    post(`/api/profiles/${pid}/documents/${docId}/resolve`, { attr, keep }),
  deleteDocument: (pid, docId) => send('DELETE', `/api/profiles/${pid}/documents/${docId}`),

  // the assistant
  startChat: (profileId, lang, mode) =>
    post('/api/chat', { profile_id: profileId || undefined, lang, mode: mode || undefined }),
  chat: (chatId, lang) => call(`/api/chat/${chatId}${lang ? `?lang=${lang}` : ''}`),
  say: (chatId, body) => post(`/api/chat/${chatId}/message`, body),
  chatResult: (chatId, lang) => call(`/api/chat/${chatId}/result?lang=${lang}`),
  chatMode: (chatId, mode, lang) => post(`/api/chat/${chatId}/mode`, { mode, lang }),

  replay: (persona) => post('/api/session', { persona }),
  personas: () => call('/api/personas'),
  answerValue: (sid, attr, value) => post(`/api/session/${sid}/answer`, { attr, value }),
  answerText: (sid, attr, text) => post(`/api/session/${sid}/answer`, { attr, text }),
  skip: (sid, attr) => post(`/api/session/${sid}/skip`, { attr }),
  result: (sid) => call(`/api/session/${sid}/result`),
  explain: (sid, schemeId, lang) =>
    call(`/api/session/${sid}/explain/${schemeId}?lang=${lang}`),
  schemes: (params) => call('/api/schemes' + (params ? `?${params}` : '')),
  scheme: (id, sid) => call(`/api/schemes/${id}` + (sid ? `?session=${sid}` : '')),
  stats: () => call('/api/stats'),
};

export const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    else if (key === 'html') node.innerHTML = value;
    else if (key.startsWith('on')) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
};

export const $ = (id) => document.getElementById(id);
