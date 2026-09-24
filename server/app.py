#!/usr/bin/env python3
"""Backend minimal (bibliothèque standard uniquement) pour project3000summitFR.

Sert le frontend statique et fusionne, à la volée, le catalogue public
(static/mountains.json, versionné dans git) avec l'overlay privé
(data/progress.json, JAMAIS commité) qui contient l'état personnel :
coché, commentaire, photos/vidéos, trace GPX.

Toute écriture (coché/commentaire/upload) passe par ce serveur et va
directement sur le disque local (data/) — pas de localStorage, pas
d'IndexedDB, pas de dépendance au navigateur.
"""
import json
import mimetypes
import os
import re
import secrets
import threading
import traceback
import unicodedata
from email import message_from_bytes
from email.policy import default as email_default_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(os.environ.get("STATIC_DIR", ROOT / "static"))
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))
CATALOG_PATH = STATIC_DIR / "mountains.json"
PROGRESS_PATH = DATA_DIR / "progress.json"
PHOTOS_DIR = DATA_DIR / "photos"
GPX_DIR = DATA_DIR / "gpx"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".ogv", ".avi", ".mkv"}
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_GPX_BYTES = 20 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
# Extensions autorisées pour le service de fichiers statiques génériques (style.css, app.js…) —
# whitelist explicite plutôt que "tout ce qui n'est pas une route API", pour ne jamais exposer
# par erreur un fichier qui traînerait dans static/ (ex. un .py ou un .bak).
STATIC_ASSET_EXTS = {".css", ".js", ".png", ".jpg", ".jpeg", ".svg", ".ico"}

mimetypes.add_type("application/gpx+xml", ".gpx")

lock = threading.Lock()


def slugify(name: str) -> str:
    n = unicodedata.normalize("NFD", name.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
    return n or "sommet"


def load_catalog():
    with open(CATALOG_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_progress():
    if not PROGRESS_PATH.exists():
        return {}
    with open(PROGRESS_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_progress(data):
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROGRESS_PATH.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_PATH)  # écriture atomique : jamais de JSON tronqué en cas de crash


def merged_peaks():
    catalog = load_catalog()
    progress = load_progress()
    out = []
    for p in catalog:
        overlay = progress.get(p["name"], {})
        merged = dict(p)
        merged["done"] = bool(overlay.get("done", False))
        merged["comment"] = overlay.get("comment", "")
        merged["photos"] = [ph["filename"] for ph in overlay.get("photos", [])]
        if overlay.get("gpx"):
            merged["gpx"] = f"/gpx/{slugify(p['name'])}.gpx"
        out.append(merged)
    return out


def parse_multipart(content_type: str, body: bytes):
    """Réutilise le vrai parseur MIME de la stdlib (module email) pour lire un
    multipart/form-data : cgi.FieldStorage n'existe plus depuis Python 3.13."""
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode()
    msg = message_from_bytes(header + body, policy=email_default_policy)
    parts = {}
    if msg.is_multipart():
        for part in msg.iter_parts():
            name = part.get_param("name", header="Content-Disposition")
            if name:
                parts[name] = part
    return parts


class Handler(BaseHTTPRequestHandler):
    server_version = "SummitFR/1.0"
    protocol_version = "HTTP/1.1"

    # ---- utilitaires de réponse ----
    def _json(self, status, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _server_error(self):
        # Le détail de l'exception reste dans les logs serveur, jamais renvoyé au client.
        traceback.print_exc()
        self._json(500, {"error": "erreur interne"})

    def _file(self, path: Path, content_type=None, cache=True):
        try:
            resolved = path.resolve()
        except OSError:
            self._json(404, {"error": "not found"})
            return
        if not resolved.is_file():
            self._json(404, {"error": "not found"})
            return
        data = resolved.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(str(resolved))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "public, max-age=60" if cache else "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self, max_bytes):
        length = int(self.headers.get("Content-Length", 0))
        if length <= 0:
            return b""
        if length > max_bytes:
            raise ValueError("payload trop volumineux")
        return self.rfile.read(length)

    def _peak_name_from_path(self, prefix, path):
        rest = path[len(prefix):]
        parts = rest.split("/", 1)
        name = unquote(parts[0])
        tail = parts[1] if len(parts) > 1 else ""
        return name, tail

    def _require_known_peak(self, catalog, name):
        if not any(p["name"] == name for p in catalog):
            raise KeyError(name)

    # ---- anti path-traversal : ne jamais faire confiance à un chemin fourni par le client ----
    def _safe_rel_path(self, base: Path, rel: str) -> Path:
        candidate = (base / rel).resolve()
        base_resolved = base.resolve()
        if base_resolved not in candidate.parents and candidate != base_resolved:
            raise ValueError("chemin invalide")
        return candidate

    # ---- routes GET ----
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/healthz":
                self._json(200, {"ok": True})
            elif path in ("/", "/index.html"):
                self._file(STATIC_DIR / "index.html", "text/html; charset=utf-8", cache=False)
            elif path == "/mountains.json":
                self._json(200, merged_peaks())
            elif path.startswith("/photos/"):
                rel = unquote(path[len("/photos/"):])
                self._file(self._safe_rel_path(PHOTOS_DIR, rel))
            elif path.startswith("/gpx/"):
                rel = unquote(path[len("/gpx/"):])
                self._file(self._safe_rel_path(GPX_DIR, rel), cache=False)
            elif Path(unquote(path)).suffix.lower() in STATIC_ASSET_EXTS:
                rel = unquote(path).lstrip("/")
                self._file(self._safe_rel_path(STATIC_DIR, rel))
            else:
                self._json(404, {"error": "not found"})
        except ValueError:
            self._json(400, {"error": "chemin invalide"})
        except Exception:  # pragma: no cover - filet de sécurité
            self._server_error()

    def do_DELETE(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/peaks/"):
                name, tail = self._peak_name_from_path("/api/peaks/", path)
                if tail.startswith("photos/"):
                    filename = unquote(tail[len("photos/"):])
                    self._delete_photo(name, filename)
                elif tail == "gpx":
                    self._delete_gpx(name)
                else:
                    self._json(404, {"error": "route inconnue"})
            else:
                self._json(404, {"error": "not found"})
        except KeyError:
            self._json(404, {"error": "sommet inconnu"})
        except Exception:
            self._server_error()

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/peaks/"):
                name, tail = self._peak_name_from_path("/api/peaks/", path)
                if tail == "done":
                    body = json.loads(self._read_body(MAX_JSON_BYTES) or b"{}")
                    self._set_done(name, bool(body.get("done")))
                elif tail == "comment":
                    body = json.loads(self._read_body(MAX_JSON_BYTES) or b"{}")
                    self._set_comment(name, str(body.get("comment", ""))[:20000])
                elif tail == "photos":
                    self._add_photo(name)
                elif tail == "gpx":
                    self._add_gpx(name)
                else:
                    self._json(404, {"error": "route inconnue"})
            else:
                self._json(404, {"error": "not found"})
        except KeyError:
            self._json(404, {"error": "sommet inconnu"})
        # JSONDecodeError hérite de ValueError : doit être intercepté AVANT, sinon un JSON
        # invalide serait signalé comme "payload trop volumineux" (413).
        except json.JSONDecodeError:
            self._json(400, {"error": "JSON invalide"})
        except ValueError as e:
            self._json(413, {"error": str(e)})
        except Exception:
            self._server_error()

    # ---- actions ----
    def _set_done(self, name, done):
        with lock:
            catalog = load_catalog()
            self._require_known_peak(catalog, name)
            progress = load_progress()
            progress.setdefault(name, {})["done"] = done
            save_progress(progress)
        self._json(200, {"ok": True})

    def _set_comment(self, name, comment):
        with lock:
            catalog = load_catalog()
            self._require_known_peak(catalog, name)
            progress = load_progress()
            progress.setdefault(name, {})["comment"] = comment
            save_progress(progress)
        self._json(200, {"ok": True})

    def _add_photo(self, name):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json(400, {"error": "attendu multipart/form-data"})
            return
        body = self._read_body(MAX_VIDEO_BYTES)
        parts = parse_multipart(content_type, body)
        part = parts.get("file")
        if part is None:
            self._json(400, {"error": "champ 'file' manquant"})
            return
        filename = part.get_filename() or "fichier"
        payload = part.get_payload(decode=True) or b""
        ext = Path(filename).suffix.lower()
        is_video = ext in VIDEO_EXTS
        is_image = ext in IMAGE_EXTS
        if not (is_video or is_image):
            self._json(400, {"error": f"extension non supportée : {ext or '(aucune)'}"})
            return
        limit = MAX_VIDEO_BYTES if is_video else MAX_IMAGE_BYTES
        if len(payload) > limit:
            self._json(413, {"error": "fichier trop volumineux"})
            return
        with lock:
            catalog = load_catalog()
            self._require_known_peak(catalog, name)
            slug = slugify(name)
            peak_dir = PHOTOS_DIR / slug
            peak_dir.mkdir(parents=True, exist_ok=True)
            safe_name = f"{secrets.token_hex(4)}{ext}"
            (peak_dir / safe_name).write_bytes(payload)
            progress = load_progress()
            entry = progress.setdefault(name, {})
            entry.setdefault("photos", []).append({
                "filename": safe_name,
                "type": "video" if is_video else "image",
            })
            save_progress(progress)
        self._json(200, {"ok": True, "filename": safe_name, "isVideo": is_video})

    def _delete_photo(self, name, filename):
        with lock:
            catalog = load_catalog()
            self._require_known_peak(catalog, name)
            slug = slugify(name)
            safe_name = Path(filename).name  # anti path-traversal : seul le nom de fichier est gardé
            target = PHOTOS_DIR / slug / safe_name
            if target.is_file():
                target.unlink()
            progress = load_progress()
            entry = progress.setdefault(name, {})
            entry["photos"] = [ph for ph in entry.get("photos", []) if ph["filename"] != safe_name]
            save_progress(progress)
        self._json(200, {"ok": True})

    def _add_gpx(self, name):
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            self._json(400, {"error": "attendu multipart/form-data"})
            return
        body = self._read_body(MAX_GPX_BYTES)
        parts = parse_multipart(content_type, body)
        part = parts.get("file")
        if part is None:
            self._json(400, {"error": "champ 'file' manquant"})
            return
        payload = part.get_payload(decode=True) or b""
        with lock:
            catalog = load_catalog()
            self._require_known_peak(catalog, name)
            slug = slugify(name)
            GPX_DIR.mkdir(parents=True, exist_ok=True)
            (GPX_DIR / f"{slug}.gpx").write_bytes(payload)
            progress = load_progress()
            progress.setdefault(name, {})["gpx"] = f"{slug}.gpx"
            save_progress(progress)
        self._json(200, {"ok": True})

    def _delete_gpx(self, name):
        with lock:
            catalog = load_catalog()
            self._require_known_peak(catalog, name)
            slug = slugify(name)
            target = GPX_DIR / f"{slug}.gpx"
            if target.is_file():
                target.unlink()
            progress = load_progress()
            entry = progress.setdefault(name, {})
            entry.pop("gpx", None)
            save_progress(progress)
        self._json(200, {"ok": True})


def main():
    port = int(os.environ.get("PORT", 8000))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "photos").mkdir(exist_ok=True)
    (DATA_DIR / "gpx").mkdir(exist_ok=True)
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"project3000summitFR backend listening on :{port} (data={DATA_DIR})")
    server.serve_forever()


if __name__ == "__main__":
    main()
