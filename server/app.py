#!/usr/bin/env python3
"""Backend minimal (bibliothèque standard uniquement) pour project3000summitFR.

Sert le frontend statique et fusionne, à la volée, le catalogue public
(static/mountains.json, versionné dans git) avec l'overlay privé
(data/progress.json, JAMAIS commité) qui contient l'état personnel :
coché, commentaire, photos/vidéos, trace GPX.

Toute écriture (coché/commentaire/upload) passe par ce serveur et va
directement sur le disque local (data/) — pas de localStorage, pas
d'IndexedDB, pas de dépendance au navigateur.

Chaque sommet est identifié par son champ "id" (stable) : les données personnelles y sont
rattachées, pas au nom — renommer un sommet dans le catalogue ne perd donc rien.

Seule dépendance optionnelle : Pillow (+ pillow-heif) pour les miniatures et la conversion
HEIC → JPEG. Sans elle, les photos originales sont servies telles quelles.
"""
import hashlib
import json
import mimetypes
import os
import re
import secrets
import threading
import traceback
import unicodedata
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    from PIL import Image, ImageOps
    try:
        from pillow_heif import register_heif_opener
        register_heif_opener()
    except ImportError:  # pragma: no cover - HEIC simplement non converti
        pass
except ImportError:  # pragma: no cover - dépend de l'environnement
    Image = None

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(os.environ.get("STATIC_DIR", ROOT / "static"))
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
CATALOG_PATH = STATIC_DIR / "mountains.json"
PROGRESS_PATH = DATA_DIR / "progress.json"
PHOTOS_DIR = DATA_DIR / "photos"
GPX_DIR = DATA_DIR / "gpx"
THUMBS_DIR = DATA_DIR / "thumbs"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".ogv", ".avi", ".mkv"}
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_GPX_BYTES = 20 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
CHUNK_BYTES = 1024 * 1024
# Tailles (plus grand côté, en px) des images redimensionnées servies sous /thumbs/ :
# 480 pour la grille de miniatures, 1920 pour la visionneuse quand l'original n'est pas
# affichable partout (HEIC).
THUMB_SIZES = {480, 1920}
# Politiques de cache. Code du site et traces GPX : revalidés à chaque chargement (ETag -> 304
# si inchangé, donc quasi gratuit) — sans ça, un navigateur peut garder l'ancien JS après une
# mise à jour alors que la page (et sa CSP) sont déjà nouvelles. Photos : nom aléatoire jamais
# réutilisé, donc cache long. Miniatures : un jour (leur contenu change si Pillow est ajouté).
# "private" : tout le site est derrière une Basic Auth, aucun cache partagé ne doit les garder.
CACHE_REVALIDATE = "no-cache"
CACHE_IMMUTABLE = "private, max-age=31536000, immutable"
CACHE_THUMB = "private, max-age=86400"

# URLs versionnées des fichiers du site : index.html (jamais mis en cache) référence
# /v/<empreinte>/js/main.js, /v/<empreinte>/style.css… L'empreinte change dès qu'un fichier
# change, donc chaque mise à jour produit de nouvelles URLs qu'aucun cache (navigateur,
# Cloudflare…) ne peut servir périmées — y compris les modules importés en relatif par
# main.js, qui héritent du préfixe. Ces fichiers peuvent alors être cachés longtemps.
ASSET_PREFIX = "/v/"
RELATIVE_ASSET_RE = re.compile(r'((?:href|src)=")(?![a-z]+:|/|#)([^"]+)"')
# Extensions autorisées pour le service de fichiers statiques génériques (style.css, app.js…) —
# whitelist explicite plutôt que "tout ce qui n'est pas une route API", pour ne jamais exposer
# par erreur un fichier qui traînerait dans static/ (ex. un .py ou un .bak).
STATIC_ASSET_EXTS = {".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico"}

# Tout est servi depuis la même origine (Leaflet est vendorisé dans static/vendor/) : seules
# les tuiles de carte (OpenStreetMap, IGN Géoplateforme) viennent d'ailleurs. 'unsafe-inline' pour les styles uniquement
# (attributs style="" générés par le frontend), jamais pour les scripts.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https://tile.openstreetmap.org https://data.geopf.fr",
    "media-src 'self' blob:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

mimetypes.add_type("application/gpx+xml", ".gpx")

lock = threading.Lock()


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


def slugify(name: str) -> str:
    n = unicodedata.normalize("NFD", name.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
    return n or "sommet"


def load_catalog():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def find_peak(catalog, peak_id):
    for p in catalog:
        if p["id"] == peak_id:
            return p
    raise KeyError(peak_id)


def migrate_progress(progress, catalog):
    """Rattache à l'id du sommet les entrées de progress.json encore indexées par son nom
    (format d'avant les ids). Renvoie (progress, changé ?, clés orphelines)."""
    ids = {p["id"] for p in catalog}
    id_by_name = {p["name"]: p["id"] for p in catalog}
    changed = False
    orphans = []
    for key in list(progress):
        if key in ids:
            continue
        if key in id_by_name:
            target = progress.setdefault(id_by_name[key], {})
            for field, value in progress.pop(key).items():
                target.setdefault(field, value)
            changed = True
        else:
            orphans.append(key)
    return progress, changed, orphans


def load_progress(catalog=None):
    if not PROGRESS_PATH.exists():
        return {}
    with open(PROGRESS_PATH, encoding="utf-8") as f:
        progress = json.load(f)
    return migrate_progress(progress, catalog if catalog is not None else load_catalog())[0]


def save_progress(data):
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_PATH)  # écriture atomique : jamais de JSON tronqué en cas de crash


def merged_peaks():
    catalog = load_catalog()
    progress = load_progress(catalog)
    out = []
    for p in catalog:
        overlay = progress.get(p["id"], {})
        merged = dict(p)
        merged["done"] = bool(overlay.get("done", False))
        merged["comment"] = overlay.get("comment", "")
        merged["photos"] = [ph["filename"] for ph in overlay.get("photos", [])]
        if overlay.get("gpx"):
            merged["gpx"] = f"/gpx/{p['id']}.gpx"
        out.append(merged)
    return out


def asset_version() -> str:
    """Empreinte des fichiers statiques (chemin, taille, date de modification). Recalculée à
    chaque chargement de page (une vingtaine de stat(), négligeable) : en développement, une
    modification de fichier change aussitôt l'empreinte, sans redémarrer le serveur."""
    h = hashlib.sha256()
    for f in sorted(STATIC_DIR.rglob("*")):
        if f.is_file() and f.suffix.lower() in STATIC_ASSET_EXTS:
            st = f.stat()
            h.update(f"{f.relative_to(STATIC_DIR)}\0{st.st_size}\0{st.st_mtime_ns}\n".encode())
    return h.hexdigest()[:12]


def render_index() -> bytes:
    """index.html avec ses références relatives (style.css, js/main.js, vendor/…) réécrites
    vers le préfixe versionné."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
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


class Handler(BaseHTTPRequestHandler):
    server_version = "SummitFR/1.0"
    protocol_version = "HTTP/1.1"

    # ---- utilitaires de réponse ----
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        # strict-origin-when-cross-origin (et surtout pas same-origin/no-referrer) : les serveurs de
        # tuiles OpenStreetMap EXIGENT un Referer (politique d'usage), sinon « Access blocked ».
        # Seule l'origine est envoyée hors du site, jamais le chemin de la page.
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        super().end_headers()

    def _write(self, data: bytes):
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self._write(body)

    def _server_error(self):
        # Le détail de l'exception reste dans les logs serveur, jamais renvoyé au client.
        traceback.print_exc()
        self._json(500, {"error": "erreur interne"})

    def _file(self, path: Path, content_type=None, cache_control=CACHE_REVALIDATE):
        """Sert un fichier par morceaux (jamais chargé entièrement en mémoire), avec support
        des requêtes Range — indispensable pour lire/avancer dans une vidéo, et exigé par
        Safari iOS pour lire la moindre vidéo — et des requêtes conditionnelles (ETag -> 304)."""
        try:
            resolved = path.resolve()
        except OSError:
            raise ApiError(404, "not found")
        if not resolved.is_file():
            raise ApiError(404, "not found")
        st = resolved.stat()
        size = st.st_size
        etag = f'"{st.st_mtime_ns:x}-{size:x}"'
        if_none_match = self.headers.get("If-None-Match", "")
        if etag in (t.strip().removeprefix("W/") for t in if_none_match.split(",")):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache_control)
            self.end_headers()
            return
        byte_range = parse_range(self.headers.get("Range"), size) if size else None
        start, end = byte_range or (0, size - 1)
        length = end - start + 1 if size else 0
        self.send_response(206 if byte_range else 200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(str(resolved))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        if byte_range:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", cache_control)
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(resolved, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(CHUNK_BYTES, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _content_length(self, max_bytes):
        raw = self.headers.get("Content-Length")
        if raw is None:
            self.close_connection = True
            raise ApiError(411, "Content-Length requis")
        try:
            length = int(raw)
        except ValueError:
            self.close_connection = True
            raise ApiError(400, "Content-Length invalide")
        if length > max_bytes:
            # Corps non lu : la connexion ne peut pas être réutilisée pour une autre requête.
            self.close_connection = True
            raise ApiError(413, "fichier trop volumineux")
        return length

    def _read_body(self, max_bytes):
        length = self._content_length(max_bytes)
        return self.rfile.read(length) if length > 0 else b""

    def _read_json(self):
        try:
            return json.loads(self._read_body(MAX_JSON_BYTES) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "JSON invalide")

    def _stream_body_to(self, dest: Path, max_bytes):
        """Écrit le corps de la requête sur disque par morceaux de 1 Mo : même une vidéo de
        500 Mo ne passe jamais entièrement en mémoire (important sur un Raspberry Pi)."""
        remaining = self._content_length(max_bytes)
        if remaining == 0:
            raise ApiError(400, "fichier vide")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(f".{dest.name}.upload")
        try:
            with open(tmp, "wb") as f:
                while remaining > 0:
                    chunk = self.rfile.read(min(CHUNK_BYTES, remaining))
                    if not chunk:
                        raise ApiError(400, "envoi interrompu")
                    f.write(chunk)
                    remaining -= len(chunk)
            os.replace(tmp, dest)
        except BaseException:
            tmp.unlink(missing_ok=True)
            self.close_connection = True
            raise

    def _route_peak(self, path):
        """/api/peaks/<id>/<suite> -> (id, suite)."""
        rest = path[len("/api/peaks/"):]
        parts = rest.split("/", 1)
        return unquote(parts[0]), (parts[1] if len(parts) > 1 else "")

    # ---- anti path-traversal : ne jamais faire confiance à un chemin fourni par le client ----
    def _safe_rel_path(self, base: Path, rel: str) -> Path:
        candidate = (base / rel).resolve()
        base_resolved = base.resolve()
        if base_resolved not in candidate.parents and candidate != base_resolved:
            raise ApiError(400, "chemin invalide")
        return candidate

    def _dispatch(self, handler):
        try:
            handler(urlparse(self.path))
            return
        except ApiError as e:
            self._json(e.status, {"error": e.message})
        except KeyError:
            self._json(404, {"error": "sommet inconnu"})
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # client parti (ex. vidéo refermée) : rien à répondre
        except Exception:
            self._server_error()
        # Après une erreur, le corps d'un POST a pu rester (partiellement) non lu : la connexion
        # ne doit pas être réutilisée, sinon ces octets seraient pris pour la requête suivante.
        if self.command == "POST":
            self.close_connection = True

    # ---- routes ----
    def do_GET(self):
        self._dispatch(self._get)

    def do_HEAD(self):
        self._dispatch(self._get)

    def do_POST(self):
        self._dispatch(self._post)

    def do_DELETE(self):
        self._dispatch(self._delete)

    def _get(self, parsed):
        path = parsed.path
        if path == "/healthz":
            self._json(200, {"ok": True})
        elif path in ("/", "/index.html"):
            body = render_index()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")  # toujours la dernière empreinte
            self.end_headers()
            self._write(body)
        elif path.startswith(ASSET_PREFIX):
            # /v/<empreinte>/<fichier> : l'empreinte ne sert qu'à changer l'URL, on sert toujours
            # le fichier actuel (une vieille page en cache obtient donc des fichiers à jour).
            parts = unquote(path[len(ASSET_PREFIX):]).split("/", 1)
            if len(parts) != 2 or Path(parts[1]).suffix.lower() not in STATIC_ASSET_EXTS:
                raise ApiError(404, "not found")
            self._file(self._safe_rel_path(STATIC_DIR, parts[1]), cache_control=CACHE_IMMUTABLE)
        elif path == "/mountains.json":
            self._json(200, merged_peaks())
        elif path.startswith("/photos/"):
            rel = unquote(path[len("/photos/"):])
            self._file(self._safe_rel_path(PHOTOS_DIR, rel), cache_control=CACHE_IMMUTABLE)
        elif path.startswith("/thumbs/"):
            self._thumb(unquote(path[len("/thumbs/"):]))
        elif path.startswith("/gpx/"):
            rel = unquote(path[len("/gpx/"):])
            self._file(self._safe_rel_path(GPX_DIR, rel))
        elif Path(unquote(path)).suffix.lower() in STATIC_ASSET_EXTS:
            # URLs non versionnées : conservées (pages en cache d'avant le versionnage), revalidées.
            rel = unquote(path).lstrip("/")
            self._file(self._safe_rel_path(STATIC_DIR, rel))
        else:
            raise ApiError(404, "not found")

    def _post(self, parsed):
        path = parsed.path
        if not path.startswith("/api/peaks/"):
            raise ApiError(404, "not found")
        peak_id, tail = self._route_peak(path)
        if tail == "done":
            self._set_field(peak_id, "done", bool(self._read_json().get("done")))
        elif tail == "comment":
            self._set_field(peak_id, "comment", str(self._read_json().get("comment", ""))[:20000])
        elif tail == "photos":
            filename = parse_qs(parsed.query).get("filename", [""])[0]
            self._add_photo(peak_id, filename)
        elif tail == "gpx":
            self._add_gpx(peak_id)
        else:
            raise ApiError(404, "route inconnue")

    def _delete(self, parsed):
        path = parsed.path
        if not path.startswith("/api/peaks/"):
            raise ApiError(404, "not found")
        peak_id, tail = self._route_peak(path)
        if tail.startswith("photos/"):
            self._delete_photo(peak_id, unquote(tail[len("photos/"):]))
        elif tail == "gpx":
            self._delete_gpx(peak_id)
        else:
            raise ApiError(404, "route inconnue")

    # ---- actions ----
    def _thumb(self, rel):
        """/thumbs/<id>/<taille>/<fichier> : version JPEG redimensionnée d'une photo, générée
        à la première demande puis mise en cache dans data/thumbs/. Sans Pillow (ou si
        l'image est illisible), l'original est servi à la place."""
        parts = rel.split("/")
        if len(parts) != 3 or not parts[1].isdigit() or int(parts[1]) not in THUMB_SIZES:
            raise ApiError(404, "not found")
        peak_id, size, filename = parts[0], int(parts[1]), parts[2]
        src = self._safe_rel_path(PHOTOS_DIR, f"{peak_id}/{filename}")
        if not src.is_file():
            raise ApiError(404, "not found")
        if Image is None or src.suffix.lower() not in IMAGE_EXTS:
            self._file(src, cache_control=CACHE_THUMB)
            return
        dest = self._safe_rel_path(THUMBS_DIR, f"{peak_id}/{size}/{filename}.jpg")
        if not dest.is_file():
            try:
                make_thumbnail(src, dest, size)
            except Exception:
                traceback.print_exc()
                self._file(src, cache_control=CACHE_THUMB)
                return
        self._file(dest, "image/jpeg", cache_control=CACHE_THUMB)

    def _set_field(self, peak_id, field, value):
        with lock:
            catalog = load_catalog()
            find_peak(catalog, peak_id)
            progress = load_progress(catalog)
            progress.setdefault(peak_id, {})[field] = value
            save_progress(progress)
        self._json(200, {"ok": True})

    def _add_photo(self, peak_id, filename):
        find_peak(load_catalog(), peak_id)
        ext = Path(filename).suffix.lower()
        is_video = ext in VIDEO_EXTS
        if not (is_video or ext in IMAGE_EXTS):
            self.close_connection = True
            raise ApiError(400, f"extension non supportée : {ext or '(aucune)'}")
        safe_name = f"{secrets.token_hex(4)}{ext}"
        # L'écriture (potentiellement longue) se fait hors du verrou ; seule la mise à jour de
        # progress.json, instantanée, est sérialisée.
        self._stream_body_to(PHOTOS_DIR / peak_id / safe_name, MAX_VIDEO_BYTES if is_video else MAX_IMAGE_BYTES)
        with lock:
            progress = load_progress()
            progress.setdefault(peak_id, {}).setdefault("photos", []).append({
                "filename": safe_name,
                "type": "video" if is_video else "image",
            })
            save_progress(progress)
        self._json(200, {"ok": True, "filename": safe_name, "isVideo": is_video})

    def _delete_photo(self, peak_id, filename):
        with lock:
            catalog = load_catalog()
            find_peak(catalog, peak_id)
            safe_name = Path(filename).name  # anti path-traversal : seul le nom de fichier est gardé
            (PHOTOS_DIR / peak_id / safe_name).unlink(missing_ok=True)
            for size in THUMB_SIZES:
                (THUMBS_DIR / peak_id / str(size) / f"{safe_name}.jpg").unlink(missing_ok=True)
            progress = load_progress(catalog)
            entry = progress.setdefault(peak_id, {})
            entry["photos"] = [ph for ph in entry.get("photos", []) if ph["filename"] != safe_name]
            save_progress(progress)
        self._json(200, {"ok": True})

    def _add_gpx(self, peak_id):
        find_peak(load_catalog(), peak_id)
        payload = self._read_body(MAX_GPX_BYTES)
        validate_gpx(payload)
        with lock:
            GPX_DIR.mkdir(parents=True, exist_ok=True)
            tmp = GPX_DIR / f".{peak_id}.gpx.tmp"
            tmp.write_bytes(payload)
            os.replace(tmp, GPX_DIR / f"{peak_id}.gpx")
            progress = load_progress()
            progress.setdefault(peak_id, {})["gpx"] = f"{peak_id}.gpx"
            save_progress(progress)
        self._json(200, {"ok": True})

    def _delete_gpx(self, peak_id):
        with lock:
            catalog = load_catalog()
            find_peak(catalog, peak_id)
            (GPX_DIR / f"{peak_id}.gpx").unlink(missing_ok=True)
            progress = load_progress(catalog)
            progress.setdefault(peak_id, {}).pop("gpx", None)
            save_progress(progress)
        self._json(200, {"ok": True})


def migrate_on_startup():
    """Convertit une fois pour toutes progress.json au format indexé par id, et signale les
    entrées qui ne correspondent plus à aucun sommet (sommet renommé avant l'arrivée des ids,
    ou retiré du catalogue) : elles sont conservées telles quelles, jamais supprimées."""
    if not PROGRESS_PATH.exists():
        return
    catalog = load_catalog()
    with open(PROGRESS_PATH, encoding="utf-8") as f:
        progress = json.load(f)
    progress, changed, orphans = migrate_progress(progress, catalog)
    if changed:
        save_progress(progress)
        print("progress.json migré : données rattachées aux ids des sommets")
    for key in orphans:
        print(f"⚠️  progress.json : entrée « {key} » sans sommet correspondant dans le catalogue "
              f"(renommé ou supprimé ?) — conservée, mais invisible dans l'appli")


def main():
    port = int(os.environ.get("PORT", 8000))
    for d in (DATA_DIR, PHOTOS_DIR, GPX_DIR, THUMBS_DIR):
        d.mkdir(parents=True, exist_ok=True)
    migrate_on_startup()
    if Image is None:
        print("Pillow absent : pas de miniatures, les photos originales sont servies telles quelles")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"project3000summitFR backend listening on :{port} (data={DATA_DIR})")
    server.serve_forever()


if __name__ == "__main__":
    main()
