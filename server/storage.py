"""Données sur disque : catalogue public et espace personnel de chaque utilisateur.

- static/mountains.json          : catalogue public (versionné dans git) ;
- data/users.json, sessions.json : comptes et sessions (voir auth.py) ;
- data/users/<identifiant>/      : son espace, JAMAIS commité —
    progress.json      sommets faits, commentaires, liste des photos, présence d'un GPX ;
    custom_peaks.json  sommets qu'il a ajoutés à la main (visibles de lui seul) ;
    photos/, thumbs/, gpx/.

Chaque sommet est identifié par son champ "id" (stable) : les données personnelles y sont
rattachées, pas au nom — renommer un sommet dans le catalogue ne perd donc rien.

STATIC_DIR et DATA_DIR sont lus à chaque appel (jamais copiés ailleurs) : les tests les
redirigent vers un dossier temporaire.
"""
import json
import os
import re
import unicodedata
from pathlib import Path

from . import auth
from .errors import ApiError

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = Path(os.environ.get("STATIC_DIR", ROOT / "static"))
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))

CUSTOM_ID_PREFIX = "perso-"
DIFFICULTIES = {"T2", "T3", "T4"}
REGIONS = {"Alpes", "Pyrénées"}
MAX_CUSTOM_LINKS = 10
# Espace disque maximal par utilisateur (photos, vidéos, GPX, fichiers JSON ; les miniatures,
# générées par le serveur et régénérables, ne comptent pas).
QUOTA_BYTES = 5 * 1024 ** 3


# ---- emplacements ----

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


def _read_json(path: Path, default):
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)  # écriture atomique : jamais de JSON tronqué en cas de crash


# ---- catalogue ----

def slugify(name: str) -> str:
    n = unicodedata.normalize("NFD", name.lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    n = re.sub(r"[^a-z0-9]+", "-", n).strip("-")
    return n or "sommet"


def load_catalog():
    return _read_json(STATIC_DIR / "mountains.json", [])


def space_catalog(username):
    """Catalogue public + sommets ajoutés à la main par cet utilisateur."""
    return load_catalog() + load_custom_peaks(username)


def find_peak(catalog, peak_id):
    for p in catalog:
        if p["id"] == peak_id:
            return p
    raise ApiError(404, "sommet inconnu")


# ---- progression (progress.json) ----

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
    progress = _read_json(user_dir(username) / "progress.json", {})
    return migrate_progress(progress, catalog if catalog is not None else load_catalog())[0]


def save_progress(username, data):
    _write_json(user_dir(username) / "progress.json", data)


def merged_peaks(space=None):
    """Catalogue fusionné avec l'espace d'un utilisateur ; space=None (invité) : catalogue seul,
    sans aucun champ personnel."""
    if space is None:
        return load_catalog()
    catalog = space_catalog(space)
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
        "bytes": space_usage(username),
    }


def space_usage(username) -> int:
    """Octets occupés par l'espace d'un utilisateur, miniatures exclues."""
    root = user_dir(username)
    if not root.is_dir():
        return 0
    thumbs = thumbs_dir(username)
    return sum(f.stat().st_size for f in root.rglob("*") if f.is_file() and thumbs not in f.parents)


def storage_info(username):
    return {"used": space_usage(username), "limit": QUOTA_BYTES}


# ---- sommets ajoutés à la main (custom_peaks.json) ----

def load_custom_peaks(username):
    return _read_json(user_dir(username) / "custom_peaks.json", [])


def save_custom_peaks(username, peaks):
    _write_json(user_dir(username) / "custom_peaks.json", peaks)


def _text_field(body, key, max_len, required=False):
    value = body.get(key, "")
    if not isinstance(value, str):
        raise ApiError(400, f"champ « {key} » invalide")
    value = value.strip()
    if required and not value:
        raise ApiError(400, f"champ « {key} » requis")
    if len(value) > max_len:
        raise ApiError(400, f"champ « {key} » trop long ({max_len} caractères max)")
    return value


def _number_field(body, key, low, high):
    value = body.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ApiError(400, f"champ « {key} » invalide")
    return value


def validate_custom_peak(body):
    """Champs d'un sommet ajouté à la main, validés un par un (rien d'autre n'est conservé)."""
    difficulty = body.get("difficulty")
    if difficulty not in DIFFICULTIES:
        raise ApiError(400, "difficulté invalide (T2, T3 ou T4)")
    region = body.get("region")
    if region not in REGIONS:
        raise ApiError(400, "région invalide")
    links = body.get("links", [])
    if not isinstance(links, list) or len(links) > MAX_CUSTOM_LINKS:
        raise ApiError(400, f"liens invalides ({MAX_CUSTOM_LINKS} maximum)")
    clean_links = []
    for link in links:
        if not isinstance(link, str) or len(link) > 500 or not re.fullmatch(r"https?://\S+", link.strip()):
            raise ApiError(400, "lien invalide : seules les adresses http(s):// sont acceptées")
        clean_links.append(link.strip())
    return {
        "name": _text_field(body, "name", 100, required=True),
        "altitude_m": int(_number_field(body, "altitude_m", 0, 9000)),
        "lat": round(float(_number_field(body, "lat", -90, 90)), 6),
        "lon": round(float(_number_field(body, "lon", -180, 180)), 6),
        "massif": _text_field(body, "massif", 100),
        "region": region,
        "difficulty": difficulty,
        "notes": _text_field(body, "notes", 5000),
        "links": clean_links,
    }
