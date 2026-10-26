/* Service worker: the app shell loads on a slow connection, and the app can be installed.

   Static files (styles, scripts, icons) are served from the cache and refreshed in the
   background. Pages and the API always go to the network: eligibility, questions and
   saved profiles live on the server, and a stale answer is worse than no answer. When the
   network is down a page falls back to the last copy of it that was cached. */

const VERSION = 'udhavi-v1';
const SHELL = [
  '/',
  '/static/css/app.css',
  '/static/js/api.js',
  '/static/js/i18n.js',
  '/static/js/speech.js',
  '/static/js/assistant.js',
  '/static/js/picker.js',
  '/static/js/cards.js',
  '/static/js/trace.js',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(VERSION).then((cache) => cache.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;

  if (url.pathname.startsWith('/static/')) {
    // Cache first, refresh behind.
    event.respondWith(caches.open(VERSION).then(async (cache) => {
      const cached = await cache.match(request);
      const network = fetch(request).then((response) => {
        if (response.ok) cache.put(request, response.clone());
        return response;
      }).catch(() => cached);
      return cached || network;
    }));
    return;
  }

  if (request.mode === 'navigate') {
    // Network first; the cached copy only when offline.
    event.respondWith(fetch(request).then((response) => {
      if (response.ok) caches.open(VERSION).then((cache) => cache.put(request, response.clone()));
      return response;
    }).catch(async () => (await caches.match(request)) || caches.match('/')));
  }
});
