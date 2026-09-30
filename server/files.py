"""Traitement des fichiers : pages HTML versionnées, GPX, miniatures, plages d'octets, chemins.

Seule dépendance optionnelle : Pillow (+ pillow-heif) pour les miniatures et la conversion
HEIC → JPEG. Sans elle, les photos originales sont servies telles quelles.
"""
import hashlib
import os
import re
import secrets
import xml.etree.ElementTree as ET
from pathlib import Path

from . import storage
from .errors import ApiError

try:
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:  # pragma: no cover - HEIC simplement non converti
        pass
except ImportError:  # pragma: no cover - dépend de l'environnement
    Image = None

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".ogv", ".avi", ".mkv"}
# Tailles (plus grand côté, en px) des images redimensionnées servies sous /thumbs/ :
# 480 pour la grille de miniatures, 1920 pour la visionneuse quand l'original n'est pas
# affichable partout (HEIC).
THUMB_SIZES = {480, 1920}

# URLs versionnées des fichiers du site : les pages (jamais mises en cache) référencent
# /v/<empreinte>/js/main.js, /v/<empreinte>/style.css… L'empreinte change dès qu'un fichier
# change, donc chaque mise à jour produit de nouvelles URLs qu'aucun cache (navigateur,
# Cloudflare…) ne peut servir périmées — y compris les modules importés en relatif par
# main.js, qui héritent du préfixe. Ces fichiers peuvent alors être cachés longtemps.
ASSET_PREFIX = "/v/"
RELATIVE_ASSET_RE = re.compile(r'((?:href|src)=")(?![a-z]+:|/|#)([^"]+)"')
# Extensions autorisées pour le service de fichiers statiques génériques (style.css, app.js…) —
# whitelist explicite plutôt que "tout ce qui n'est pas une route API", pour ne jamais exposer
# par erreur un fichier qui traînerait dans static/ (ex. un .py ou un .bak).
STATIC_ASSET_EXTS = {".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".webmanifest"}


def asset_version() -> str:
    """Empreinte des fichiers statiques (chemin, taille, date de modification). Recalculée à
    chaque chargement de page (une vingtaine de stat(), négligeable) : en développement, une
    modification de fichier change aussitôt l'empreinte, sans redémarrer le serveur."""
    h = hashlib.sha256()
    static_dir = storage.STATIC_DIR
    for f in sorted(static_dir.rglob("*")):
        if f.is_file() and f.suffix.lower() in STATIC_ASSET_EXTS:
            st = f.stat()
            h.update(f"{f.relative_to(static_dir)}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:12]


def render_page(name: str) -> bytes:
    """Page HTML de static/ avec ses références relatives (style.css, js/main.js, vendor/…)
    réécrites vers le préfixe versionné."""
    html = (storage.STATIC_DIR / name).read_text(encoding="utf-8")
    prefix = f"{ASSET_PREFIX}{asset_version()}/"
    return RELATIVE_ASSET_RE.sub(lambda m: f'{m.group(1)}{prefix}{m.group(2)}"', html).encode("utf-8")


def validate_gpx(payload: bytes):
    # Pas de DTD/entités : un GPX légitime n'en a jamais besoin, et ça écarte d'office les
    # attaques par expansion d'entités ("billion laughs").
    if b"<!DOCTYPE" in payload or b"<!ENTITY" in payload:
        raise ApiError(400, "GPX invalide : DOCTYPE/ENTITY non autorisés")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        raise ApiError(400, "GPX invalide : XML mal formé")
    if root.tag.rsplit("}", 1)[-1] != "gpx":
        raise ApiError(400, "GPX invalide : l'élément racine doit être <gpx>")


def parse_range(header, size):
    """Interprète un en-tête "Range: bytes=..." (une seule plage). Renvoie (début, fin
    incluse), None si l'en-tête est absent/ignoré, ou lève ApiError(416) si insatisfiable."""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", (header or "").strip())
    if not m or m.group(1) == m.group(2) == "":
        return None
    start_s, end_s = m.groups()
    if start_s == "":  # suffixe : les N derniers octets
        start, end = max(0, size - int(end_s)), size - 1
    else:
        start = int(start_s)
        end = min(int(end_s), size - 1) if end_s else size - 1
    if start >= size or start > end:
        raise ApiError(416, "plage invalide")
    return start, end


def make_thumbnail(src: Path, dest: Path, size: int):
    """Génère une version JPEG redimensionnée (orientation EXIF appliquée). Écrit dans un
    fichier temporaire puis renomme : deux requêtes simultanées ne produisent jamais un
    fichier à moitié écrit."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tmp")
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail((size, size))
            im.convert("RGB").save(tmp, "JPEG", quality=82, optimize=True)
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)


def safe_rel_path(base: Path, rel: str) -> Path:
    """Anti path-traversal : ne jamais faire confiance à un chemin fourni par le client."""
    candidate = (base / rel).resolve()
    base_resolved = base.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise ApiError(400, "chemin invalide")
    return candidate
