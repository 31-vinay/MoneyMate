const CACHE_VERSION = 'money-mate-v5';
const STATIC_CACHE = CACHE_VERSION + '-static';
const DYNAMIC_CACHE = CACHE_VERSION + '-dynamic';

const STATIC_ASSETS = [
  '/static/style.css',
  '/static/logo.png',
  '/static/manifest.json',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js',
  'https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css',
  '/offline',
];

const NAV_ROUTES = [
  '/dashboard',
  '/add_income',
  '/add_expense',
  '/goals',
  '/analysis',
  '/subscriptions',
  '/settings',
];

const CHART_ROUTES = [
  '/analysis/chart/dist',
  '/analysis/chart/cats',
  '/analysis/chart/trend',
  '/analysis/chart/inc_exp',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) =>
      cache.addAll(STATIC_ASSETS.map((url) => new Request(url, { credentials: 'same-origin' })))
        .catch((err) => console.warn('[SW] Pre-cache failed for some assets:', err))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(
        keys
          .filter((k) => !k.startsWith(CACHE_VERSION))
          .map((k) => caches.delete(k))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);

  // Static assets — cache-first, fallback to network
  if (
    url.pathname.startsWith('/static/') ||
    url.hostname === 'cdn.jsdelivr.net'
  ) {
    event.respondWith(
      caches.match(req).then((cached) => {
        if (cached) return cached;
        return fetch(req).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(STATIC_CACHE).then((cache) => cache.put(req, clone));
          }
          return response;
        }).catch(() => caches.match('/offline'));
      })
    );
    return;
  }

  // Analysis charts — network-first, short-lived cache (5 min)
  if (CHART_ROUTES.some((r) => url.pathname === r)) {
    event.respondWith(
      fetch(req).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(DYNAMIC_CACHE).then((cache) => cache.put(req, clone));
        }
        return response;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // Navigation requests — network-first, fallback to offline page
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(DYNAMIC_CACHE).then((cache) => cache.put(req, clone));
        }
        return response;
      }).catch(() =>
        caches.match(req).then((cached) => cached || caches.match('/offline'))
      )
    );
    return;
  }

  // Everything else — network-first, stale fallback
  event.respondWith(
    fetch(req).catch(() => caches.match(req))
  );
});

// Periodic cache cleanup — evict dynamic entries older than 1 hour
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});
