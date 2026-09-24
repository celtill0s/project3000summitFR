"""Tests basiques du backend (server/app.py) : fonctions pures + quelques parcours de bout
en bout critiques pour la sécurité/l'intégrité des données (traversal, upload, round-trips).
N'utilisent jamais le vrai static/mountains.json ni le vrai data/ du dépôt — tout est isolé
dans un dossier temporaire par test (voir isolated_dirs)."""
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from server import app as server_app

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


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    """Redirige STATIC_DIR/DATA_DIR (et dérivés) vers un dossier temporaire."""
    static_dir = tmp_path / "static"
    data_dir = tmp_path / "data"
    static_dir.mkdir()
    data_dir.mkdir()
    (static_dir / "mountains.json").write_text(
        json.dumps(SAMPLE_CATALOG, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(server_app, "STATIC_DIR", static_dir)
    monkeypatch.setattr(server_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(server_app, "CATALOG_PATH", static_dir / "mountains.json")
    monkeypatch.setattr(server_app, "PROGRESS_PATH", data_dir / "progress.json")
    monkeypatch.setattr(server_app, "PHOTOS_DIR", data_dir / "photos")
    monkeypatch.setattr(server_app, "GPX_DIR", data_dir / "gpx")
    monkeypatch.setattr(server_app, "THUMBS_DIR", data_dir / "thumbs")
    return static_dir, data_dir


# ---------------------------------------------------------------------------
# Fonctions pures
# ---------------------------------------------------------------------------

def test_slugify_removes_accents_and_spaces():
    assert server_app.slugify("La Grande Fache") == "la-grande-fache"
    assert server_app.slugify("Pic d'Estaragne") == "pic-d-estaragne"
    assert server_app.slugify("Ouille Noire") == "ouille-noire"


def test_slugify_never_empty():
    assert server_app.slugify("!!!") == "sommet"


@pytest.mark.parametrize("header,expected", [
    (None, None),
    ("bytes=0-99", (0, 99)),
    ("bytes=100-", (100, 999)),
    ("bytes=-100", (900, 999)),
    ("bytes=500-5000", (500, 999)),  # fin recadrée sur la taille du fichier
    ("items=0-1", None),  # unité inconnue : ignorée, fichier complet
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
# Catalogue / overlay (mountains.json + data/progress.json)
# ---------------------------------------------------------------------------

def test_merged_peaks_defaults_when_no_progress(isolated_dirs):
    peaks = server_app.merged_peaks()
    assert len(peaks) == 2
    p = next(p for p in peaks if p["id"] == "pic-de-test")
    assert p["done"] is False
    assert p["comment"] == ""
    assert p["photos"] == []
    assert "gpx" not in p


def test_save_progress_roundtrips_and_is_atomic(isolated_dirs):
    server_app.save_progress({"pic-de-test": {"done": True, "comment": "Superbe"}})
    reloaded = server_app.load_progress()
    assert reloaded["pic-de-test"]["done"] is True
    assert reloaded["pic-de-test"]["comment"] == "Superbe"
    assert not server_app.PROGRESS_PATH.with_suffix(".tmp").exists()


def test_merged_peaks_reflects_progress_overlay(isolated_dirs):
    server_app.save_progress({
        "pic-de-test": {
            "done": True,
            "comment": "Vue magnifique",
            "photos": [{"filename": "abc.jpg", "type": "image"}],
            "gpx": "pic-de-test.gpx",
        }
    })
    peaks = server_app.merged_peaks()
    p = next(p for p in peaks if p["id"] == "pic-de-test")
    assert p["done"] is True
    assert p["comment"] == "Vue magnifique"
    assert p["photos"] == ["abc.jpg"]
    assert p["gpx"] == "/gpx/pic-de-test.gpx"
    assert p["altitude_m"] == 3123  # le catalogue public reste intact


def test_legacy_name_keys_are_migrated_to_ids(isolated_dirs, capsys):
    # Ancien format : progress.json indexé par NOM de sommet.
    server_app.save_progress({
        "Pic de Test": {"done": True, "comment": "Ancien format"},
        "Sommet Renommé": {"done": True},
    })
    p = next(p for p in server_app.merged_peaks() if p["id"] == "pic-de-test")
    assert p["done"] is True and p["comment"] == "Ancien format"

    server_app.migrate_on_startup()
    stored = json.loads(server_app.PROGRESS_PATH.read_text(encoding="utf-8"))
    assert stored["pic-de-test"]["comment"] == "Ancien format"
    assert "Pic de Test" not in stored
    # Entrée orpheline : conservée (jamais de perte de données) et signalée dans les logs.
    assert stored["Sommet Renommé"] == {"done": True}
    assert "Sommet Renommé" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Bout en bout : vrai serveur HTTP sur un port éphémère
# ---------------------------------------------------------------------------

GPX_SAMPLE = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
    b'<trk><trkseg><trkpt lat="44.5" lon="6.5"><ele>2000</ele></trkpt>'
    b'<trkpt lat="44.51" lon="6.51"><ele>2100</ele></trkpt></trkseg></trk></gpx>'
)


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


def _get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req) as r:
        return r.status, r.read()


def _request(url, data=None, method="POST", headers=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req) as r:
        return r.status, json.loads(r.read())


def _post_json(url, obj):
    return _request(url, json.dumps(obj).encode(), headers={"Content-Type": "application/json"})


def _peak(live_server, peak_id="pic-de-test"):
    _, body = _get(f"{live_server}/mountains.json")
    return next(p for p in json.loads(body) if p["id"] == peak_id)


def _upload_photo(live_server, filename, data, peak_id="pic-de-test"):
    q = urllib.parse.urlencode({"filename": filename})
    return _request(f"{live_server}/api/peaks/{peak_id}/photos?{q}", data,
                    headers={"Content-Type": "application/octet-stream"})


def test_healthz(live_server):
    status, body = _get(f"{live_server}/healthz")
    assert status == 200
    assert json.loads(body) == {"ok": True}


def test_security_headers(live_server):
    with urllib.request.urlopen(f"{live_server}/healthz") as r:
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert "script-src 'self'" in r.headers["Content-Security-Policy"]
        # Régression : same-origin/no-referrer supprime le Referer exigé par les tuiles OSM.
        assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_get_mountains_json(live_server):
    status, body = _get(f"{live_server}/mountains.json")
    assert status == 200
    assert len(json.loads(body)) == 2


def test_path_traversal_on_photos_is_rejected(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{live_server}/photos/..%2f..%2fserver%2fapp.py")
    assert exc.value.code == 400


def test_path_traversal_on_thumbs_is_rejected(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{live_server}/thumbs/..%2f..%2f/480/app.py")
    assert exc.value.code in (400, 404)


def test_unknown_extension_route_is_not_found(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{live_server}/server/app.py")
    assert exc.value.code == 404


def test_unknown_peak_returns_404(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _post_json(f"{live_server}/api/peaks/sommet-inexistant/done", {"done": True})
    assert exc.value.code == 404


def test_done_and_comment_roundtrip(live_server):
    assert _post_json(f"{live_server}/api/peaks/pic-de-test/done", {"done": True})[0] == 200
    assert _post_json(f"{live_server}/api/peaks/pic-de-test/comment", {"comment": "Testé automatiquement"})[0] == 200
    p = _peak(live_server)
    assert p["done"] is True
    assert p["comment"] == "Testé automatiquement"


def test_peak_id_with_apostrophe_in_name(live_server):
    # Nom avec apostrophe/accents : la route utilise l'id, jamais le nom.
    assert _post_json(f"{live_server}/api/peaks/aiguille-d-essai/done", {"done": True})[0] == 200
    assert _peak(live_server, "aiguille-d-essai")["done"] is True


def test_invalid_json_returns_400(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _request(f"{live_server}/api/peaks/pic-de-test/done", b"{pas du json",
                 headers={"Content-Type": "application/json"})
    assert exc.value.code == 400
    assert json.loads(exc.value.read()) == {"error": "JSON invalide"}


def test_photo_upload_and_delete_roundtrip(live_server):
    _, result = _upload_photo(live_server, "test.jpg", b"\xff\xd8\xff\xe0FAKE")
    assert result["ok"] is True
    filename = result["filename"]
    assert filename in _peak(live_server)["photos"]

    status, data = _get(f"{live_server}/photos/pic-de-test/{filename}")
    assert status == 200 and data == b"\xff\xd8\xff\xe0FAKE"
    assert not list((server_app.PHOTOS_DIR / "pic-de-test").glob(".*.upload"))  # pas de temporaire oublié

    assert _request(f"{live_server}/api/peaks/pic-de-test/photos/{filename}", method="DELETE")[0] == 200
    assert filename not in _peak(live_server)["photos"]
    assert not (server_app.PHOTOS_DIR / "pic-de-test" / filename).exists()


def test_photo_upload_rejects_bad_extension(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _upload_photo(live_server, "malware.exe", b"data")
    assert exc.value.code == 400


def test_photo_upload_rejects_oversized_before_reading(live_server, monkeypatch):
    monkeypatch.setattr(server_app, "MAX_IMAGE_BYTES", 10)
    with pytest.raises(urllib.error.HTTPError) as exc:
        _upload_photo(live_server, "big.jpg", b"x" * 100)
    assert exc.value.code == 413
    assert _peak(live_server)["photos"] == []


def test_video_is_served_with_range_support(live_server):
    video = bytes(range(256)) * 40  # 10 240 octets
    _, result = _upload_photo(live_server, "clip.mp4", video)
    url = f"{live_server}/photos/pic-de-test/{result['filename']}"

    req = urllib.request.Request(url, headers={"Range": "bytes=100-199"})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206
        assert r.headers["Content-Range"] == f"bytes 100-199/{len(video)}"
        assert r.headers["Content-Type"] == "video/mp4"
        assert r.read() == video[100:200]

    with urllib.request.urlopen(url) as r:
        assert r.status == 200
        assert r.headers["Accept-Ranges"] == "bytes"
        assert r.read() == video

    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(url, {"Range": f"bytes={len(video)}-"})
    assert exc.value.code == 416


def test_head_returns_headers_only(live_server, isolated_dirs):
    static_dir, _ = isolated_dirs
    (static_dir / "style.css").write_text("body {}", encoding="utf-8")
    req = urllib.request.Request(f"{live_server}/style.css", method="HEAD")
    with urllib.request.urlopen(req) as r:
        assert r.status == 200
        assert int(r.headers["Content-Length"]) > 0
        assert r.read() == b""


def test_gpx_upload_and_delete_roundtrip(live_server):
    status, _ = _request(f"{live_server}/api/peaks/pic-de-test/gpx", GPX_SAMPLE,
                         headers={"Content-Type": "application/gpx+xml"})
    assert status == 200
    p = _peak(live_server)
    assert p["gpx"] == "/gpx/pic-de-test.gpx"
    assert _get(f"{live_server}{p['gpx']}")[1] == GPX_SAMPLE

    assert _request(f"{live_server}/api/peaks/pic-de-test/gpx", method="DELETE")[0] == 200
    assert "gpx" not in _peak(live_server)
    assert not (server_app.GPX_DIR / "pic-de-test.gpx").exists()


def test_gpx_upload_rejects_non_gpx(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _request(f"{live_server}/api/peaks/pic-de-test/gpx", b"<html>pas un gpx</html>")
    assert exc.value.code == 400
    assert "gpx" not in _peak(live_server)


def test_thumbnail_is_generated_and_cleaned_up(live_server):
    Image = pytest.importorskip("PIL.Image")
    import io
    buf = io.BytesIO()
    Image.new("RGB", (2000, 1000), "red").save(buf, "JPEG")
    _, result = _upload_photo(live_server, "grand.jpg", buf.getvalue())
    filename = result["filename"]

    status, data = _get(f"{live_server}/thumbs/pic-de-test/480/{filename}")
    assert status == 200
    with Image.open(io.BytesIO(data)) as thumb:
        assert thumb.size == (480, 240)
    cached = server_app.THUMBS_DIR / "pic-de-test" / "480" / f"{filename}.jpg"
    assert cached.is_file()

    _request(f"{live_server}/api/peaks/pic-de-test/photos/{filename}", method="DELETE")
    assert not cached.exists()


def test_thumbnail_unknown_size_is_404(live_server):
    _, result = _upload_photo(live_server, "a.jpg", b"\xff\xd8FAKE")
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{live_server}/thumbs/pic-de-test/123/{result['filename']}")
    assert exc.value.code == 404


def test_static_files_are_revalidated_with_etag(live_server, isolated_dirs):
    static_dir, _ = isolated_dirs
    js = static_dir / "app.js"
    js.write_text("console.log(1)", encoding="utf-8")
    with urllib.request.urlopen(f"{live_server}/app.js") as r:
        assert r.headers["Cache-Control"] == "no-cache"
        etag = r.headers["ETag"]
    # Inchangé : 304 sans corps.
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{live_server}/app.js", {"If-None-Match": etag})
    assert exc.value.code == 304
    # Modifié (mise à jour du site) : nouvel ETag, nouveau contenu servi.
    js.write_text("console.log(2)", encoding="utf-8")
    status, body = _get(f"{live_server}/app.js", {"If-None-Match": etag})
    assert status == 200 and body == b"console.log(2)"


def test_photos_are_cached_long_and_privately(live_server):
    _, result = _upload_photo(live_server, "p.jpg", b"\xff\xd8FAKE")
    with urllib.request.urlopen(f"{live_server}/photos/pic-de-test/{result['filename']}") as r:
        assert r.headers["Cache-Control"].startswith("private, max-age=31536000")


def test_index_references_versioned_assets(live_server, isolated_dirs):
    static_dir, _ = isolated_dirs
    (static_dir / "js").mkdir()
    (static_dir / "js" / "main.js").write_text("import './map.js';", encoding="utf-8")
    (static_dir / "style.css").write_text("body {}", encoding="utf-8")
    (static_dir / "index.html").write_text(
        '<link href="style.css"><script type="module" src="js/main.js"></script>'
        '<a href="#">x</a><a href="https://ign.fr">y</a><img src="/photos/a.jpg">',
        encoding="utf-8",
    )
    with urllib.request.urlopen(f"{live_server}/") as r:
        assert r.headers["Cache-Control"] == "no-store"
        html = r.read().decode()
    m = re.search(r'src="/v/([0-9a-f]{12})/js/main.js"', html)
    assert m, html
    version = m.group(1)
    assert f'href="/v/{version}/style.css"' in html
    # Liens absolus, externes et ancres : intacts.
    assert 'href="#"' in html and 'href="https://ign.fr"' in html and 'src="/photos/a.jpg"' in html

    with urllib.request.urlopen(f"{live_server}/v/{version}/js/main.js") as r:
        assert r.read() == b"import './map.js';"
        assert "immutable" in r.headers["Cache-Control"]

    # Un fichier modifié (mise à jour) change l'empreinte, donc toutes les URLs.
    (static_dir / "js" / "main.js").write_text("import './map.js'; // v2", encoding="utf-8")
    _, body = _get(f"{live_server}/")
    assert f"/v/{version}/" not in body.decode()


def test_versioned_prefix_keeps_whitelist_and_traversal_protection(live_server, isolated_dirs):
    static_dir, _ = isolated_dirs
    (static_dir / "secret.py").write_text("x", encoding="utf-8")
    for url, codes in [("/v/abc/secret.py", (404,)), ("/v/abc/..%2f..%2fserver%2fapp.js", (400, 404)), ("/v/abc", (404,))]:
        with pytest.raises(urllib.error.HTTPError) as exc:
            _get(f"{live_server}{url}")
        assert exc.value.code in codes, url


def test_pwa_files_are_served(live_server, isolated_dirs):
    static_dir, _ = isolated_dirs
    (static_dir / "manifest.webmanifest").write_text('{"name": "x"}', encoding="utf-8")
    (static_dir / "sw.js").write_text("self.addEventListener('fetch', () => {});", encoding="utf-8")
    (static_dir / "index.html").write_text(
        '<link rel="manifest" href="manifest.webmanifest" crossorigin="use-credentials" />',
        encoding="utf-8",
    )
    _, html = _get(f"{live_server}/")
    m = re.search(r'href="(/v/[0-9a-f]{12}/manifest.webmanifest)" crossorigin="use-credentials"', html.decode())
    assert m, html
    with urllib.request.urlopen(f"{live_server}{m.group(1)}") as r:
        assert r.headers["Content-Type"] == "application/manifest+json"
    # Service worker à la racine (portée = tout le site), revalidé à chaque fois, et autorisé
    # par sa propre CSP à récupérer les tuiles.
    with urllib.request.urlopen(f"{live_server}/sw.js") as r:
        assert r.headers["Content-Type"] == "text/javascript"
        assert r.headers["Cache-Control"] == "no-cache"
        csp = r.headers["Content-Security-Policy"]
        assert "https://tile.openstreetmap.org" in csp.split("connect-src")[1].split(";")[0]
        assert "https://data.geopf.fr" in csp.split("connect-src")[1].split(";")[0]
