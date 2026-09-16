#!/bin/bash
# Sauvegarde data/ (progress.json, photos/, gpx/ — tout ce qui n'est pas dans git) vers des
# snapshots datés, hors du dossier de l'appli. Utilise rsync --link-dest : les fichiers
# identiques au snapshot précédent sont des liens durs, pas des copies — chaque snapshot est
# donc "complet" à restaurer (simple cp) sans dupliquer l'espace disque des fichiers inchangés.
#
# Ne protège PAS contre une panne physique de la carte SD/du disque du Pi (tout reste sur le
# même support) : seulement contre une suppression/corruption accidentelle côté application.
# Pour une vraie protection matérielle, copier BACKUP_ROOT vers un autre disque/service.
set -euo pipefail
cd "$(dirname "$0")/.."

DATA_DIR="${DATA_DIR:-$(pwd)/data}"
BACKUP_ROOT="${BACKUP_ROOT:-$HOME/backups-project3000summitFR}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
STAMP=$(date +%Y%m%d-%H%M%S)
DEST="$BACKUP_ROOT/$STAMP"
LATEST_LINK="$BACKUP_ROOT/latest"

if [ ! -d "$DATA_DIR" ]; then
  echo "$(date -Is) [backup] data/ introuvable ($DATA_DIR), rien à sauvegarder." >&2
  exit 1
fi

mkdir -p "$BACKUP_ROOT"

LINK_DEST_ARGS=()
if [ -e "$LATEST_LINK" ]; then
  LINK_DEST_ARGS=(--link-dest="$(readlink -f "$LATEST_LINK")")
fi

rsync -a "${LINK_DEST_ARGS[@]}" "$DATA_DIR/" "$DEST/"
rm -f "$LATEST_LINK"
ln -s "$DEST" "$LATEST_LINK"

echo "$(date -Is) [backup] snapshot créé -> $DEST"

# Purge des snapshots plus vieux que RETENTION_DAYS (le lien symbolique "latest" n'est jamais
# supprimé par cette commande, seuls les dossiers datés le sont).
find "$BACKUP_ROOT" -maxdepth 1 -type d -name '20*' -mtime "+$RETENTION_DAYS" -print -exec rm -rf {} \;
