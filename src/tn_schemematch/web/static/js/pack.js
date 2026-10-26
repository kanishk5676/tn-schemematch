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
