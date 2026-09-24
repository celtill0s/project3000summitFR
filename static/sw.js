// Service worker (PWA) : démarrage instantané et hors-ligne partiel.
// Servi à la racine (/sw.js, jamais sous /v/) pour que sa portée couvre tout le site.
//
// Stratégies :
// - page (navigation)            : réseau d'abord, dernière version en cache si hors-ligne ;
// - /v/<empreinte>/…             : cache d'abord (URL immuable, voir ASSET_PREFIX côté serveur) ;
// - /api/me, /mountains.json, /gpx/… : réseau d'abord, cache si hors-ligne ou réseau trop lent ;
// - miniatures, photos           : cache d'abord (nom de fichier jamais réutilisé) ;
// - tuiles OSM / IGN             : réseau d'abord (OSM exige la revalidation), cache hors-ligne.
// Jamais interceptés : écritures (POST/DELETE) et requêtes Range (lecture vidéo).
// Les caches personnels (pages, data, media) sont vidés par la page à chaque connexion et
// déconnexion (js/session-utils.js) : un autre compte sur le même appareil n'y a pas accès.

// v2 : passage aux comptes (données rangées par utilisateur) — purge des caches d'avant.
const CACHE = {
  pages: 'pages-v2',
  assets: 'assets-v1',
  data: 'data-v2',
  media: 'media-v2',
  tiles: 'tiles-v1'
};
const LIMIT = { media: 300, tiles: 3000 }; // nombre d'entrées max (les plus anciennes partent)
const TILE_HOSTS = ['tile.openstreetmap.org', 'data.geopf.fr'];
const IMAGE_RE = /\.(jpe?g|png|gif|webp)$/i;
const SLOW_NETWORK_MS = 4000; // au-delà, on sert le cache (réseau faible en montagne)

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const keep = new Set(Object.values(CACHE));
    for (const name of await caches.keys()) {
      if (!keep.has(name)) await caches.delete(name);
    }
    await self.clients.claim();
  })());
});

// La page envoie la liste des fichiers /v/… qu'elle a chargés (modules JS compris, que le
// HTML ne liste pas) : ils sont mis en cache pour un prochain démarrage hors-ligne.
self.addEventListener('message', (event) => {
  if (event.data?.type !== 'cache-assets') return;
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE.assets);
    for (const url of event.data.urls) {
      if (new URL(url).origin !== location.origin || await cache.match(url)) continue;
      const res = await fetch(url).catch(() => null);
      if (res?.ok) await cache.put(url, res);
    }
  })());
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET' || req.headers.has('range')) return;
  const url = new URL(req.url);

  if (url.origin === location.origin) {
    if (req.mode === 'navigate') {
      event.respondWith(page(req));
    } else if (url.pathname.startsWith('/v/')) {
      event.respondWith(cacheFirst(req, CACHE.assets));
    } else if (url.pathname === '/api/me' || url.pathname === '/mountains.json' || url.pathname.startsWith('/gpx/')) {
      // Clé de cache : le chemin, plus l'espace consulté (?space=, admin) pour ne pas mélanger.
      const space = url.searchParams.get('space');
      const key = url.origin + url.pathname + (space ? `?space=${encodeURIComponent(space)}` : '');
      event.respondWith(networkFirst(req, CACHE.data, { key, timeout: SLOW_NETWORK_MS }));
    } else if (url.pathname.startsWith('/thumbs/') || (url.pathname.startsWith('/photos/') && IMAGE_RE.test(url.pathname))) {
      event.respondWith(cacheFirst(req, CACHE.media, LIMIT.media));
    }
    return;
  }
  if (TILE_HOSTS.includes(url.hostname)) {
    event.respondWith(networkFirst(req, CACHE.tiles, { limit: LIMIT.tiles }));
  }
});

async function page(req) {
  const cache = await caches.open(CACHE.pages);
  try {
    const res = await fetch(req);
    // Seule la vraie page de la carte est gardée : jamais la page de connexion vers laquelle le
    // serveur redirige quand la session a expiré (res.redirected).
    if (res.ok && !res.redirected && new URL(res.url).pathname === '/') {
      const html = await res.clone().text();
      await cache.put('/', res.clone());
      pruneOldAssets(html);
    }
    return res;
  } catch {
    return (await cache.match('/')) || new Response(
      '<!doctype html><meta charset="utf-8"><title>Hors ligne</title>' +
      '<p style="font-family:sans-serif;padding:2em">Hors ligne, et l\'application n\'a pas encore été ouverte avec du réseau sur cet appareil.</p>',
      { status: 503, headers: { 'Content-Type': 'text/html; charset=utf-8' } }
    );
  }
}

// Après une mise à jour du site, les fichiers d'une ancienne empreinte ne servent plus.
async function pruneOldAssets(html) {
  const current = html.match(/\/v\/([0-9a-f]+)\//)?.[1];
  if (!current) return;
  const cache = await caches.open(CACHE.assets);
  for (const req of await cache.keys()) {
    if (!new URL(req.url).pathname.startsWith(`/v/${current}/`)) await cache.delete(req);
  }
}

async function cacheFirst(req, cacheName, limit) {
  const cache = await caches.open(cacheName);
  const cached = await cache.match(req);
  if (cached) return cached;
  const res = await fetch(req);
  if (res.ok) await put(cacheName, cache, req, res.clone(), limit);
  return res;
}

async function networkFirst(req, cacheName, { key = req, timeout, limit } = {}) {
  const cache = await caches.open(cacheName);
  const network = fetch(req).then(async (res) => {
    // Réponses opaques (requête sans CORS) : non mises en cache, leur taille réelle est
    // inconnue et le navigateur leur compte plusieurs Mo de quota chacune.
    if (res.ok && res.type !== 'opaque') await put(cacheName, cache, key, res.clone(), limit);
    return res;
  });
  try {
    if (!timeout) return await network;
    const cached = await cache.match(key);
    if (!cached) return await network;
    // Réseau trop lent : on sert le cache, la réponse réseau mettra le cache à jour ensuite.
    return await Promise.race([network, new Promise((resolve) => setTimeout(() => resolve(cached), timeout))]);
  } catch (err) {
    const cached = await cache.match(key);
    if (cached) return cached;
    throw err;
  }
}

// Élagage espacé (tous les 50 ajouts) : lister des milliers de clés à chaque tuile coûterait cher.
const putsSinceTrim = {};
async function put(cacheName, cache, key, res, limit) {
  await cache.put(key, res);
  if (!limit) return;
  putsSinceTrim[cacheName] = (putsSinceTrim[cacheName] || 0) + 1;
  if (putsSinceTrim[cacheName] < 50) return;
  putsSinceTrim[cacheName] = 0;
  const keys = await cache.keys();
  for (const old of keys.slice(0, Math.max(0, keys.length - limit))) await cache.delete(old);
}
