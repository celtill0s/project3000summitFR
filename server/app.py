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

Organisation :
- app.py     : serveur HTTP (table des routes, Handler) et démarrage ;
- auth.py    : comptes, mots de passe, sessions ;
- storage.py : catalogue et espaces personnels sur disque ;
- files.py   : pages versionnées, GPX, miniatures, plages d'octets, chemins sûrs ;
- cli.py     : commandes d'administration (create-admin, set-password, list-users).
"""
import json
import mimetypes
import os
import re
import secrets
import shutil
import sys
import threading
import traceback
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

if __name__ == "__main__" and not __package__:
    # Lancé comme script (python3 server/app.py) : on repasse par le paquet « server » pour que
    # les imports relatifs ci-dessous fonctionnent.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from server.app import main
    sys.exit(main())

from . import auth, cli, files, storage
from .errors import ApiError
from .files import (IMAGE_EXTS, STATIC_ASSET_EXTS, THUMB_SIZES, VIDEO_EXTS, make_thumbnail, parse_range,
                    render_page, safe_rel_path, validate_gpx)
from .storage import (CUSTOM_ID_PREFIX, find_peak, gpx_dir, load_catalog, load_custom_peaks, load_progress,
                      merged_peaks, photos_dir, save_custom_peaks, save_progress, sessions_store, slugify,
                      space_catalog, space_stats, thumbs_dir, user_dir, users_store, validate_custom_peak)

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_GPX_BYTES = 20 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
CHUNK_BYTES = 1024 * 1024
# Politiques de cache. Code du site et traces GPX : revalidés à chaque chargement (ETag -> 304
# si inchangé, donc quasi gratuit) — sans ça, un navigateur peut garder l'ancien JS après une
# mise à jour alors que la page (et sa CSP) sont déjà nouvelles. Photos : nom aléatoire jamais
# réutilisé, donc cache long. Miniatures : un jour (leur contenu change si Pillow est ajouté).
# "private" : données personnelles, aucun cache partagé ne doit les garder.
CACHE_REVALIDATE = "no-cache"
CACHE_IMMUTABLE = "private, max-age=31536000, immutable"
CACHE_THUMB = "private, max-age=86400"

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
    ("POST", r"/api/peaks", "member", "r_add_custom_peak"),
    ("POST", rf"/api/peaks/(?P<peak>{_SEG})", "member", "r_update_custom_peak"),
    ("DELETE", rf"/api/peaks/(?P<peak>{_SEG})", "member", "r_delete_custom_peak"),
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
        self._file(safe_rel_path(storage.STATIC_DIR, rel), cache_control=CACHE_IMMUTABLE)

    def r_static(self, rel):
        # URLs non versionnées (sw.js, favicon, pages en cache d'avant le versionnage) : revalidées.
        self._file(safe_rel_path(storage.STATIC_DIR, rel))

    # ---- routes connectées ----
    def r_index(self):
        self._html(render_page("index.html"))

    def r_me(self):
        me = dict(self.principal)
        if me["role"] != "guest":
            me["storage"] = storage.storage_info(me["username"])
        self._json(200, me)

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
        if files.Image is None or src.suffix.lower() not in IMAGE_EXTS:
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
    def _ok_with_storage(self, **extra):
        """Réponse d'une écriture qui change l'espace occupé : le site met à jour son bandeau."""
        self._json(200, {"ok": True, **extra, "storage": storage.storage_info(self.principal["username"])})

    def _check_quota(self, incoming_bytes):
        info = storage.storage_info(self.principal["username"])
        if info["used"] + incoming_bytes > info["limit"]:
            raise ApiError(507, f"espace de stockage plein ({info['limit'] // 1024 ** 3} Go maximum par utilisateur) : "
                                "supprime des photos, vidéos ou traces GPX pour en ajouter", extra={"storage": info})

    def _update_progress(self, peak_id, change):
        """Applique change(entrée du sommet) à progress.json, sous verrou (sommet vérifié d'abord)."""
        me = self.principal["username"]
        with lock:
            catalog = space_catalog(me)
            find_peak(catalog, peak_id)
            progress = load_progress(me, catalog)
            change(progress.setdefault(peak_id, {}))
            save_progress(me, progress)

    def r_set_done(self, peak):
        done = bool(self._read_json().get("done"))
        self._update_progress(peak, lambda entry: entry.update(done=done))
        self._json(200, {"ok": True})

    def r_set_comment(self, peak):
        comment = str(self._read_json().get("comment", ""))[:20000]
        self._update_progress(peak, lambda entry: entry.update(comment=comment))
        self._json(200, {"ok": True})

    def r_add_custom_peak(self):
        me = self.principal["username"]
        peak = validate_custom_peak(self._read_json())
        with lock:
            self._check_unique_name(me, peak["name"])
            peak = {
                "id": f"{CUSTOM_ID_PREFIX}{slugify(peak['name'])}-{secrets.token_hex(3)}",
                **peak,
                "source": "Ajout manuel",
                "custom": True,
            }
            save_custom_peaks(me, load_custom_peaks(me) + [peak])
        self._json(200, {**peak, "done": False, "comment": "", "photos": []})

    @staticmethod
    def _check_unique_name(me, name, except_id=None):
        if any(p["name"].casefold() == name.casefold() and p["id"] != except_id for p in space_catalog(me)):
            raise ApiError(409, "un sommet porte déjà ce nom")

    def r_update_custom_peak(self, peak):
        """Modifie un sommet ajouté à la main ; son id (et donc ses photos, GPX…) ne change pas."""
        me = self.principal["username"]
        fields = validate_custom_peak(self._read_json())
        with lock:
            custom = load_custom_peaks(me)
            target = next((p for p in custom if p["id"] == peak), None)
            if target is None:
                raise ApiError(404, "sommet inconnu (seuls les sommets ajoutés à la main sont modifiables)")
            self._check_unique_name(me, fields["name"], except_id=peak)
            target.update(fields)
            save_custom_peaks(me, custom)
        self._json(200, target)

    def r_delete_custom_peak(self, peak):
        """Supprime un sommet ajouté à la main, avec ses données (photos, GPX, commentaire)."""
        me = self.principal["username"]
        with lock:
            custom = load_custom_peaks(me)
            if not any(p["id"] == peak for p in custom):
                raise ApiError(404, "sommet inconnu (seuls les sommets ajoutés à la main sont supprimables)")
            save_custom_peaks(me, [p for p in custom if p["id"] != peak])
            progress = load_progress(me, load_catalog())
            if progress.pop(peak, None) is not None:
                save_progress(me, progress)
            shutil.rmtree(safe_rel_path(photos_dir(me), peak), ignore_errors=True)
            shutil.rmtree(safe_rel_path(thumbs_dir(me), peak), ignore_errors=True)
            safe_rel_path(gpx_dir(me), f"{peak}.gpx").unlink(missing_ok=True)
        self._ok_with_storage()

    def r_add_photo(self, peak):
        me = self.principal["username"]
        find_peak(space_catalog(me), peak)
        filename = self.query.get("filename", [""])[0]
        ext = Path(filename).suffix.lower()
        is_video = ext in VIDEO_EXTS
        if not (is_video or ext in IMAGE_EXTS):
            self.close_connection = True
            raise ApiError(400, f"extension non supportée : {ext or '(aucune)'}")
        max_bytes = MAX_VIDEO_BYTES if is_video else MAX_IMAGE_BYTES
        self._check_quota(self._content_length(max_bytes))
        safe_name = f"{secrets.token_hex(4)}{ext}"
        # L'écriture (potentiellement longue) se fait hors du verrou ; seule la mise à jour de
        # progress.json, instantanée, est sérialisée.
        self._stream_body_to(photos_dir(me) / peak / safe_name, max_bytes)
        media = {"filename": safe_name, "type": "video" if is_video else "image"}
        self._update_progress(peak, lambda entry: entry.setdefault("photos", []).append(media))
        self._ok_with_storage(filename=safe_name, isVideo=is_video)

    def r_delete_photo(self, peak, file):
        me = self.principal["username"]
        safe_name = Path(file).name  # anti path-traversal : seul le nom de fichier est gardé

        def forget(entry):
            (photos_dir(me) / peak / safe_name).unlink(missing_ok=True)
            for size in THUMB_SIZES:
                (thumbs_dir(me) / peak / str(size) / f"{safe_name}.jpg").unlink(missing_ok=True)
            entry["photos"] = [ph for ph in entry.get("photos", []) if ph["filename"] != safe_name]
        self._update_progress(peak, forget)
        self._ok_with_storage()

    def r_add_gpx(self, peak):
        me = self.principal["username"]
        find_peak(space_catalog(me), peak)
        self._check_quota(self._content_length(MAX_GPX_BYTES))
        payload = self._read_body(MAX_GPX_BYTES)
        validate_gpx(payload)

        def store(entry):
            gpx_dir(me).mkdir(parents=True, exist_ok=True)
            tmp = gpx_dir(me) / f".{peak}.gpx.tmp"
            tmp.write_bytes(payload)
            os.replace(tmp, gpx_dir(me) / f"{peak}.gpx")
            entry["gpx"] = f"{peak}.gpx"
        self._update_progress(peak, store)
        self._ok_with_storage()

    def r_delete_gpx(self, peak):
        me = self.principal["username"]

        def forget(entry):
            (gpx_dir(me) / f"{peak}.gpx").unlink(missing_ok=True)
            entry.pop("gpx", None)
        self._update_progress(peak, forget)
        self._ok_with_storage()

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


def main():
    if len(sys.argv) > 1:
        sys.exit(cli.cli(sys.argv[1:]))
    port = int(os.environ.get("PORT", 8000))
    (storage.DATA_DIR / "users").mkdir(parents=True, exist_ok=True)
    if files.Image is None:
        print("Pillow absent : pas de miniatures, les photos originales sont servies telles quelles")
    if users_store().count() == 0:
        print("⚠️  Aucun compte : personne ne peut se connecter. Crée le premier administrateur :\n"
              "     docker compose exec app python3 server/app.py create-admin <identifiant>\n"
              "   (sans Docker : python3 server/app.py create-admin <identifiant>)")
        if cli.legacy_data_present():
            print("   Les données existantes (progress.json, photos, gpx) lui seront rattachées.")
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"project3000summitFR backend listening on :{port} (data={storage.DATA_DIR})")
    server.serve_forever()


if __name__ == "__main__":
    main()
