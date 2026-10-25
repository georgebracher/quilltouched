/*
 * Quilltouched service worker — app-shell only.
 *
 * Cache-first for the static shell (index, manifest, icons, hashed
 * build assets). /api/* is NEVER cached or intercepted: game state is
 * server-authoritative and must always hit the network.
 *
 * Scene art (/sprites/, /backgrounds/) is runtime-cached after first
 * fetch, not precached — ~28MB of PNGs would make install hostile on
 * mobile data; scenes you have visited keep rendering offline.
 *
 * The required shell is only what every build has; the PNG icons are cached
 * when present (the public copy ships no images, and one missing file would
 * otherwise fail the whole install).
 *
 * Bump the cache version when the shell strategy changes.
 */
const CACHE_NAME = 'eq-shell-v13';

const SHELL = ['/', '/index.html', '/manifest.webmanifest', '/favicon.svg'];
const OPTIONAL = ['/icons/icon-192.png', '/icons/icon-512.png'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches
      .open(CACHE_NAME)
      .then((cache) =>
        cache
          .addAll(SHELL)
          .then(() => Promise.all(OPTIONAL.map((url) => cache.add(url).catch(() => undefined)))),
      )
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return; // never touch cross-origin
  if (url.pathname.startsWith('/api/')) return; // API is network-only, always

  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request)
        .then((response) => {
          // Runtime-cache the shell's own hashed build assets (so the
          // installed shell keeps booting offline) plus scene art on
          // first use (sprites/backgrounds are immutable per filename).
          const isShellAsset =
            url.pathname.startsWith('/assets/') ||
            url.pathname.startsWith('/sprites/') ||
            url.pathname.startsWith('/backgrounds/') ||
            SHELL.includes(url.pathname);
          if (response.ok && isShellAsset) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(async () => {
          if (request.mode === 'navigate') {
            const shell = await caches.match('/');
            if (shell) return shell;
          }
          return Response.error();
        });
    }),
  );
});
