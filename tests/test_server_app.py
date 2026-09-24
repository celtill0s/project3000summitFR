"""Tests du backend (server/app.py, server/auth.py) : fonctions pures, comptes et sessions,
matrice des droits d'accès (qui peut lire/écrire quoi), et parcours de bout en bout.
N'utilisent jamais le vrai static/mountains.json ni le vrai data/ du dépôt — tout est isolé
dans un dossier temporaire par test (voir isolated_dirs)."""
import io
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from server import app as server_app
from server import auth

PASSWORD = "motdepasse-1234"
SAMPLE_CATALOG = [
    {
        "id": "pic-de-test",
        "name": "Pic de Test",
        "altitude_m": 3123,
        "lat": 44.5,
        "lon": 6.5,
        "massif": "Massif de Test",
        "region": "Alpes",
        "difficulty": "T3",
        "notes": "Sommet fictif pour les tests.",
        "source": "test.local",
        "source_url": "https://test.local/pic-de-test",
    },
    {
        "id": "aiguille-d-essai",
        "name": "Aiguille d'Essai",
        "altitude_m": 3050,
        "lat": 42.9,
        "lon": 0.3,
        "massif": "Massif d'Essai",
        "region": "Pyrénées",
        "difficulty": "T4",
        "notes": "Autre sommet fictif.",
        "source": "test.local",
        "source_url": "https://test.local/aiguille-dessai",
    },
]
GPX_SAMPLE = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
    b'<trk><trkseg><trkpt lat="44.5" lon="6.5"><ele>2000</ele></trkpt>'
    b'<trkpt lat="44.51" lon="6.51"><ele>2100</ele></trkpt></trkseg></trk></gpx>'
)


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirige STATIC_DIR/DATA_DIR vers un dossier temporaire, avec un site minimal."""
    static_dir = tmp_path / "static"
    data_dir = tmp_path / "data"
    static_dir.mkdir()
    data_dir.mkdir()
    (static_dir / "mountains.json").write_text(json.dumps(SAMPLE_CATALOG, ensure_ascii=False), encoding="utf-8")
    (static_dir / "index.html").write_text('<link href="style.css"><p>carte</p>', encoding="utf-8")
    (static_dir / "login.html").write_text('<link href="style.css"><p>connexion</p>', encoding="utf-8")
    (static_dir / "style.css").write_text("body {}", encoding="utf-8")
    monkeypatch.setattr(server_app, "STATIC_DIR", static_dir)
    monkeypatch.setattr(server_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(server_app, "CATALOG_PATH", static_dir / "mountains.json")
    monkeypatch.setattr(server_app, "throttle", auth.LoginThrottle())
    return static_dir, data_dir


@pytest.fixture
def users(isolated_dirs):
    """alice (admin), bob et carol (membres), gus (invité)."""
    store = server_app.users_store()
    store.create("alice", PASSWORD, "admin")
    store.create("bob", PASSWORD, "member")
    store.create("carol", PASSWORD, "member")
    store.create("gus", PASSWORD, "guest")
    return store


@pytest.fixture
def live_server(isolated_dirs):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_app.Handler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


class Client:
    """Client HTTP de test avec session (cookie géré à la main : le cookie est « Secure », qu'un
    CookieJar refuserait de renvoyer sur http://127.0.0.1)."""

    def __init__(self, base):
        self.base = base
        self.session = None

    def request(self, method, path, data=None, headers=None, csrf=True, json_body=None):
        headers = dict(headers or {})
        if json_body is not None:
            data = json.dumps(json_body).encode()
            headers.setdefault("Content-Type", "application/json")
        if csrf and method in ("POST", "DELETE"):
            headers.setdefault("X-Requested-With", "SommetsApp")
        if self.session:
            headers["Cookie"] = f"session={self.session}"
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            resp = _opener.open(req)
            status, hdrs, body = resp.status, resp.headers, resp.read()
        except urllib.error.HTTPError as e:
            status, hdrs, body = e.code, e.headers, e.read()
        for cookie in hdrs.get_all("Set-Cookie") or []:
            m = re.match(r"session=([^;]*)", cookie)
            if m:
                self.session = m.group(1) or None
        return status, hdrs, body

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def json(self, method, path, **kw):
        status, _, body = self.request(method, path, **kw)
        return status, (json.loads(body) if body else None)

    def login(self, username, password=PASSWORD):
        return self.json("POST", "/api/login", json_body={"username": username, "password": password})


@pytest.fixture
def client(live_server):
    return lambda: Client(live_server)


def logged_in(make_client, username):
    c = make_client()
    status, _ = c.login(username)
    assert status == 200, f"connexion de {username} impossible"
    return c


def upload_photo(c, peak, filename, data):
    q = urllib.parse.urlencode({"filename": filename})
    return c.json("POST", f"/api/peaks/{peak}/photos?{q}", data=data,
                  headers={"Content-Type": "application/octet-stream"})


def peak_of(c, peak_id="pic-de-test", space=None):
    status, peaks = c.json("GET", "/mountains.json" + (f"?space={space}" if space else ""))
    assert status == 200
    return next(p for p in peaks if p["id"] == peak_id)


# ---------------------------------------------------------------------------
# Fonctions pures
# ---------------------------------------------------------------------------

def test_slugify_removes_accents_and_spaces():
    assert server_app.slugify("La Grande Fache") == "la-grande-fache"
    assert server_app.slugify("Pic d'Estaragne") == "pic-d-estaragne"


def test_slugify_never_empty():
    assert server_app.slugify("!!!") == "sommet"


@pytest.mark.parametrize("header,expected", [
    (None, None),
    ("bytes=0-99", (0, 99)),
    ("bytes=100-", (100, 999)),
    ("bytes=-100", (900, 999)),
    ("bytes=500-5000", (500, 999)),
    ("items=0-1", None),
])
def test_parse_range(header, expected):
    assert server_app.parse_range(header, 1000) == expected


def test_parse_range_unsatisfiable():
    with pytest.raises(server_app.ApiError) as exc:
        server_app.parse_range("bytes=2000-", 1000)
    assert exc.value.status == 416


@pytest.mark.parametrize("payload", [
    b"pas du xml",
    b"<kml></kml>",
    b'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa">]><gpx>&a;</gpx>',
])
def test_validate_gpx_rejects(payload):
    with pytest.raises(server_app.ApiError) as exc:
        server_app.validate_gpx(payload)
    assert exc.value.status == 400


def test_validate_gpx_accepts_namespaced_root():
    server_app.validate_gpx(GPX_SAMPLE)


# ---------------------------------------------------------------------------
# auth.py : mots de passe, comptes, sessions, limitation
# ---------------------------------------------------------------------------

def test_password_hash_roundtrip_and_salt():
    h1, h2 = auth.hash_password("secret-tres-long"), auth.hash_password("secret-tres-long")
    assert h1 != h2  # sel aléatoire
    assert h1.startswith("scrypt$")
    assert auth.verify_password("secret-tres-long", h1)
    assert not auth.verify_password("secret-tres-lonG", h1)
    assert not auth.verify_password("x", "n'importe quoi")


@pytest.mark.parametrize("name", ["", "a", "Alice", "al ice", "../etc", "a" * 33, "é-accent", "-tiret"])
def test_invalid_usernames(name):
    with pytest.raises(ValueError):
        auth.validate_username(name)


def test_user_store_rules(isolated_dirs):
    store = server_app.users_store()
    store.create("alice", PASSWORD, "admin")
    with pytest.raises(ValueError):
        store.create("alice", PASSWORD, "member")  # doublon
    with pytest.raises(ValueError):
        store.create("bob", "court", "member")  # mot de passe trop court
    with pytest.raises(ValueError):
        store.create("bob", PASSWORD, "superadmin")  # rôle inconnu
    with pytest.raises(ValueError):
        store.set_role("alice", "member")  # dernier admin
    with pytest.raises(ValueError):
        store.delete("alice")  # dernier admin
    assert store.authenticate("alice", PASSWORD) == {"username": "alice", "role": "admin"}
    assert store.authenticate("alice", "mauvais-mot-de-passe") is None
    assert store.authenticate("inconnu", PASSWORD) is None
    # jamais d'empreinte de mot de passe dans all()
    assert "hash" not in json.dumps(store.all())


def test_users_file_is_private(isolated_dirs):
    server_app.users_store().create("alice", PASSWORD, "admin")
    mode = (isolated_dirs[1] / "users.json").stat().st_mode & 0o777
    assert mode == 0o600


def test_sessions_store_only_token_hashes(isolated_dirs):
    store = server_app.sessions_store()
    token = store.create("alice")
    assert store.get(token) == "alice"
    assert token not in (isolated_dirs[1] / "sessions.json").read_text()
    store.revoke(token)
    assert store.get(token) is None


def test_session_expiry(isolated_dirs, monkeypatch):
    store = server_app.sessions_store()
    token = store.create("alice")
    real_time = time.time
    monkeypatch.setattr(auth.time, "time", lambda: real_time() + auth.SessionStore.TTL + 10)
    assert store.get(token) is None


def test_revoke_user_keeps_given_token(isolated_dirs):
    store = server_app.sessions_store()
    t1, t2, t3 = store.create("alice"), store.create("alice"), store.create("bob")
    store.revoke_user("alice", keep_token=t2)
    assert store.get(t1) is None and store.get(t2) == "alice" and store.get(t3) == "bob"


def test_login_throttle():
    t = auth.LoginThrottle()
    keys = [("user", "alice"), ("ip", "1.2.3.4")]
    for _ in range(auth.LoginThrottle.MAX_FAILURES - 1):
        t.failure(keys)
    assert t.retry_after(keys) == 0
    t.failure(keys)
    assert t.retry_after(keys) > 0
    assert t.retry_after([("user", "autre"), ("ip", "5.6.7.8")]) == 0


# ---------------------------------------------------------------------------
# Connexion, déconnexion, sessions (HTTP)
# ---------------------------------------------------------------------------

def test_login_sets_protected_cookie(client, users):
    c = client()
    status, headers, body = c.post("/api/login", json_body={"username": "bob", "password": PASSWORD})
    assert status == 200 and json.loads(body) == {"username": "bob", "role": "member"}
    cookie = headers["Set-Cookie"]
    for attr in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/"):
        assert attr in cookie


def test_login_is_case_insensitive_on_username(client, users):
    assert client().login("BOB")[0] == 200


@pytest.mark.parametrize("username,password", [("bob", "mauvais-mot-de-passe"), ("inconnu", PASSWORD), ("bob", "")])
def test_login_failures_same_message(client, users, username, password):
    status, body = client().login(username, password)
    assert status == 401
    assert body["error"] == "identifiant ou mot de passe incorrect"


def test_login_throttled_after_repeated_failures(client, users):
    c = client()
    for _ in range(auth.LoginThrottle.MAX_FAILURES):
        assert c.login("bob", "mauvais-mot-de-passe")[0] == 401
    status, headers, _ = c.post("/api/login", json_body={"username": "bob", "password": PASSWORD})
    assert status == 429  # même le bon mot de passe est refusé pendant le blocage
    assert int(headers["Retry-After"]) > 0
    # Depuis une autre adresse, un autre compte n'est pas bloqué.
    other = client()
    status, _ = other.json("POST", "/api/login", json_body={"username": "carol", "password": PASSWORD},
                           headers={"CF-Connecting-IP": "203.0.113.7"})
    assert status == 200


def test_logout_revokes_session(client, users):
    c = logged_in(client, "bob")
    old = c.session
    assert c.json("POST", "/api/logout")[0] == 200
    c.session = old  # réutiliser l'ancien cookie ne marche plus
    assert c.json("GET", "/api/me")[0] == 401


def test_writes_require_csrf_header(client, users):
    c = logged_in(client, "bob")
    status, _ = c.json("POST", "/api/peaks/pic-de-test/done", json_body={"done": True}, csrf=False)
    assert status == 403
    assert not peak_of(c)["done"]
    assert client().json("POST", "/api/login", json_body={"username": "bob", "password": PASSWORD}, csrf=False)[0] == 403


def test_pages_redirect_to_login_when_anonymous(client, users):
    c = client()
    status, headers, _ = c.get("/")
    assert status == 302 and headers["Location"] == "/login"
    status, _, body = c.get("/login")
    assert status == 200 and b"connexion" in body
    c.login("bob")
    status, _, body = c.get("/")
    assert status == 200 and b"carte" in body
    status, headers, _ = c.get("/login")
    assert status == 302 and headers["Location"] == "/"


def test_me(client, users):
    assert logged_in(client, "gus").json("GET", "/api/me") == (200, {"username": "gus", "role": "guest"})


def test_change_own_password(client, users):
    c = logged_in(client, "bob")
    other_device = logged_in(client, "bob")
    assert c.json("POST", "/api/me/password", json_body={"current": "faux-faux-faux", "new": "nouveau-mdp-1234"})[0] == 403
    assert c.json("POST", "/api/me/password", json_body={"current": PASSWORD, "new": "court"})[0] == 400
    assert c.json("POST", "/api/me/password", json_body={"current": PASSWORD, "new": "nouveau-mdp-1234"})[0] == 200
    assert c.json("GET", "/api/me")[0] == 200            # cet appareil reste connecté
    assert other_device.json("GET", "/api/me")[0] == 401  # les autres sont déconnectés
    assert client().login("bob")[0] == 401
    assert client().login("bob", "nouveau-mdp-1234")[0] == 200


# ---------------------------------------------------------------------------
# Matrice des droits : qui peut accéder à quoi
# ---------------------------------------------------------------------------

@pytest.fixture
def populated(client, users):
    """bob et alice ont chacun une photo, une trace GPX, un sommet fait et un commentaire."""
    files = {}
    for name in ("bob", "alice"):
        c = logged_in(client, name)
        _, r = upload_photo(c, "pic-de-test", "p.jpg", b"\xff\xd8\xff\xe0FAKE-" + name.encode())
        files[name] = r["filename"]
        c.json("POST", "/api/peaks/pic-de-test/gpx", data=GPX_SAMPLE)
        c.json("POST", "/api/peaks/pic-de-test/done", json_body={"done": True})
        c.json("POST", "/api/peaks/pic-de-test/comment", json_body={"comment": f"commentaire de {name}"})
    return files


def _matrix_cases():
    # (qui, méthode, chemin, statut attendu) ; {bob}/{alice} = nom du fichier photo de chacun
    anon, guest, bob, carol, alice = None, "gus", "bob", "carol", "alice"
    return [
        # public
        (anon, "GET", "/healthz", 200),
        (anon, "GET", "/login", 200),
        (anon, "GET", "/style.css", 200),
        (anon, "GET", "/v/abc/style.css", 200),
        # anonyme : tout le reste refusé
        (anon, "GET", "/", 302),
        (anon, "GET", "/api/me", 401),
        (anon, "POST", "/api/me/password", 401),
        (anon, "GET", "/mountains.json", 401),
        (anon, "GET", "/photos/bob/pic-de-test/{bob}", 401),
        (anon, "GET", "/thumbs/bob/480/pic-de-test/{bob}", 401),
        (anon, "GET", "/gpx/bob/pic-de-test.gpx", 401),
        (anon, "POST", "/api/peaks/pic-de-test/done", 401),
        (anon, "POST", "/api/peaks/pic-de-test/comment", 401),
        (anon, "POST", "/api/peaks/pic-de-test/photos", 401),
        (anon, "DELETE", "/api/peaks/pic-de-test/photos/{bob}", 401),
        (anon, "POST", "/api/peaks/pic-de-test/gpx", 401),
        (anon, "DELETE", "/api/peaks/pic-de-test/gpx", 401),
        (anon, "GET", "/api/admin/users", 401),
        (anon, "POST", "/api/admin/users", 401),
        (anon, "POST", "/api/admin/users/bob/password", 401),
        (anon, "POST", "/api/admin/users/bob/role", 401),
        (anon, "DELETE", "/api/admin/users/bob", 401),
        # invité : catalogue seulement
        (guest, "GET", "/", 200),
        (guest, "GET", "/mountains.json", 200),
        (guest, "GET", "/mountains.json?space=bob", 403),
        (guest, "GET", "/photos/bob/pic-de-test/{bob}", 403),
        (guest, "GET", "/thumbs/bob/480/pic-de-test/{bob}", 403),
        (guest, "GET", "/gpx/bob/pic-de-test.gpx", 403),
        (guest, "POST", "/api/peaks/pic-de-test/done", 403),
        (guest, "POST", "/api/peaks/pic-de-test/photos?filename=x.jpg", 403),
        (guest, "DELETE", "/api/peaks/pic-de-test/gpx", 403),
        (guest, "GET", "/api/admin/users", 403),
        # membre : son espace uniquement
        (bob, "GET", "/photos/bob/pic-de-test/{bob}", 200),
        (bob, "GET", "/gpx/bob/pic-de-test.gpx", 200),
        (bob, "GET", "/mountains.json?space=bob", 200),
        (bob, "GET", "/photos/alice/pic-de-test/{alice}", 403),
        (bob, "GET", "/thumbs/alice/480/pic-de-test/{alice}", 403),
        (bob, "GET", "/gpx/alice/pic-de-test.gpx", 403),
        (bob, "GET", "/mountains.json?space=alice", 403),
        (carol, "GET", "/photos/bob/pic-de-test/{bob}", 403),
        (bob, "GET", "/api/admin/users", 403),
        (bob, "POST", "/api/admin/users", 403),
        (bob, "DELETE", "/api/admin/users/carol", 403),
        (bob, "POST", "/api/admin/users/carol/password", 403),
        (bob, "POST", "/api/admin/users/bob/role", 403),
        # admin : lit l'espace des autres, gère les comptes
        (alice, "GET", "/photos/bob/pic-de-test/{bob}", 200),
        (alice, "GET", "/thumbs/bob/480/pic-de-test/{bob}", 200),
        (alice, "GET", "/gpx/bob/pic-de-test.gpx", 200),
        (alice, "GET", "/mountains.json?space=bob", 200),
        (alice, "GET", "/mountains.json?space=inconnu", 404),
        (alice, "GET", "/api/admin/users", 200),
        # chemins piégés
        (bob, "GET", "/photos/bob/..%2F..%2Fusers.json/x", 400),
        (bob, "GET", "/photos/..%2Fusers.json/x/y", 403),
        (alice, "GET", "/photos/..%2F..%2Fusers.json/x/y", 404),
        (anon, "GET", "/v/abc/..%2F..%2Fdata%2Fusers.json", 404),
        (anon, "GET", "/users.json", 404),
        (anon, "GET", "/sessions.json", 404),
        (anon, "GET", "/api/inexistante", 404),
    ]


@pytest.mark.parametrize("who,method,path,expected", _matrix_cases(),
                         ids=[f"{w or 'anonyme'} {m} {p} → {e}" for w, m, p, e in _matrix_cases()])
def test_access_matrix(client, populated, who, method, path, expected):
    c = logged_in(client, who) if who else client()
    path = path.format(**populated)
    body = json.dumps({"done": True, "username": "x", "password": "x", "role": "admin"}).encode() if method == "POST" else None
    status, _, _ = c.request(method, path, data=body, headers={"Content-Type": "application/json"})
    assert status == expected, f"{who or 'anonyme'} {method} {path} → {status}, attendu {expected}"


def test_every_private_route_is_covered_by_the_matrix():
    """Garde-fou : toute route non publique doit être testée pour un anonyme (refus attendu).
    Ajouter une route sans l'ajouter à la matrice fait échouer ce test."""
    anon_paths = [(m, p.split("?")[0].format(bob="f.jpg", alice="f.jpg")) for who, m, p, _ in _matrix_cases() if who is None]
    for method, pattern, role, _ in server_app.COMPILED_ROUTES:
        if role is server_app.PUBLIC:
            continue
        assert any(m == method and pattern.fullmatch(p) for m, p in anon_paths), \
            f"route {method} {pattern.pattern} absente de la matrice anonyme"


# ---------------------------------------------------------------------------
# Espaces personnels
# ---------------------------------------------------------------------------

def test_guest_sees_catalog_without_personal_fields(client, populated):
    status, peaks = logged_in(client, "gus").json("GET", "/mountains.json")
    assert status == 200 and len(peaks) == 2
    for p in peaks:
        assert not {"done", "comment", "photos", "gpx"} & p.keys()


def test_spaces_are_isolated(client, populated):
    bob = peak_of(logged_in(client, "bob"))
    carol = peak_of(logged_in(client, "carol"))
    assert bob["done"] and bob["comment"] == "commentaire de bob" and len(bob["photos"]) == 1
    assert bob["gpx"] == "/gpx/bob/pic-de-test.gpx"
    assert not carol["done"] and carol["comment"] == "" and carol["photos"] == [] and "gpx" not in carol


def test_admin_reads_other_space(client, populated):
    p = peak_of(logged_in(client, "alice"), space="bob")
    assert p["comment"] == "commentaire de bob" and p["photos"] == [populated["bob"]]


def test_admin_writes_go_to_own_space(client, populated):
    alice = logged_in(client, "alice")
    alice.json("POST", "/api/peaks/aiguille-d-essai/done", json_body={"done": True})
    assert peak_of(alice, "aiguille-d-essai")["done"]
    assert not peak_of(logged_in(client, "bob"), "aiguille-d-essai")["done"]


def test_invalid_json_returns_400(client, users):
    status, body = logged_in(client, "bob").json("POST", "/api/peaks/pic-de-test/done", data=b"{pas du json",
                                                 headers={"Content-Type": "application/json"})
    assert status == 400 and body == {"error": "JSON invalide"}


def test_unknown_peak_returns_404(client, users):
    assert logged_in(client, "bob").json("POST", "/api/peaks/inexistant/done", json_body={"done": True})[0] == 404


def test_photo_upload_and_delete_roundtrip(client, users, isolated_dirs):
    c = logged_in(client, "bob")
    _, result = upload_photo(c, "pic-de-test", "test.jpg", b"\xff\xd8\xff\xe0FAKE")
    filename = result["filename"]
    assert filename in peak_of(c)["photos"]
    status, _, data = c.get(f"/photos/bob/pic-de-test/{filename}")
    assert status == 200 and data == b"\xff\xd8\xff\xe0FAKE"
    photo_dir = isolated_dirs[1] / "users" / "bob" / "photos" / "pic-de-test"
    assert not list(photo_dir.glob(".*.upload"))
    assert c.json("DELETE", f"/api/peaks/pic-de-test/photos/{filename}")[0] == 200
    assert filename not in peak_of(c)["photos"]
    assert not (photo_dir / filename).exists()


def test_photo_upload_rejects_bad_extension(client, users):
    assert upload_photo(logged_in(client, "bob"), "pic-de-test", "malware.exe", b"data")[0] == 400


def test_photo_upload_rejects_oversized_before_reading(client, users, monkeypatch):
    monkeypatch.setattr(server_app, "MAX_IMAGE_BYTES", 10)
    c = logged_in(client, "bob")
    assert upload_photo(c, "pic-de-test", "big.jpg", b"x" * 100)[0] == 413
    assert peak_of(c)["photos"] == []


def test_video_is_served_with_range_support(client, users):
    c = logged_in(client, "bob")
    video = bytes(range(256)) * 40
    _, result = upload_photo(c, "pic-de-test", "clip.mp4", video)
    url = f"/photos/bob/pic-de-test/{result['filename']}"
    status, headers, body = c.get(url, headers={"Range": "bytes=100-199"})
    assert status == 206 and headers["Content-Range"] == f"bytes 100-199/{len(video)}"
    assert headers["Content-Type"] == "video/mp4" and body == video[100:200]
    status, headers, body = c.get(url)
    assert status == 200 and headers["Accept-Ranges"] == "bytes" and body == video
    assert c.get(url, headers={"Range": f"bytes={len(video)}-"})[0] == 416


def test_head_returns_headers_only(client, users):
    status, headers, body = client().request("HEAD", "/style.css")
    assert status == 200 and int(headers["Content-Length"]) > 0 and body == b""


def test_gpx_upload_and_delete_roundtrip(client, users, isolated_dirs):
    c = logged_in(client, "bob")
    assert c.json("POST", "/api/peaks/pic-de-test/gpx", data=GPX_SAMPLE)[0] == 200
    p = peak_of(c)
    assert c.get(p["gpx"])[2] == GPX_SAMPLE
    assert c.json("DELETE", "/api/peaks/pic-de-test/gpx")[0] == 200
    assert "gpx" not in peak_of(c)
    assert not (isolated_dirs[1] / "users" / "bob" / "gpx" / "pic-de-test.gpx").exists()


def test_gpx_upload_rejects_non_gpx(client, users):
    c = logged_in(client, "bob")
    assert c.json("POST", "/api/peaks/pic-de-test/gpx", data=b"<html>pas un gpx</html>")[0] == 400
    assert "gpx" not in peak_of(c)


def test_thumbnail_is_generated_and_cleaned_up(client, users, isolated_dirs):
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), "red").save(buf, "JPEG")
    c = logged_in(client, "bob")
    _, result = upload_photo(c, "pic-de-test", "grand.jpg", buf.getvalue())
    filename = result["filename"]
    status, _, data = c.get(f"/thumbs/bob/480/pic-de-test/{filename}")
    assert status == 200
    with Image.open(io.BytesIO(data)) as thumb:
        assert thumb.size == (480, 240)
    cached = isolated_dirs[1] / "users" / "bob" / "thumbs" / "pic-de-test" / "480" / f"{filename}.jpg"
    assert cached.is_file()
    c.json("DELETE", f"/api/peaks/pic-de-test/photos/{filename}")
    assert not cached.exists()


def test_thumbnail_unknown_size_is_404(client, users):
    c = logged_in(client, "bob")
    _, result = upload_photo(c, "pic-de-test", "a.jpg", b"\xff\xd8FAKE")
    assert c.get(f"/thumbs/bob/123/pic-de-test/{result['filename']}")[0] == 404


# ---------------------------------------------------------------------------
# Administration des comptes
# ---------------------------------------------------------------------------

def test_admin_list_with_stats_and_no_hashes(client, populated):
    status, body = logged_in(client, "alice").json("GET", "/api/admin/users")
    by_name = {u["username"]: u for u in body["users"]}
    assert set(by_name) == {"alice", "bob", "carol", "gus"}
    assert by_name["bob"]["role"] == "member"
    assert by_name["bob"]["done"] == 1 and by_name["bob"]["photos"] == 1 and by_name["bob"]["gpx"] == 1
    assert "done" not in by_name["gus"]
    assert "hash" not in json.dumps(body) and "scrypt" not in json.dumps(body)


def test_admin_create_user(client, users):
    admin = logged_in(client, "alice")
    assert admin.json("POST", "/api/admin/users", json_body={"username": "dave", "password": PASSWORD, "role": "member"})[0] == 200
    assert client().login("dave") == (200, {"username": "dave", "role": "member"})
    for bad in ({"username": "Dave!", "password": PASSWORD}, {"username": "eve", "password": "court"},
                {"username": "dave", "password": PASSWORD}, {"username": "eve", "password": PASSWORD, "role": "roi"}):
        assert admin.json("POST", "/api/admin/users", json_body=bad)[0] == 400


def test_admin_reset_password_revokes_sessions(client, users):
    bob = logged_in(client, "bob")
    admin = logged_in(client, "alice")
    assert admin.json("POST", "/api/admin/users/bob/password", json_body={"password": "provisoire-1234"})[0] == 200
    assert bob.json("GET", "/api/me")[0] == 401
    assert client().login("bob", "provisoire-1234")[0] == 200
    assert admin.json("POST", "/api/admin/users/inconnu/password", json_body={"password": "provisoire-1234"})[0] == 404


def test_admin_role_change_applies_immediately(client, populated):
    bob = logged_in(client, "bob")
    admin = logged_in(client, "alice")
    assert admin.json("POST", "/api/admin/users/bob/role", json_body={"role": "guest"})[0] == 200
    assert bob.json("GET", f"/photos/bob/pic-de-test/{populated['bob']}")[0] == 403  # sans se reconnecter
    assert admin.json("POST", "/api/admin/users/alice/role", json_body={"role": "member"})[0] == 400  # dernier admin


def test_admin_delete_user_and_data(client, populated, isolated_dirs):
    bob = logged_in(client, "bob")
    admin = logged_in(client, "alice")
    assert admin.json("DELETE", "/api/admin/users/alice")[0] == 400  # pas soi-même
    assert admin.json("DELETE", "/api/admin/users/bob")[0] == 200
    assert bob.json("GET", "/api/me")[0] == 401
    assert not (isolated_dirs[1] / "users" / "bob").exists()
    assert client().login("bob")[0] == 401
    assert admin.json("DELETE", "/api/admin/users/bob")[0] == 404


# ---------------------------------------------------------------------------
# Site : en-têtes, cache, pages versionnées
# ---------------------------------------------------------------------------

def test_security_headers(client, users):
    _, headers, _ = client().get("/healthz")
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_static_files_are_revalidated_with_etag(client, isolated_dirs):
    js = isolated_dirs[0] / "app.js"
    js.write_text("console.log(1)", encoding="utf-8")
    c = client()
    _, headers, _ = c.get("/app.js")
    assert headers["Cache-Control"] == "no-cache"
    assert c.get("/app.js", headers={"If-None-Match": headers["ETag"]})[0] == 304
    js.write_text("console.log(2)", encoding="utf-8")
    status, _, body = c.get("/app.js", headers={"If-None-Match": headers["ETag"]})
    assert status == 200 and body == b"console.log(2)"


def test_pages_reference_versioned_assets(client, users, isolated_dirs):
    (isolated_dirs[0] / "login.html").write_text(
        '<link href="style.css"><a href="#">x</a><a href="https://ign.fr">y</a><img src="/photos/a.jpg">', encoding="utf-8")
    _, headers, body = client().get("/login")
    html = body.decode()
    assert headers["Cache-Control"] == "no-store"
    m = re.search(r'href="/v/([0-9a-f]{12})/style.css"', html)
    assert m, html
    assert 'href="#"' in html and 'href="https://ign.fr"' in html and 'src="/photos/a.jpg"' in html
    status, headers, _ = client().get(f"/v/{m.group(1)}/style.css")
    assert status == 200 and "immutable" in headers["Cache-Control"]


# ---------------------------------------------------------------------------
# Migration des données d'avant les comptes, et commandes d'administration
# ---------------------------------------------------------------------------

def test_legacy_data_migrates_to_admin(isolated_dirs):
    data = isolated_dirs[1]
    (data / "photos" / "pic-de-test").mkdir(parents=True)
    (data / "photos" / "pic-de-test" / "a.jpg").write_bytes(b"photo")
    (data / "gpx").mkdir()
    (data / "gpx" / "pic-de-test.gpx").write_bytes(GPX_SAMPLE)
    # ancien format : indexé par nom de sommet
    (data / "progress.json").write_text(json.dumps({"Pic de Test": {
        "done": True, "comment": "ancien", "photos": [{"filename": "a.jpg", "type": "image"}], "gpx": "pic-de-test.gpx"}}))
    assert server_app.legacy_data_present()
    moved = server_app.migrate_legacy_to("alice")
    assert set(moved) == {"progress.json", "photos", "gpx"}
    assert not server_app.legacy_data_present()
    p = next(x for x in server_app.merged_peaks("alice") if x["id"] == "pic-de-test")
    assert p["done"] and p["comment"] == "ancien" and p["photos"] == ["a.jpg"] and p["gpx"] == "/gpx/alice/pic-de-test.gpx"
    assert (data / "users" / "alice" / "photos" / "pic-de-test" / "a.jpg").read_bytes() == b"photo"


def test_legacy_migration_never_overwrites(isolated_dirs):
    data = isolated_dirs[1]
    (data / "progress.json").write_text("{}")
    (data / "users" / "alice").mkdir(parents=True)
    (data / "users" / "alice" / "progress.json").write_text('{"x": 1}')
    with pytest.raises(RuntimeError):
        server_app.migrate_legacy_to("alice")
    assert (data / "users" / "alice" / "progress.json").read_text() == '{"x": 1}'


def test_cli_create_admin_and_set_password(isolated_dirs, monkeypatch, capsys):
    (isolated_dirs[1] / "progress.json").write_text("{}")
    answers = iter(["court", PASSWORD, "different-1234", PASSWORD, PASSWORD])
    monkeypatch.setattr(server_app.getpass, "getpass", lambda prompt="": next(answers))
    assert server_app.cli(["create-admin", "Alice"]) == 0
    out = capsys.readouterr().out
    assert "créé" in out and "rattachées" in out
    assert server_app.users_store().get("alice") == {"username": "alice", "role": "admin"}
    answers2 = iter(["nouveau-mdp-1234", "nouveau-mdp-1234"])
    monkeypatch.setattr(server_app.getpass, "getpass", lambda prompt="": next(answers2))
    assert server_app.cli(["set-password", "alice"]) == 0
    assert server_app.users_store().authenticate("alice", "nouveau-mdp-1234")
    assert server_app.cli(["set-password", "inconnu"]) == 1
    assert server_app.cli(["n-importe-quoi"]) == 2
