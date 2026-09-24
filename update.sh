#!/bin/bash
# Met à jour le déploiement : récupère la dernière version du code (git pull)
# et reconstruit/relance les conteneurs. Les données personnelles (data/, secrets/)
# ne sont jamais touchées : elles sont hors du dépôt git (voir .gitignore).
#
# Pas de `docker compose down` préalable : si le pull échoue, l'appli continue de tourner
# avec la version actuelle ; `up -d --build` ne recrée que les conteneurs dont l'image change.
set -euo pipefail
cd "$(dirname "$0")"

echo "→ Récupération de la dernière version (git pull)…"
git pull --ff-only

echo "→ Reconstruction et redémarrage…"
docker compose up -d --build

echo "✓ Mise à jour terminée."
