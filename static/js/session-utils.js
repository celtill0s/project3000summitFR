// Petits outils de session partagés par la page de connexion et la carte (sans dépendance).

// En-tête exigé par le serveur sur toute écriture (protection contre les requêtes forgées depuis
// un autre site : ce dernier ne peut pas l'ajouter sans autorisation CORS, jamais accordée).
export const CSRF_HEADERS = { 'X-Requested-With': 'SommetsApp' };

// Vide le cache hors-ligne des données personnelles (page, liste, photos) : appelé à chaque
// connexion et déconnexion, pour qu'un autre compte sur le même appareil n'y ait pas accès. Le
// code du site et les tuiles de carte (publics) sont conservés.
export async function clearPersonalCaches() {
  if (!('caches' in window)) return;
  try {
    for (const name of await caches.keys()) {
      if (/^(pages|data|media)-/.test(name)) await caches.delete(name);
    }
  } catch { /* stockage indisponible : rien à vider */ }
}
