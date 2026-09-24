// Petits utilitaires sans dépendance (échappement HTML, types de fichiers).
export function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

export function isVideoFile(filename) {
  return /\.(mp4|webm|mov|m4v|ogv|avi|mkv)$/i.test(filename || '');
}

// HEIC/HEIF (photos iPhone) : affichable nativement par Safari uniquement.
export function isHeicFile(filename) {
  return /\.(heic|heif)$/i.test(filename || '');
}

// Le catalogue est éditable par quiconque forke le dépôt : tous ses champs sont échappés avant
// insertion dans le HTML, et seuls les liens http(s) sont rendus cliquables.
export function safeUrl(url) {
  return /^https?:\/\//i.test(url || '') ? url : '';
}
