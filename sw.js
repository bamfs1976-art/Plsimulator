/* Service worker: offline shell for the PL Simulator.
 *
 * - network-first for the app shell and the model bundle (always fresh
 *   when online, last good copy when not)
 * - cache-first for the icons and manifest, which change rarely
 *
 * Everything the app needs at runtime is embedded in index.html as a
 * fallback, so shell + model.json is a complete offline experience.
 */
"use strict";
const CACHE = "plsim-v2";
const SHELL = ["./", "./index.html", "./model.json", "./og-render.js"];
const STATIC = ["./icon-192.png", "./icon-512.png", "./manifest.webmanifest"];

self.addEventListener("install", e => {
  e.waitUntil(caches.open(CACHE)
    .then(c => c.addAll(SHELL.concat(STATIC)))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

function networkFirst(req) {
  return fetch(req).then(res => {
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy));
    }
    return res;
  }).catch(() => caches.match(req, { ignoreSearch: true }));
}

function cacheFirst(req) {
  return caches.match(req).then(hit => hit || fetch(req).then(res => {
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then(c => c.put(req, copy));
    }
    return res;
  }));
}

self.addEventListener("fetch", e => {
  if (e.request.method !== "GET") return;
  const url = new URL(e.request.url);
  if (url.origin !== location.origin) return;
  const p = url.pathname;
  if (p.endsWith("/") || p.endsWith("/index.html") || p.endsWith("/model.json") || p.endsWith("/og-render.js")) {
    e.respondWith(networkFirst(e.request));
  } else if (/\/(icon-192\.png|icon-512\.png|manifest\.webmanifest)$/.test(p)) {
    e.respondWith(cacheFirst(e.request));
  }
});
