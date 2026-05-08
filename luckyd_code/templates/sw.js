// DeepSeek Code Service Worker
const CACHE = 'ds-code-v1.1.0';

self.addEventListener('install', function(e) {
  e.waitUntil(
    caches.open(CACHE).then(function(cache) {
      return cache.addAll([
        '/',
      ]);
    })
  );
});

self.addEventListener('fetch', function(e) {
  // Network-first for API, cache-first for static
  if (e.request.url.includes('/api/')) {
    e.respondWith(
      fetch(e.request).catch(function() {
        return new Response(JSON.stringify({error: 'offline'}), {
          status: 503, headers: {'Content-Type': 'application/json'}
        });
      })
    );
  } else {
    e.respondWith(
      caches.match(e.request).then(function(r) {
        return r || fetch(e.request);
      })
    );
  }
});
