#!/bin/bash
# Met à jour le déploiement : récupère la dernière version du code (git pull)
# et relance les conteneurs. Les données personnelles (data/, secrets/) ne sont
# jamais touchées : elles sont hors du dépôt git (voir .gitignore).
set -euo pipefail
cd "$(dirname "$0")"

trap 'echo "⚠️  Erreur pendant la mise à jour — tentative de redémarrage avec le code actuel."; docker compose up -d --build' ERR

echo "→ Arrêt des conteneurs…"
docker compose down

echo "→ Récupération de la dernière version (git pull)…"
git pull

echo "→ Reconstruction et redémarrage…"
docker compose up -d --build

trap - ERR
echo "✓ Mise à jour terminée."
