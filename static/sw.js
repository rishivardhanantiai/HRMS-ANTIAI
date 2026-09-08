const CACHE_NAME = 'anti-hrms-cache-v2';
const ASSETS_TO_CACHE = [
  '/',
  '/static/manifest.json',
  '/static/css/style.css',
  '/static/css/style.min.css',
  '/static/css/theme.css',
  '/static/css/theme.min.css',
  '/static/css/announcements.css',
  '/static/css/announcements.min.css',
  '/static/js/main.js',
  '/static/js/main.min.js',
  '/static/js/announcements.js',
  '/static/js/announcements.min.js',
  '/static/images/logo.png',
  '/static/images/logo_globe.png',
  '/static/images/logo_globe_watermark.png',
  '/static/images/logo_wordmark.png',
  '/static/images/icon-96.png',
  '/static/images/icon-192.png',
  '/static/images/icon-512.png'
];

// Install Event
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
  self.skipWaiting();
});

// Activate Event
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys => {
      return Promise.all(
        keys.map(key => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

// Fetch Event (Cache-first for static assets, network-first for dynamic resources)
self.addEventListener('fetch', event => {
  const requestUrl = new URL(event.request.url);
  
  // Cache static assets
  if (ASSETS_TO_CACHE.includes(requestUrl.pathname)) {
    event.respondWith(
      caches.match(event.request).then(cachedResponse => {
        return cachedResponse || fetch(event.request);
      })
    );
  } else {
    // Network-first strategy for dynamic routes
    event.respondWith(
      fetch(event.request).catch(() => {
        return caches.match(event.request).then(cachedResponse => {
          if (cachedResponse) {
            return cachedResponse;
          }
          // If offline and request is HTML document, return fallback offline page
          if (event.request.headers.get('accept') && event.request.headers.get('accept').includes('text/html')) {
            return new Response(
              '<!DOCTYPE html><html><head><title>Offline</title><style>body{background:#050505;color:#e2e8f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;}</style></head><body><div><h1>Offline Mode</h1><p>You are currently offline. Please check your internet connection.</p></div></body></html>',
              { headers: { 'Content-Type': 'text/html' } }
            );
          }
        });
      })
    );
  }
});
