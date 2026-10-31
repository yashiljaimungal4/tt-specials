// TT Deals service worker: offline shell + push notifications
const CACHE = "tt-deals-v2";
const SHELL = ["./", "index.html", "manifest.json", "icons/icon-192.png", "icons/badge-96.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

// Network first (fresh deals), fall back to cache when offline
self.addEventListener("fetch", (e) => {
  if (e.request.method !== "GET" || new URL(e.request.url).origin !== location.origin) return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request, { ignoreSearch: true }))
  );
});

self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = { title: "TT Deals", body: e.data ? e.data.text() : "" }; }
  const opts = {
    body: d.body || "",
    icon: "icons/icon-192.png",
    badge: "icons/badge-96.png",
    tag: d.tag || undefined,
    renotify: !!d.tag,
    requireInteraction: !!d.urgent,
    data: { url: d.url || "./" },
  };
  if (d.image) opts.image = d.image;
  e.waitUntil(self.registration.showNotification(d.title || "TT Deals", opts));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "./";
  e.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      const inApp = url.startsWith(self.registration.scope);
      if (inApp) {
        for (const c of list) {
          if (c.url.startsWith(self.registration.scope)) { c.navigate(url); return c.focus(); }
        }
      }
      return self.clients.openWindow(url);
    })
  );
});
