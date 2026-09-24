"""Comptes utilisateurs, mots de passe, sessions et limitation des tentatives de connexion.

Bibliothèque standard uniquement. Tout est stocké dans data/ (jamais dans git) :
- data/users.json    : comptes (mot de passe haché avec scrypt, rôle) ;
- data/sessions.json : sessions ouvertes (seule l'empreinte SHA-256 du jeton est gardée : une
  fuite de ce fichier ne permet pas de se connecter).

Rôles : « guest » (invité : catalogue seul), « member » (son propre espace), « admin »
(son espace + gestion des comptes + lecture de l'espace des autres).
"""
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path

ROLES = ("guest", "member", "admin")
ROLE_RANK = {role: rank for rank, role in enumerate(ROLES)}
USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{1,31}")
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256

# scrypt (résistant aux attaques par GPU) : 32 Mio de mémoire et ~0,1 à 0,5 s par vérification
# selon la machine — seulement à la connexion, jamais à chaque requête (sessions ensuite).
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
SCRYPT_MAXMEM = 64 * 1024 * 1024


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
                        maxmem=SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, expected = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r),
                            p=int(p), maxmem=SCRYPT_MAXMEM, dklen=32)
        return hmac.compare_digest(dk, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


# Vérifiée quand l'identifiant n'existe pas : même durée de réponse qu'un mauvais mot de passe,
# pour ne pas révéler quels identifiants existent.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def validate_username(username: str) -> str:
    if not isinstance(username, str) or not USERNAME_RE.fullmatch(username):
        raise ValueError("identifiant invalide : 2 à 32 caractères, minuscules, chiffres, - ou _")
    return username


def validate_password(password: str) -> str:
    if not isinstance(password, str) or not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise ValueError(f"mot de passe trop court : {MIN_PASSWORD_LENGTH} caractères minimum")
    return password


def validate_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError("rôle invalide")
    return role


def _read_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def _write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)  # écriture atomique


class UserStore:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    def _load(self) -> dict:
        return _read_json(self.path, {"users": {}})["users"]

    def _save(self, users: dict):
        _write_json(self.path, {"users": users})

    def all(self) -> dict:
        """{identifiant: {"role", "created"}} — sans les empreintes de mot de passe."""
        return {u: {"role": d["role"], "created": d.get("created")} for u, d in self._load().items()}

    def get(self, username: str):
        d = self._load().get(username)
        return {"username": username, "role": d["role"]} if d else None

    def count(self) -> int:
        return len(self._load())

    def create(self, username: str, password: str, role: str):
        validate_username(username)
        validate_password(password)
        validate_role(role)
        hashed = hash_password(password)  # hors du verrou (coûteux)
        with self.lock:
            users = self._load()
            if username in users:
                raise ValueError("cet identifiant existe déjà")
            users[username] = {"hash": hashed, "role": role, "created": int(time.time())}
            self._save(users)

    def set_password(self, username: str, password: str):
        validate_password(password)
        hashed = hash_password(password)
        with self.lock:
            users = self._load()
            if username not in users:
                raise KeyError(username)
            users[username]["hash"] = hashed
            self._save(users)

    def _admins_after(self, users: dict, username: str, new_role) -> int:
        return sum(1 for u, d in users.items() if (new_role if u == username else d["role"]) == "admin")

    def set_role(self, username: str, role: str):
        validate_role(role)
        with self.lock:
            users = self._load()
            if username not in users:
                raise KeyError(username)
            if self._admins_after(users, username, role) == 0:
                raise ValueError("impossible : il doit rester au moins un administrateur")
            users[username]["role"] = role
            self._save(users)

    def delete(self, username: str):
        with self.lock:
            users = self._load()
            if username not in users:
                raise KeyError(username)
            if self._admins_after(users, username, None) == 0:
                raise ValueError("impossible : il doit rester au moins un administrateur")
            del users[username]
            self._save(users)

    def authenticate(self, username: str, password: str):
        """Renvoie {"username", "role"} si les identifiants sont bons, sinon None."""
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > MAX_PASSWORD_LENGTH:
            return None
        d = self._load().get(username)
        ok = verify_password(password, d["hash"] if d else _DUMMY_HASH)
        return {"username": username, "role": d["role"]} if (d and ok) else None


class SessionStore:
    TTL = 30 * 24 * 3600      # une session inutilisée pendant 30 jours expire
    TOUCH_INTERVAL = 3600     # prolongation enregistrée au plus une fois par heure (moins d'écritures)

    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _load(self) -> dict:
        now = time.time()
        return {k: v for k, v in _read_json(self.path, {}).items() if v.get("expires", 0) > now}

    def create(self, username: str) -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.lock:
            sessions = self._load()
            sessions[self._key(token)] = {"user": username, "created": int(now), "expires": int(now + self.TTL)}
            _write_json(self.path, sessions)
        return token

    def get(self, token: str):
        """Identifiant associé au jeton (et prolongation de la session), ou None."""
        if not token or len(token) > 128:
            return None
        key = self._key(token)
        sessions = self._load()
        s = sessions.get(key)
        if not s:
            return None
        now = time.time()
        if s["expires"] - now < self.TTL - self.TOUCH_INTERVAL:
            with self.lock:
                sessions = self._load()
                if key in sessions:
                    sessions[key]["expires"] = int(now + self.TTL)
                    _write_json(self.path, sessions)
        return s["user"]

    def revoke(self, token: str):
        with self.lock:
            sessions = self._load()
            if sessions.pop(self._key(token or ""), None) is not None:
                _write_json(self.path, sessions)

    def revoke_user(self, username: str, keep_token: str = None):
        """Ferme toutes les sessions d'un utilisateur (mot de passe changé, compte supprimé)."""
        keep = self._key(keep_token) if keep_token else None
        with self.lock:
            sessions = self._load()
            kept = {k: v for k, v in sessions.items() if v["user"] != username or k == keep}
            if len(kept) != len(sessions):
                _write_json(self.path, kept)


class LoginThrottle:
    """Bloque temporairement après trop d'échecs, par identifiant ET par adresse IP : deviner un
    mot de passe devient impraticable (5 essais par quart d'heure)."""
    MAX_FAILURES = 5
    WINDOW = 15 * 60
    LOCKOUT = 15 * 60

    def __init__(self):
        self.lock = threading.Lock()
        self.failures = {}      # clé -> [horodatages]
        self.locked_until = {}  # clé -> horodatage

    def retry_after(self, keys) -> int:
        now = time.time()
        with self.lock:
            return max([int(self.locked_until.get(k, 0) - now) + 1 for k in keys if self.locked_until.get(k, 0) > now] or [0])

    def failure(self, keys):
        now = time.time()
        with self.lock:
            for k in keys:
                recent = [t for t in self.failures.get(k, []) if now - t < self.WINDOW] + [now]
                self.failures[k] = recent
                if len(recent) >= self.MAX_FAILURES:
                    self.locked_until[k] = now + self.LOCKOUT
                    self.failures[k] = []

    def success(self, key):
        with self.lock:
            self.failures.pop(key, None)
            self.locked_until.pop(key, None)
