const CACHE_NAME = 'leblibrary-cache-v2';
const urlsToCache = [
  '/',
  '/manifest.json',
];

self.addEventListener('install', event => {
  self.skipWaiting(); // מאלץ את ה-Service Worker החדש להשתלט מיד
  event.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => {
        return cache.addAll(urlsToCache);
      })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(cacheNames => {
      return Promise.all(
        cacheNames.map(cacheName => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName); // מוחק את הקאש הישן והתקוע
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// אסטרטגיית Network First - קודם השרת, ואם נופל חוזרים לקאש
self.addEventListener('fetch', event => {
  // מדלג על בקשות שלא שייכות ל-GET (כמו שליחת טפסים או צ'אט)
  if (event.request.method !== 'GET') return;

  event.respondWith(
    fetch(event.request)
      .then(networkResponse => {
        // שומר עותק מעודכן בזיכרון
        return caches.open(CACHE_NAME).then(cache => {
          cache.put(event.request, networkResponse.clone());
          return networkResponse;
        });
      })
      .catch(() => {
        // במקרה שאין אינטרנט לגולש - שולף מהזיכרון
        return caches.match(event.request);
      })
  );
});