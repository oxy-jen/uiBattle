const APP_VERSION = {{ app_version|tojson }};
const CACHE_PREFIX = 'uiba-pwa';
const CACHE_NAME = `${CACHE_PREFIX}-${APP_VERSION}`;
const CORE_ASSETS = [
  '/app',
  '/login',
  '/manifest.webmanifest',
  '/pwa/version.json',
  '/static/css/style.css?v={{ static_version|urlencode }}',
  '/static/js/main.js?v=profile-media3',
  '/static/js/pwa-updater.js?v={{ app_version|urlencode }}',
  '/static/site-icon.svg',
  '/static/pwa-icon-192.png',
  '/static/pwa-icon-512.png'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then((cache) => cache.addAll(CORE_ASSETS))
      .catch(() => undefined)
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(
      names
        .filter((name) => name.startsWith(CACHE_PREFIX) && name !== CACHE_NAME)
        .map((name) => caches.delete(name))
    );
    await self.clients.claim();
    const clients = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    clients.forEach((client) => client.postMessage({type: 'UIBA_SW_ACTIVATED', version: APP_VERSION}));
  })());
});

self.addEventListener('message', (event) => {
  const type = event.data && event.data.type;
  if (type === 'UIBA_ACTIVATE_UPDATE') {
    self.skipWaiting();
  }
  if (type === 'UIBA_CLEAR_CACHES') {
    event.waitUntil(
      caches.keys().then((names) => Promise.all(
        names.filter((name) => name.startsWith(CACHE_PREFIX)).map((name) => caches.delete(name))
      ))
    );
  }
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/auth/') || url.pathname.startsWith('/socket.io/')) return;
  if (url.pathname === '/pwa/version.json' || url.pathname === '/pwa/health') {
    event.respondWith(fetch(request, {cache: 'no-store'}));
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith((async () => {
      try {
        const response = await fetch(request);
        const cache = await caches.open(CACHE_NAME);
        cache.put(request, response.clone());
        return response;
      } catch (error) {
        const cached = await caches.match(request);
        return cached || caches.match('/app') || caches.match('/login');
      }
    })());
    return;
  }

  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.webmanifest') {
    event.respondWith((async () => {
      const cached = await caches.match(request);
      const network = fetch(request)
        .then(async (response) => {
          if (response && response.ok) {
            const cache = await caches.open(CACHE_NAME);
            cache.put(request, response.clone());
          }
          return response;
        })
        .catch(() => cached);
      return cached || network;
    })());
  }
});
