# topMountains

Carte interactive (Leaflet + fonds OpenStreetMap) des sommets de plus de
3000 m des **Alpes françaises** et des **Pyrénées françaises** accessibles
à pied, sans matériel d'alpinisme (pas de glacier obligatoire, pas de
corde, pas de via ferrata).

## Utilisation

Le fichier `index.html` charge les données via `fetch('mountains.json')`,
ce qui ne fonctionne pas en ouvrant le fichier directement dans le
navigateur (`file://`) à cause des restrictions CORS. Lancer un petit
serveur local depuis ce dossier :

```bash
python3 -m http.server 8000
```

puis ouvrir <http://localhost:8000>.

## Contenu

- **`index.html`** — la carte : panneau latéral (recherche, filtres par
  massif/difficulté/statut, liste triée par altitude), carte Leaflet avec
  un **calque par niveau de difficulté** (T2/T3/T4, activables/
  désactivables via le sélecteur de calques en haut à droite), popups
  détaillées par sommet.
- **`mountains.json`** — les données : nom, altitude, coordonnées, massif,
  région, cotation de difficulté (échelle CAS/SAC), notes d'accès, source.
- **`sources.md`** — méthodologie complète : comment chaque sommet a été
  sélectionné, comment sa cotation a été déterminée, sources utilisées et
  limites connues.

## Fonctionnalités

- **Calques par difficulté** : chaque niveau de cotation (T2, T3, T4) est
  un calque Leaflet indépendant, à afficher/masquer via le contrôle en
  haut à droite de la carte ou les puces de la barre latérale (les deux
  restent synchronisés).
- **Filtres** : par massif (Alpes/Pyrénées), par difficulté, par statut
  (fait / à faire), et recherche texte libre (nom, massif).
- **Suivi "sommet fait"** : une case à cocher (dans la liste et dans
  chaque popup) permet de marquer un sommet comme fait. L'état est
  sauvegardé automatiquement dans le `localStorage` du navigateur (propre
  à cet appareil/navigateur, non partagé).
- **Export/Import de la progression** : bouton "Exporter" (barre latérale)
  télécharge un fichier `progress.json` avec la liste des sommets faits.
  Le bouton "Importer" recharge un `progress.json` précédemment exporté
  (fusion ou remplacement, au choix). Utile pour ne pas perdre sa
  progression si le navigateur est réinstallé ou ses données effacées —
  penser à exporter régulièrement et à garder ce fichier quelque part de
  sûr (données personnelles : volontairement **non versionné**, voir
  `.gitignore`). Le `localStorage` seul n'est **pas** garanti de survivre
  à un nettoyage du navigateur.
- **Trace GPX par sommet** : dans la popup d'un sommet, bouton "Importer un
  GPX" pour associer un fichier `.gpx` (export d'une appli comme
  Visorando, Komoot, Openrunner…) à ce sommet. La trace est aussitôt
  dessinée sur la carte (calque "Traces GPX", activable/désactivable comme
  les autres) et sauvegardée dans le `localStorage` du navigateur pour se
  recharger automatiquement au prochain chargement de la page. Comme pour
  la progression, ces traces sont des données personnelles et ne sont
  **pas** versionnées (`.gitignore`) — c'est du stockage propre à
  l'appareil/navigateur utilisé, pas de sauvegarde automatique ailleurs.

## Modifier les données

Éditer `mountains.json` directement (tableau JSON, un objet par sommet).
Chaque entrée suit ce schéma :

```json
{
  "name": "Nom du sommet",
  "altitude_m": 3025,
  "lat": 44.6783,
  "lon": 6.9636,
  "massif": "Nom du massif",
  "region": "Alpes" ou "Pyrénées",
  "difficulty": "T2" | "T3" | "T4",
  "notes": "Description courte de l'itinéraire/accès",
  "source": "domaine-source.fr"
}
```

Voir `sources.md` pour le barème de cotation et les sources de référence à
utiliser pour toute nouvelle entrée.
