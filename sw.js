// SW..LION Tracker — Service Worker v1.0
// Caches app shell + Google Fonts + Spotify album covers for offline use.

const VERSION = 'sw-lion-v1.2.0';
const APP_CACHE = `app-${VERSION}`;
const RUNTIME_CACHE = `runtime-${VERSION}`;

// Files to pre-cache (app shell)
const APP_SHELL = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png',
  './icon-maskable-512.png',
  './apple-touch-icon.png',
];

// Install: pre-cache app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(APP_CACHE)
      .then((cache) => cache.addAll(APP_SHELL))
      .then(() => self.skipWaiting())
  );
});

// Activate: clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((key) => key !== APP_CACHE && key !== RUNTIME_CACHE)
          .map((key) => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

// Fetch strategy:
// - App shell: cache-first
// - Google Fonts (CSS + woff2): stale-while-revalidate
// - Spotify CDN images: cache-first with runtime cache
// - Everything else (platform links): network-only
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') return;

  // App shell — cache first
  if (APP_SHELL.includes(url.pathname.replace(/^\/[^/]+\//, './')) ||
      url.origin === self.location.origin) {
    event.respondWith(cacheFirst(request, APP_CACHE));
    return;
  }

  // Google Fonts — stale-while-revalidate
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    event.respondWith(staleWhileRevalidate(request, RUNTIME_CACHE));
    return;
  }

  // Spotify album covers — cache first (covers don't change)
  if (url.hostname === 'i.scdn.co') {
    event.respondWith(cacheFirst(request, RUNTIME_CACHE));
    return;
  }

  // Everything else — network only (don't cache platform navigation links)
});

async function cacheFirst(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response && response.status === 200) {
      cache.put(request, response.clone());
    }
    return response;
  } catch (err) {
    // Offline fallback — return cached index for navigation requests
    if (request.mode === 'navigate') {
      return cache.match('./index.html');
    }
    throw err;
  }
}

async function staleWhileRevalidate(request, cacheName) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(request);
  const fetchPromise = fetch(request).then((response) => {
    if (response && response.status === 200) {
      cache.put(request, response.clone());
    }
    return response;
  }).catch(() => cached);
  return cached || fetchPromise;
}
