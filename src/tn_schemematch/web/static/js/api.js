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
    throw error;
  }
  return payload;
}

const post = (url, body) => call(url, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

export const api = {
  samples: () => call('/api/samples'),
  start: (query, useAi, maxQuestions) =>
    post('/api/session', { query, use_ai: useAi, max_questions: maxQuestions }),
  replay: (persona) => post('/api/session', { persona }),
  personas: () => call('/api/personas'),
  answerValue: (sid, attr, value) => post(`/api/session/${sid}/answer`, { attr, value }),
  answerText: (sid, attr, text) => post(`/api/session/${sid}/answer`, { attr, text }),
  skip: (sid, attr) => post(`/api/session/${sid}/skip`, { attr }),
  result: (sid) => call(`/api/session/${sid}/result`),
  explain: (sid, schemeId, lang) =>
    call(`/api/session/${sid}/explain/${schemeId}?lang=${lang}`),
  compare: (sid) => post(`/api/session/${sid}/compare`),
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
