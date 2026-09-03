const CACHE_NAME = 'anti-hrms-cache-v1';
const ASSETS_TO_CACHE = [
  '/',
  '/static/css/style.css',
  '/static/css/theme.css',
  '/static/js/main.js',
  '/static/images/logo.png'
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

// Fetch Event (Network-first with cache fallback for dynamic resources, cache-first for static assets)
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
          // If offline and request is HTML document, we can return a basic offline notification message
          if (event.request.headers.get('accept').includes('text/html')) {
            return new Response(
              '<h1>Offline Mode</h1><p>You are currently offline. Please check your internet connection and try again.</p>',
              { headers: { 'Content-Type': 'text/html' } }
            );
          }
        });
      })
    );
  }
});
