/* The application sheet: read it aloud, and follow the language switch. */

import { hasVoice, speak } from './speech.js';
import { t } from './i18n.js';

const sheet = document.querySelector('.pack');
const button = document.getElementById('pack-read');

button?.addEventListener('click', () => {
  const lang = sheet.dataset.lang;
  if (hasVoice(lang)) speak(sheet.dataset.spoken, lang);
  else window.alert(t('no_tamil_voice'));
});

// The sheet is printed in one language, chosen by ?lang; the top-bar switch reloads it.
document.addEventListener('languagechange', (event) => {
  const url = new URL(window.location.href);
  url.searchParams.set('lang', event.detail);
  window.location.replace(url);
});

// Helpers record where the application stands, from the sheet itself.
const track = document.getElementById('track-form');
track?.addEventListener('submit', async (event) => {
  event.preventDefault();
  const box = track.closest('.pack-track');
  const form = new FormData(track);
  const note = document.getElementById('track-note');
  const response = await fetch(`/api/profiles/${box.dataset.pid}/applications`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      scheme_id: box.dataset.scheme, status: form.get('status'),
      reference: form.get('reference'), applied_on: form.get('applied_on') || null,
    }),
  });
  note.textContent = response.ok ? '✓' : (await response.json()).error?.message || '!';
});
