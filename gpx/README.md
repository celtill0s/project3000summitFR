# Dossier `gpx/`

Traces GPX associées aux sommets de `../mountains.json`, versionnées avec
le reste du dépôt (pas de `.gitignore` sur ce dossier — c'est voulu).

## Ajouter une trace de façon durable

1. Copie le fichier `.gpx` ici (ex. `mont-thabor.gpx`).
2. Dans `../mountains.json`, ajoute un champ `"gpx"` sur l'entrée du
   sommet concerné :

   ```json
   {
     "name": "Mont Thabor",
     ...
     "gpx": "gpx/mont-thabor.gpx"
   }
   ```

3. Commite les deux fichiers. La carte (`index.html`) chargera et
   affichera automatiquement cette trace à chaque visite, sur n'importe
   quel appareil — pas besoin de la réimporter à chaque fois.

## Alternative : import direct depuis l'app

Le bouton "🧭 Importer un GPX" dans la popup d'un sommet fonctionne aussi
sans passer par ce dossier : la trace est alors seulement sauvegardée dans
le `localStorage` du navigateur utilisé, pas dans le dépôt. Depuis la
popup, le bouton "⬇ Télécharger le GPX" permet de récupérer le fichier
correspondant pour le placer ici et le committer si tu veux le rendre
permanent/partagé entre appareils.
