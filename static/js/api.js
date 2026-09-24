// Appels au backend (toute la persistance est côté serveur) et URLs des médias.
import { isHeicFile, isVideoFile } from './util.js';
import { CSRF_HEADERS } from './session-utils.js';
import { session } from './store.js';

// --- Appels au backend : toute écriture (coché, commentaire, photos/vidéos, gpx) part
// directement vers le serveur, qui la persiste sur son propre disque (data/). Plus de
// localStorage, plus d'IndexedDB, plus de File System Access API — le serveur EST la
// persistance, quel que soit l'appareil/navigateur utilisé pour consulter le site.
// Routes par id de sommet (stable), jamais par nom : renommer un sommet ne casse rien.
export const peakApiBase = p => `/api/peaks/${encodeURIComponent(p.id)}`;

// Réponse 401 : session expirée ou révoquée (déconnexion ailleurs, mot de passe changé…) →
// retour à la page de connexion.
async function checked(res) {
  if (res.status === 401) {
    location.replace('/login');
    throw new Error('session expirée');
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || ('HTTP ' + res.status));
  return res;
}

export async function apiGet(url) {
  return (await checked(await fetch(url, { cache: 'no-store' }))).json();
}

export async function apiPost(url, body) {
  const res = await checked(await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...CSRF_HEADERS },
    body: JSON.stringify(body)
  }));
  return res.json().catch(() => ({}));
}

export async function apiDelete(url) {
  const res = await checked(await fetch(url, { method: 'DELETE', headers: CSRF_HEADERS }));
  return res.json().catch(() => ({}));
}

// Envoi du fichier brut (pas de multipart) : le serveur l'écrit sur disque au fil de l'eau,
// sans jamais le charger entièrement en mémoire. Le nom d'origine ne sert qu'à l'extension.
export async function apiUpload(url, file) {
  const sep = url.includes('?') ? '&' : '?';
  const res = await checked(await fetch(`${url}${sep}filename=${encodeURIComponent(file.name)}`, {
    method: 'POST',
    headers: { 'Content-Type': file.type || 'application/octet-stream', ...CSRF_HEADERS },
    body: file
  }));
  return res.json();
}

// URLs d'un média : original, miniature (grille) et version affichable dans la visionneuse
// (JPEG converti par le serveur pour le HEIC, l'original sinon). Sans Pillow côté serveur,
// /thumbs/ renvoie simplement l'original.
// Les fichiers sont rangés par espace (utilisateur) : /photos/<utilisateur>/<sommet>/<fichier>.
export function mediaUrls(p, filename) {
  const owner = encodeURIComponent(session.space);
  const id = encodeURIComponent(p.id);
  const file = encodeURIComponent(filename);
  const original = `/photos/${owner}/${id}/${file}`;
  if (isVideoFile(filename)) return { thumb: original, full: original };
  return {
    thumb: `/thumbs/${owner}/480/${id}/${file}`,
    full: isHeicFile(filename) ? `/thumbs/${owner}/1920/${id}/${file}` : original
  };
}
