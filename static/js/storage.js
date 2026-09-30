// Bandeau rouge permanent quand l'espace de l'utilisateur (5 Go) est plein ou presque : le
// serveur joint l'espace occupé ({used, limit}) à /api/me et à chaque écriture de fichier.
const NEARLY_FULL = 0.95;

let enabled = false;
let refusedAt = null; // espace occupé lors du dernier envoi refusé faute de place

function gigabytes(bytes) {
  return (bytes / 1024 ** 3).toLocaleString('fr-FR', { maximumFractionDigits: 2, minimumFractionDigits: 2 });
}

export function updateStorage(storage, refused = false) {
  if (!enabled || !storage) return;
  const { used, limit } = storage;
  if (refused) refusedAt = used;
  else if (refusedAt !== null && used < refusedAt) refusedAt = null; // de la place a été libérée
  const full = used >= limit || refusedAt !== null;
  const show = full || used >= limit * NEARLY_FULL;
  const banner = document.getElementById('storage-banner');
  if (show) {
    banner.textContent = full
      ? `Espace plein : ${gigabytes(used)} Go utilisés sur ${gigabytes(limit)} Go. Tu ne peux plus ajouter de photos, vidéos ni traces GPX : supprimes-en pour libérer de la place.`
      : `Espace presque plein : ${gigabytes(used)} Go utilisés sur ${gigabytes(limit)} Go. Les prochains envois risquent d'être refusés : supprime des photos, vidéos ou traces GPX pour libérer de la place.`;
  }
  if (banner.hidden === !show) return;
  banner.hidden = !show;
  document.body.classList.toggle('has-storage-banner', show);
  window.dispatchEvent(new Event('resize')); // la carte Leaflet recalcule sa taille
}

// Seulement sur son propre espace : un admin qui consulte celui d'un autre ne voit pas le bandeau.
export function initStorageBanner(storage, ownSpace) {
  enabled = ownSpace;
  updateStorage(storage);
}
