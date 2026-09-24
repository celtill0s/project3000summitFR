#!/bin/bash
# Met à jour le déploiement : récupère la dernière version du code (git pull)
# et reconstruit/relance les conteneurs. Les données personnelles (data/, secrets/)
# ne sont jamais touchées : elles sont hors du dépôt git (voir .gitignore).
#
# Pas de `docker compose down` préalable : si le pull échoue, l'appli continue de tourner
# avec la version actuelle ; `up -d --build` ne recrée que les conteneurs dont l'image change.
#
# Tout le script est dans une fonction appelée à la dernière ligne : bash lit ainsi le fichier
# en entier AVANT d'exécuter quoi que ce soit. Sans ça, le `git pull` qui modifie update.sh
# pendant son exécution ferait lire à bash la nouvelle version à l'ancienne position.
set -euo pipefail

main() {
  cd "$(dirname "$0")"

  echo "→ Récupération de la dernière version (git pull)…"
  git pull --ff-only

  echo "→ Reconstruction et redémarrage…"
  docker compose up -d --build

  echo "✓ Mise à jour terminée."
  exit
}

main "$@"
