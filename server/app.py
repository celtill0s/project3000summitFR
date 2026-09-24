#!/usr/bin/env python3
"""Backend (bibliothèque standard uniquement) pour project3000summitFR.

Sert le frontend et fusionne, à la volée, le catalogue public (static/mountains.json, versionné
dans git) avec l'espace personnel de l'utilisateur connecté (data/users/<identifiant>/, JAMAIS
commité) : sommets faits, commentaires, photos/vidéos, traces GPX.

Comptes et sessions : voir auth.py. Chaque requête passe par la table ROUTES, qui déclare pour
chaque route le rôle minimal requis ; ce qui n'y figure pas est refusé. Rôles :
- guest  (invité) : le catalogue seul, rien de ce qu'un utilisateur a ajouté ;
- member (membre) : son propre espace, en lecture et écriture ;
- admin           : son espace, la gestion des comptes, et la lecture de l'espace des autres.

Chaque sommet est identifié par son champ "id" (stable) : les données personnelles y sont
rattachées, pas au nom — renommer un sommet dans le catalogue ne perd donc rien.

Seule dépendance optionnelle : Pillow (+ pillow-heif) pour les miniatures et la conversion
HEIC → JPEG. Sans elle, les photos originales sont servies telles quelles.
"""
import getpass
import hashlib
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import traceback
import unicodedata
import xml.etree.ElementTree as ET
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    from . import auth
except ImportError:  # lancé comme script : python3 server/app.py
    import auth

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
# "private" : données personnelles, aucun cache partagé ne doit les garder.
CACHE_REVALIDATE = "no-cache"
CACHE_IMMUTABLE = "private, max-age=31536000, immutable"
CACHE_THUMB = "private, max-age=86400"

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

# Session : cookie inaccessible au JavaScript (HttpOnly), jamais envoyé en clair (Secure), ni
# joint aux requêtes venant d'un autre site (SameSite=Lax).
SESSION_COOKIE = "session"
SESSION_COOKIE_ATTRS = f"Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age={auth.SessionStore.TTL}"
# Toute écriture doit porter cet en-tête, qu'un autre site ne peut pas ajouter à une requête
# vers le nôtre sans autorisation CORS (jamais accordée) : protection contre les requêtes forgées
# (CSRF), en plus de SameSite.
CSRF_HEADER = "X-Requested-With"
CSRF_VALUE = "SommetsApp"

# Tout est servi depuis la même origine (Leaflet est vendorisé dans static/vendor/) : seules
# les tuiles de carte (OpenStreetMap, IGN Géoplateforme) viennent d'ailleurs. 'unsafe-inline'
# pour les styles uniquement (attributs style="" générés par le frontend), jamais pour les scripts.
CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    "script-src 'self'",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https://tile.openstreetmap.org https://data.geopf.fr",
    "media-src 'self' blob:",
    # Tuiles aussi en connect-src : le service worker (PWA) les récupère via fetch() pour les
    # garder en cache hors-ligne.
    "connect-src 'self' https://tile.openstreetmap.org https://data.geopf.fr",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

mimetypes.add_type("application/gpx+xml", ".gpx")
mimetypes.add_type("application/manifest+json", ".webmanifest")

lock = threading.Lock()
throttle = auth.LoginThrottle()


class ApiError(Exception):
    def __init__(self, status, message, headers=None, extra=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or {}
        self.extra = extra or {}


# ---- stockage ----

def users_store() -> auth.UserStore:
    return auth.UserStore(DATA_DIR / "users.json")


def sessions_store() -> auth.SessionStore:
    return auth.SessionStore(DATA_DIR / "sessions.json")


def user_dir(username: str) -> Path:
    return DATA_DIR / "users" / auth.validate_username(username)


def photos_dir(username):
    return user_dir(username) / "photos"


def gpx_dir(username):
    return user_dir(username) / "gpx"


def thumbs_dir(username):
    return user_dir(username) / "thumbs"


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
    raise ApiError(404, "sommet inconnu")


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


def load_progress(username, catalog=None):
    path = user_dir(username) / "progress.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        progress = json.load(f)
    return migrate_progress(progress, catalog if catalog is not None else load_catalog())[0]


def save_progress(username, data):
    path = user_dir(username) / "progress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # écriture atomique : jamais de JSON tronqué en cas de crash


def merged_peaks(space=None):
    """Catalogue fusionné avec l'espace d'un utilisateur ; space=None (invité) : catalogue seul,
    sans aucun champ personnel."""
    catalog = load_catalog()
    if space is None:
        return catalog
    progress = load_progress(space, catalog)
    out = []
    for p in catalog:
        overlay = progress.get(p["id"], {})
        merged = dict(p)
        merged["done"] = bool(overlay.get("done", False))
        merged["comment"] = overlay.get("comment", "")
        merged["photos"] = [ph["filename"] for ph in overlay.get("photos", [])]
        if overlay.get("gpx"):
            merged["gpx"] = f"/gpx/{space}/{p['id']}.gpx"
        out.append(merged)
    return out


def space_stats(username):
    progress = load_progress(username)
    return {
        "done": sum(1 for v in progress.values() if v.get("done")),
        "photos": sum(len(v.get("photos", [])) for v in progress.values()),
        "gpx": sum(1 for v in progress.values() if v.get("gpx")),
    }


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


def render_page(name: str) -> bytes:
    """Page HTML de static/ avec ses références relatives (style.css, js/main.js, vendor/…)
    réécrites vers le préfixe versionné."""
    html = (STATIC_DIR / name).read_text(encoding="utf-8")
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


# ---- table des routes : (méthode, motif, rôle minimal, méthode du Handler) ----
# PUBLIC = accessible sans connexion. Toute route absente de cette table est refusée (404).
# Les pages HTML (PAGE) redirigent vers /login au lieu de répondre 401.
PUBLIC = None
PAGE = "page"
_SEG = r"[^/]+"
ROUTES = [
    ("GET", r"/healthz", PUBLIC, "r_healthz"),
    ("GET", r"/login", PUBLIC, "r_login_page"),
    ("POST", r"/api/login", PUBLIC, "r_login"),
    ("POST", r"/api/logout", PUBLIC, "r_logout"),
    ("GET", r"/(?:index\.html)?", (PAGE, "guest"), "r_index"),
    ("GET", r"/api/me", "guest", "r_me"),
    ("POST", r"/api/me/password", "guest", "r_change_own_password"),
    ("GET", r"/mountains\.json", "guest", "r_mountains"),
    # Espace personnel : fichiers de <user>, lisibles par lui-même ou un admin (vérifié ensuite).
    ("GET", rf"/photos/(?P<user>{_SEG})/(?P<peak>{_SEG})/(?P<file>{_SEG})", "member", "r_photo"),
    ("GET", rf"/thumbs/(?P<user>{_SEG})/(?P<size>\d+)/(?P<peak>{_SEG})/(?P<file>{_SEG})", "member", "r_thumb"),
    ("GET", rf"/gpx/(?P<user>{_SEG})/(?P<peak>{_SEG})\.gpx", "member", "r_gpx"),
    # Écritures : toujours dans l'espace de l'utilisateur connecté.
    ("POST", rf"/api/peaks/(?P<peak>{_SEG})/done", "member", "r_set_done"),
    ("POST", rf"/api/peaks/(?P<peak>{_SEG})/comment", "member", "r_set_comment"),
    ("POST", rf"/api/peaks/(?P<peak>{_SEG})/photos", "member", "r_add_photo"),
    ("DELETE", rf"/api/peaks/(?P<peak>{_SEG})/photos/(?P<file>{_SEG})", "member", "r_delete_photo"),
    ("POST", rf"/api/peaks/(?P<peak>{_SEG})/gpx", "member", "r_add_gpx"),
    ("DELETE", rf"/api/peaks/(?P<peak>{_SEG})/gpx", "member", "r_delete_gpx"),
    # Administration des comptes.
    ("GET", r"/api/admin/users", "admin", "r_admin_list"),
    ("POST", r"/api/admin/users", "admin", "r_admin_create"),
    ("POST", rf"/api/admin/users/(?P<user>{_SEG})/password", "admin", "r_admin_password"),
    ("POST", rf"/api/admin/users/(?P<user>{_SEG})/role", "admin", "r_admin_role"),
    ("DELETE", rf"/api/admin/users/(?P<user>{_SEG})", "admin", "r_admin_delete"),
    # Fichiers du site (code source public, identique à celui du dépôt GitHub) : en dernier, pour
    # que les motifs ci-dessus aient la priorité ; servis depuis static/ uniquement.
    ("GET", rf"/v/{_SEG}/(?P<rel>.+)", PUBLIC, "r_asset"),
    ("GET", r"/(?P<rel>.+\.(?:css|js|png|jpg|jpeg|svg|ico|webmanifest))", PUBLIC, "r_static"),
]
COMPILED_ROUTES = [(m, re.compile(p), role, h) for m, p, role, h in ROUTES]


def has_role(principal, role) -> bool:
    return principal is not None and auth.ROLE_RANK[principal["role"]] >= auth.ROLE_RANK[role]


class Handler(BaseHTTPRequestHandler):
    server_version = "SummitFR/2.0"
    protocol_version = "HTTP/1.1"

    # ---- utilitaires de réponse ----
    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        # strict-origin-when-cross-origin (et surtout pas same-origin/no-referrer) : les serveurs de
        # tuiles OpenStreetMap EXIGENT un Referer (politique d'usage), sinon « Access blocked ».
        # Seule l'origine est envoyée hors du site, jamais le chemin de la page.
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        for cookie in getattr(self, "_set_cookies", []):
            self.send_header("Set-Cookie", cookie)
        self._set_cookies = []
        super().end_headers()

    def _write(self, data: bytes):
        if self.command != "HEAD":
            self.wfile.write(data)

    def _json(self, status, obj, headers=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self._write(body)

    def _html(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")  # toujours la dernière empreinte
        self.end_headers()
        self._write(body)

    def _redirect(self, location):
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

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
            data = json.loads(self._read_body(MAX_JSON_BYTES) or b"{}")
        except json.JSONDecodeError:
            raise ApiError(400, "JSON invalide")
        if not isinstance(data, dict):
            raise ApiError(400, "JSON invalide")
        return data

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

    # ---- authentification ----
    def _session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(SESSION_COOKIE)
        return morsel.value if morsel else None

    def _principal(self):
        """Utilisateur connecté ({"username", "role"}) ou None. Relu à chaque requête : un rôle
        changé ou un compte supprimé prend effet immédiatement."""
        username = sessions_store().get(self._session_token())
        return users_store().get(username) if username else None

    def _client_ip(self):
        # Derrière Cloudflare + Caddy, l'adresse du client est dans CF-Connecting-IP ; ne sert
        # qu'à limiter les tentatives de connexion (la falsifier n'ouvre aucun accès).
        return (self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0].strip()
                or self.client_address[0])

    def _set_session_cookie(self, token):
        self._set_cookies = getattr(self, "_set_cookies", []) + [f"{SESSION_COOKIE}={token}; {SESSION_COOKIE_ATTRS}"]

    def _clear_session_cookie(self):
        self._set_cookies = getattr(self, "_set_cookies", []) + [f"{SESSION_COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=0"]

    def _space_owner_check(self, owner):
        """Lecture de l'espace de <owner> : soi-même, ou n'importe qui pour un admin."""
        if owner != self.principal["username"] and self.principal["role"] != "admin":
            raise ApiError(403, "accès refusé")
        try:
            auth.validate_username(owner)
        except ValueError:
            raise ApiError(404, "not found")

    # ---- aiguillage ----
    def _dispatch(self):
        try:
            parsed = urlparse(self.path)
            self.query = parse_qs(parsed.query)
            method = "GET" if self.command == "HEAD" else self.command
            for route_method, pattern, role, handler in COMPILED_ROUTES:
                if route_method != method:
                    continue
                m = pattern.fullmatch(parsed.path)
                if not m:
                    continue
                self.principal = self._principal()
                is_page = isinstance(role, tuple)
                min_role = role[1] if is_page else role
                if min_role is not PUBLIC and not has_role(self.principal, min_role):
                    if self.principal is None:
                        if is_page:
                            self._redirect("/login")
                            return
                        raise ApiError(401, "connexion requise")
                    raise ApiError(403, "accès refusé")
                if method in ("POST", "DELETE") and self.headers.get(CSRF_HEADER) != CSRF_VALUE:
                    raise ApiError(403, "requête refusée (en-tête de sécurité manquant)")
                getattr(self, handler)(**{k: unquote(v) for k, v in m.groupdict().items()})
                return
            raise ApiError(404, "not found")
        except ApiError as e:
            self._json(e.status, {"error": e.message, **e.extra}, e.headers)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True  # client parti (ex. vidéo refermée) : rien à répondre
            return
        except Exception:
            self._server_error()
        # Après une erreur, le corps d'un POST a pu rester (partiellement) non lu : la connexion
        # ne doit pas être réutilisée, sinon ces octets seraient pris pour la requête suivante.
        if self.command == "POST":
            self.close_connection = True

    do_GET = do_HEAD = do_POST = do_DELETE = _dispatch

    # ---- routes publiques ----
    def r_healthz(self):
        self._json(200, {"ok": True})

    def r_login_page(self):
        if self.principal:
            self._redirect("/")
        else:
            self._html(render_page("login.html"))

    def r_login(self):
        body = self._read_json()
        username = str(body.get("username", "")).strip().lower()
        password = body.get("password", "")
        keys = [("user", username), ("ip", self._client_ip())]
        wait = throttle.retry_after(keys)
        if wait:
            raise ApiError(429, f"trop de tentatives, réessaie dans {wait // 60 + 1} min",
                           headers={"Retry-After": str(wait)}, extra={"retry_after": wait})
        user = users_store().authenticate(username, password if isinstance(password, str) else "")
        if not user:
            throttle.failure(keys)
            raise ApiError(401, "identifiant ou mot de passe incorrect")
        throttle.success(("user", username))
        self._set_session_cookie(sessions_store().create(user["username"]))
        self._json(200, user)

    def r_logout(self):
        token = self._session_token()
        if token:
            sessions_store().revoke(token)
        self._clear_session_cookie()
        self._json(200, {"ok": True})

    def r_asset(self, rel):
        # /v/<empreinte>/<fichier> : l'empreinte ne sert qu'à changer l'URL, on sert toujours le
        # fichier actuel (une vieille page en cache obtient donc des fichiers à jour).
        if Path(rel).suffix.lower() not in STATIC_ASSET_EXTS:
            raise ApiError(404, "not found")
        self._file(safe_rel_path(STATIC_DIR, rel), cache_control=CACHE_IMMUTABLE)

    def r_static(self, rel):
        # URLs non versionnées (sw.js, favicon, pages en cache d'avant le versionnage) : revalidées.
        self._file(safe_rel_path(STATIC_DIR, rel))

    # ---- routes connectées ----
    def r_index(self):
        self._html(render_page("index.html"))

    def r_me(self):
        self._json(200, self.principal)

    def r_change_own_password(self):
        body = self._read_json()
        username = self.principal["username"]
        if not users_store().authenticate(username, str(body.get("current", ""))):
            raise ApiError(403, "mot de passe actuel incorrect")
        try:
            users_store().set_password(username, body.get("new", ""))
        except ValueError as e:
            raise ApiError(400, str(e))
        # Les autres appareils connectés sont déconnectés ; celui-ci reste connecté.
        sessions_store().revoke_user(username, keep_token=self._session_token())
        self._json(200, {"ok": True})

    def r_mountains(self):
        """Catalogue + espace affiché : le sien (membre/admin), celui d'un autre (admin, via
        ?space=), ou aucun (invité : catalogue seul)."""
        space = self.query.get("space", [None])[0]
        if self.principal["role"] == "guest":
            if space:
                raise ApiError(403, "accès refusé")
            self._json(200, merged_peaks(None))
            return
        space = space or self.principal["username"]
        self._space_owner_check(space)
        if space != self.principal["username"] and not users_store().get(space):
            raise ApiError(404, "utilisateur inconnu")
        self._json(200, merged_peaks(space))

    def r_photo(self, user, peak, file):
        self._space_owner_check(user)
        self._file(safe_rel_path(photos_dir(user), f"{peak}/{file}"), cache_control=CACHE_IMMUTABLE)

    def r_thumb(self, user, size, peak, file):
        """Version JPEG redimensionnée d'une photo, générée à la première demande puis mise en
        cache. Sans Pillow (ou si l'image est illisible), l'original est servi à la place."""
        self._space_owner_check(user)
        if int(size) not in THUMB_SIZES:
            raise ApiError(404, "not found")
        src = safe_rel_path(photos_dir(user), f"{peak}/{file}")
        if not src.is_file():
            raise ApiError(404, "not found")
        if Image is None or src.suffix.lower() not in IMAGE_EXTS:
            self._file(src, cache_control=CACHE_THUMB)
            return
        dest = safe_rel_path(thumbs_dir(user), f"{peak}/{size}/{file}.jpg")
        if not dest.is_file():
            try:
                make_thumbnail(src, dest, int(size))
            except Exception:
                traceback.print_exc()
                self._file(src, cache_control=CACHE_THUMB)
                return
        self._file(dest, "image/jpeg", cache_control=CACHE_THUMB)

    def r_gpx(self, user, peak):
        self._space_owner_check(user)
        self._file(safe_rel_path(gpx_dir(user), f"{peak}.gpx"))

    # ---- écritures (espace de l'utilisateur connecté uniquement) ----
    def _set_field(self, peak_id, field, value):
        me = self.principal["username"]
        with lock:
            catalog = load_catalog()
            find_peak(catalog, peak_id)
            progress = load_progress(me, catalog)
            progress.setdefault(peak_id, {})[field] = value
            save_progress(me, progress)
        self._json(200, {"ok": True})

    def r_set_done(self, peak):
        self._set_field(peak, "done", bool(self._read_json().get("done")))

    def r_set_comment(self, peak):
        self._set_field(peak, "comment", str(self._read_json().get("comment", ""))[:20000])

    def r_add_photo(self, peak):
        me = self.principal["username"]
        find_peak(load_catalog(), peak)
        filename = self.query.get("filename", [""])[0]
        ext = Path(filename).suffix.lower()
        is_video = ext in VIDEO_EXTS
        if not (is_video or ext in IMAGE_EXTS):
            self.close_connection = True
            raise ApiError(400, f"extension non supportée : {ext or '(aucune)'}")
        safe_name = f"{secrets.token_hex(4)}{ext}"
        # L'écriture (potentiellement longue) se fait hors du verrou ; seule la mise à jour de
        # progress.json, instantanée, est sérialisée.
        self._stream_body_to(photos_dir(me) / peak / safe_name, MAX_VIDEO_BYTES if is_video else MAX_IMAGE_BYTES)
        with lock:
            progress = load_progress(me)
            progress.setdefault(peak, {}).setdefault("photos", []).append({
                "filename": safe_name,
                "type": "video" if is_video else "image",
            })
            save_progress(me, progress)
        self._json(200, {"ok": True, "filename": safe_name, "isVideo": is_video})

    def r_delete_photo(self, peak, file):
        me = self.principal["username"]
        with lock:
            catalog = load_catalog()
            find_peak(catalog, peak)
            safe_name = Path(file).name  # anti path-traversal : seul le nom de fichier est gardé
            (photos_dir(me) / peak / safe_name).unlink(missing_ok=True)
            for size in THUMB_SIZES:
                (thumbs_dir(me) / peak / str(size) / f"{safe_name}.jpg").unlink(missing_ok=True)
            progress = load_progress(me, catalog)
            entry = progress.setdefault(peak, {})
            entry["photos"] = [ph for ph in entry.get("photos", []) if ph["filename"] != safe_name]
            save_progress(me, progress)
        self._json(200, {"ok": True})

    def r_add_gpx(self, peak):
        me = self.principal["username"]
        find_peak(load_catalog(), peak)
        payload = self._read_body(MAX_GPX_BYTES)
        validate_gpx(payload)
        with lock:
            gpx_dir(me).mkdir(parents=True, exist_ok=True)
            tmp = gpx_dir(me) / f".{peak}.gpx.tmp"
            tmp.write_bytes(payload)
            os.replace(tmp, gpx_dir(me) / f"{peak}.gpx")
            progress = load_progress(me)
            progress.setdefault(peak, {})["gpx"] = f"{peak}.gpx"
            save_progress(me, progress)
        self._json(200, {"ok": True})

    def r_delete_gpx(self, peak):
        me = self.principal["username"]
        with lock:
            catalog = load_catalog()
            find_peak(catalog, peak)
            (gpx_dir(me) / f"{peak}.gpx").unlink(missing_ok=True)
            progress = load_progress(me, catalog)
            progress.setdefault(peak, {}).pop("gpx", None)
            save_progress(me, progress)
        self._json(200, {"ok": True})

    # ---- administration des comptes ----
    def _existing_user(self, user):
        if not users_store().get(user):
            raise ApiError(404, "utilisateur inconnu")
        return user

    def r_admin_list(self):
        users = [{"username": u, **d, **(space_stats(u) if d["role"] != "guest" else {})}
                 for u, d in sorted(users_store().all().items())]
        self._json(200, {"users": users})

    def r_admin_create(self):
        body = self._read_json()
        try:
            users_store().create(str(body.get("username", "")).strip().lower(), body.get("password", ""),
                                 body.get("role", "member"))
        except ValueError as e:
            raise ApiError(400, str(e))
        self._json(200, {"ok": True})

    def r_admin_password(self, user):
        self._existing_user(user)
        try:
            users_store().set_password(user, self._read_json().get("password", ""))
        except ValueError as e:
            raise ApiError(400, str(e))
        sessions_store().revoke_user(user, keep_token=self._session_token() if user == self.principal["username"] else None)
        self._json(200, {"ok": True})

    def r_admin_role(self, user):
        self._existing_user(user)
        try:
            users_store().set_role(user, self._read_json().get("role", ""))
        except ValueError as e:
            raise ApiError(400, str(e))
        self._json(200, {"ok": True})

    def r_admin_delete(self, user):
        self._existing_user(user)
        if user == self.principal["username"]:
            raise ApiError(400, "impossible de supprimer son propre compte depuis le site")
        try:
            users_store().delete(user)
        except ValueError as e:
            raise ApiError(400, str(e))
        sessions_store().revoke_user(user)
        shutil.rmtree(user_dir(user), ignore_errors=True)  # son espace : photos, GPX, progression
        self._json(200, {"ok": True})


# ---- migration des données d'avant les comptes (un seul espace, à la racine de data/) ----

LEGACY_ITEMS = ("progress.json", "photos", "gpx", "thumbs")


def _non_empty(path: Path) -> bool:
    return path.is_file() or (path.is_dir() and any(path.iterdir()))


def legacy_data_present() -> bool:
    return any(_non_empty(DATA_DIR / name) for name in LEGACY_ITEMS)


def migrate_legacy_to(username: str) -> list:
    """Déplace data/progress.json, photos/, gpx/, thumbs/ dans data/users/<username>/.
    Renvoie la liste des éléments déplacés ; ne remplace jamais un élément existant."""
    dest = user_dir(username)
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in LEGACY_ITEMS:
        src = DATA_DIR / name
        if not _non_empty(src):
            continue
        if _non_empty(dest / name):
            raise RuntimeError(f"{dest / name} existe déjà : migration interrompue, rien n'est écrasé")
        if (dest / name).is_dir():
            (dest / name).rmdir()
        os.replace(src, dest / name)
        moved.append(name)
    if (dest / "progress.json").exists():
        # progress.json d'avant les ids (indexé par nom de sommet) : converti au passage.
        save_progress(username, load_progress(username))
    return moved


def _prompt_password(label="Mot de passe") -> str:
    while True:
        pw = getpass.getpass(f"{label} ({auth.MIN_PASSWORD_LENGTH} caractères minimum) : ")
        try:
            auth.validate_password(pw)
        except ValueError as e:
            print(f"  {e}")
            continue
        if getpass.getpass("Confirmation : ") == pw:
            return pw
        print("  les deux saisies diffèrent, recommence")


def cli(argv) -> int:
    """Commandes d'administration, à lancer sur le serveur :
      python3 server/app.py create-admin <identifiant>   crée un compte admin (et y rattache les
                                                         données d'avant les comptes, s'il y en a)
      python3 server/app.py set-password <identifiant>   réinitialise un mot de passe (secours)
      python3 server/app.py list-users
    (avec Docker : docker compose exec app python3 server/app.py …)"""
    if not argv or argv[0] not in ("create-admin", "set-password", "list-users"):
        print(cli.__doc__)
        return 2
    store = users_store()
    try:
        if argv[0] == "list-users":
            for u, d in sorted(store.all().items()):
                print(f"{u:32s} {d['role']}")
            return 0
        if len(argv) != 2:
            print(cli.__doc__)
            return 2
        username = auth.validate_username(argv[1].strip().lower())
        if argv[0] == "create-admin":
            store.create(username, _prompt_password(), "admin")
            print(f"✓ compte administrateur « {username} » créé")
            if legacy_data_present():
                moved = migrate_legacy_to(username)
                print(f"✓ données existantes rattachées à « {username} » : {', '.join(moved)}")
        else:
            if not store.get(username):
                print(f"utilisateur « {username} » inconnu")
                return 1
            store.set_password(username, _prompt_password("Nouveau mot de passe"))
            sessions_store().revoke_user(username)
            print(f"✓ mot de passe de « {username} » changé (ses sessions ouvertes sont fermées)")
        return 0
    except (ValueError, RuntimeError) as e:
        print(f"erreur : {e}")
        return 1


def main():
    if len(sys.argv) > 1:
        sys.exit(cli(sys.argv[1:]))
    port = int(os.environ.get("PORT", 8000))
    (DATA_DIR / "users").mkdir(parents=True, exist_ok=True)
    if Image is None:
        print("Pillow absent : pas de miniatures, les photos originales sont servies telles quelles")
    if users_store().count() == 0:
        print("⚠️  Aucun compte : personne ne peut se connecter. Crée le premier administrateur :\n"
              "     docker compose exec app python3 server/app.py create-admin <identifiant>\n"
              "   (sans Docker : python3 server/app.py create-admin <identifiant>)")
        if legacy_data_present():
            print("   Les données existantes (progress.json, photos, gpx) lui seront rattachées.")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"project3000summitFR backend listening on :{port} (data={DATA_DIR})")
    server.serve_forever()


if __name__ == "__main__":
    main()
