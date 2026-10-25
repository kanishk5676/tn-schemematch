/* Which saved profile this browser is acting as.

   Remembered in localStorage only as a convenience — the profile itself lives in the
   server's vault. Storage can be unavailable (private windows, blocked site data), so every
   access is guarded and the pages work without it. */

import { api, el } from './api.js';

const KEY = 'tnsm.profile';

export function currentProfile() {
  try { return localStorage.getItem(KEY) || null; } catch { return null; }
}

export function rememberProfile(pid) {
  try {
    if (pid) localStorage.setItem(KEY, pid); else localStorage.removeItem(KEY);
  } catch { /* storage blocked — the page still works, it just will not remember */ }
}

/** Fill a <select> with saved profiles. Resolves to the list (empty if none). */
export async function fillPicker(select, { blank = 'Someone new', selected = currentProfile() } = {}) {
  let profiles = [];
  try { ({ profiles } = await api.profiles()); } catch { /* vault unavailable */ }
  select.replaceChildren(el('option', { value: '' }, blank),
    ...profiles.map((p) => el('option', { value: p.id },
      `${p.name}${p.relation ? ` (${p.relation})` : ''} · ${p.n_facts} facts`)));
  // A remembered id that has since been deleted falls back to "someone new".
  select.value = profiles.some((p) => p.id === selected) ? selected : '';
  return profiles;
}
