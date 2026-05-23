// Service Worker for Airport Digital Twin
// Provides caching, offline fallback, and update notifications

const CACHE_VERSION = 'v4';
const STATIC_CACHE = `static-${CACHE_VERSION}`;
const API_CACHE = `api-${CACHE_VERSION}`;

const MAX_STATIC_ENTRIES = 100;
const MAX_API_ENTRIES = 50;
const API_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours
const STATIC_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000; // 30 days

const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/airport.svg',
  '/manifest.json',
  '/icons/apple-touch-icon.png',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/icon-512-maskable.png',
  '/offline.html',
];

// LRU cache eviction — keeps cache under maxEntries
async function evictOldEntries(cacheName, maxEntries) {
  const cache = await caches.open(cacheName);
  const keys = await cache.keys();
  if (keys.length > maxEntries) {
    const toDelete = keys.slice(0, keys.length - maxEntries);
    await Promise.all(toDelete.map((k) => cache.delete(k)));
  }
}

// Install — precache static shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(STATIC_ASSETS))
  );
  // Don't skipWaiting — let the client control when to activate
});

// Activate — clean up old caches and notify clients of update
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name !== STATIC_CACHE && name !== API_CACHE)
          .map((name) => caches.delete(name))
      );
    }).then(() => {
      // Notify all clients that a new version is available
      return self.clients.matchAll().then((clients) => {
        clients.forEach((client) => {
          client.postMessage({ type: 'SW_UPDATED', version: CACHE_VERSION });
        });
      });
    })
  );
  self.clients.claim();
});

// Listen for skip-waiting message from client
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// Fetch — strategy per request type
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  if (request.method !== 'GET') return;

  // WebSocket — don't intercept
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return;

  // API requests: network-first with cache fallback
  // Never cache authenticated responses (could leak across sessions)
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws')) {
    const hasAuth = request.headers.get('Authorization') || request.headers.get('Cookie');
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok && !url.pathname.includes('/ws') && !hasAuth) {
            const clone = response.clone();
            caches.open(API_CACHE).then((cache) => {
              cache.put(request, clone);
              evictOldEntries(API_CACHE, MAX_API_ENTRIES);
            });
          }
          return response;
        })
        .catch(() => hasAuth ? new Response('Offline', { status: 503 }) : caches.match(request))
    );
    return;
  }

  // Static assets (JS, CSS, fonts, images, 3D models): stale-while-revalidate
  if (
    url.pathname.endsWith('.js') ||
    url.pathname.endsWith('.css') ||
    url.pathname.endsWith('.woff2') ||
    url.pathname.endsWith('.png') ||
    url.pathname.endsWith('.svg') ||
    url.pathname.endsWith('.glb') ||
    url.pathname.startsWith('/assets/')
  ) {
    event.respondWith(
      caches.match(request).then((cached) => {
        const fetchPromise = fetch(request).then((response) => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(STATIC_CACHE).then((cache) => {
              cache.put(request, clone);
              evictOldEntries(STATIC_CACHE, MAX_STATIC_ENTRIES);
            });
          }
          return response;
        }).catch(() => cached);

        return cached || fetchPromise;
      })
    );
    return;
  }

  // HTML navigation: network-first with offline fallback
  if (request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const clone = response.clone();
          caches.open(STATIC_CACHE).then((cache) => cache.put(request, clone));
          return response;
        })
        .catch(() => {
          return caches.match(request).then((cached) => {
            return cached || caches.match('/offline.html');
          });
        })
    );
    return;
  }
});
