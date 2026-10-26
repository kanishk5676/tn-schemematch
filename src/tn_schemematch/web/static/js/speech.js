/* Speaking and listening, with the browser's own speech services.

   Listening uses SpeechRecognition (webkitSpeechRecognition in Chrome) with ta-IN or en-IN.
   Chrome sends the audio to Google to recognise it, which is why the page asks once before
   the first recording. Reading aloud uses speechSynthesis with a Tamil voice when the
   device has one. Without a Tamil voice, Tamil text is not read at all: an English voice
   spelling out Tamil letters is worse than silence, and the page says how to add one.

   Every entry point degrades: no recognition → the mic button is hidden and the person
   types or taps; no synthesis → replies are shown, not read. */

const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition || null;
const synth = window.speechSynthesis || null;

const AUTO_KEY = 'udhavi.autoread';
const CONSENT_KEY = 'udhavi.mic-consent';

export const canListen = () => Boolean(Recognition);
export const canSpeak = () => Boolean(synth && window.SpeechSynthesisUtterance);

function stored(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch { return fallback; }
}
function store(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage blocked */ }
}

export const autoRead = () => stored(AUTO_KEY, '1') === '1';
export const setAutoRead = (on) => store(AUTO_KEY, on ? '1' : '0');
export const micConsented = () => stored(CONSENT_KEY, '') === 'yes';
export const setMicConsent = (yes) => store(CONSENT_KEY, yes ? 'yes' : 'no');

/* ----------------------------------------------------------------- voices */

let voices = [];
function loadVoices() { voices = synth ? synth.getVoices() : []; }
if (synth) {
  loadVoices();
  synth.addEventListener?.('voiceschanged', loadVoices);
}

/** The best voice for a language, or null. Tamil must be Tamil; English prefers India. */
export function voiceFor(lang) {
  if (!voices.length) loadVoices();
  if (lang === 'ta') return voices.find((v) => v.lang?.toLowerCase().startsWith('ta')) || null;
  return voices.find((v) => v.lang === 'en-IN')
    || voices.find((v) => v.lang?.toLowerCase().startsWith('en')) || null;
}

export const hasVoice = (lang) => Boolean(canSpeak() && voiceFor(lang));

/* Long utterances are cut off by some engines after ~15 seconds, so text is queued one
   sentence at a time. Tamil sentences end in "." as English ones do. */
function sentences(text) {
  return String(text || '').replace(/\s+/g, ' ').split(/(?<=[.?!।])\s+/).filter((s) => s.trim());
}

let speaking = null;

/** Read text aloud. Resolves when finished or stopped; resolves false if it could not. */
export function speak(text, lang, { onStart, onEnd } = {}) {
  stopSpeaking();
  const voice = voiceFor(lang);
  if (!canSpeak() || !voice || !text) return Promise.resolve(false);
  const parts = sentences(text);
  const token = {};
  speaking = token;
  onStart?.();
  return new Promise((resolve) => {
    let i = 0;
    const next = () => {
      if (speaking !== token || i >= parts.length) {
        if (speaking === token) speaking = null;
        onEnd?.();
        resolve(true);
        return;
      }
      const utterance = new SpeechSynthesisUtterance(parts[i]);
      i += 1;
      utterance.voice = voice;
      utterance.lang = voice.lang;
      utterance.rate = lang === 'ta' ? 0.9 : 0.95; // a little slower than default
      utterance.onend = next;
      utterance.onerror = next;
      synth.speak(utterance);
    };
    next();
  });
}

export function stopSpeaking() {
  speaking = null;
  if (synth) synth.cancel();
}

export const isSpeaking = () => speaking !== null;

/* -------------------------------------------------------------- listening */

/** Listen once. Calls onInterim(text) as words arrive and onFinal(text) at the end.
    Returns a function that stops listening early. */
export function listen(lang, { onInterim, onFinal, onError, onEnd } = {}) {
  if (!Recognition) { onError?.('unsupported'); return () => {}; }
  stopSpeaking(); // never record the page's own voice
  const recognition = new Recognition();
  recognition.lang = lang === 'en' ? 'en-IN' : 'ta-IN';
  recognition.interimResults = true;
  recognition.continuous = false;
  recognition.maxAlternatives = 1;
  let finalText = '';
  recognition.onresult = (event) => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const piece = event.results[i][0].transcript;
      if (event.results[i].isFinal) finalText += piece; else interim += piece;
    }
    onInterim?.((finalText + interim).trim());
  };
  recognition.onerror = (event) => onError?.(event.error || 'error');
  recognition.onend = () => {
    if (finalText.trim()) onFinal?.(finalText.trim());
    onEnd?.();
  };
  try { recognition.start(); } catch { onError?.('busy'); }
  return () => { try { recognition.stop(); } catch { /* already stopped */ } };
}
