"""Tests basiques du backend (server/app.py) : fonctions pures + quelques parcours de bout
en bout critiques pour la sécurité/l'intégrité des données (traversal, upload, round-trips).
N'utilisent jamais le vrai static/mountains.json ni le vrai data/ du dépôt — tout est isolé
dans un dossier temporaire par test (voir isolated_dirs)."""
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from server import app as server_app

SAMPLE_CATALOG = [
    {
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


def test_parse_multipart_extracts_file_field():
    body = (
        b"--BOUNDARY\r\n"
        b'Content-Disposition: form-data; name="file"; filename="photo.jpg"\r\n'
        b"Content-Type: image/jpeg\r\n\r\n"
        b"FAKEJPEGDATA"
        b"\r\n--BOUNDARY--\r\n"
    )
    parts = server_app.parse_multipart("multipart/form-data; boundary=BOUNDARY", body)
    assert "file" in parts
    assert parts["file"].get_filename() == "photo.jpg"
    assert parts["file"].get_payload(decode=True) == b"FAKEJPEGDATA"


# ---------------------------------------------------------------------------
# Catalogue / overlay (mountains.json + data/progress.json)
# ---------------------------------------------------------------------------

def test_merged_peaks_defaults_when_no_progress(isolated_dirs):
    peaks = server_app.merged_peaks()
    assert len(peaks) == 2
    p = next(p for p in peaks if p["name"] == "Pic de Test")
    assert p["done"] is False
    assert p["comment"] == ""
    assert p["photos"] == []
    assert "gpx" not in p


def test_save_progress_roundtrips_and_is_atomic(isolated_dirs):
    server_app.save_progress({"Pic de Test": {"done": True, "comment": "Superbe"}})
    reloaded = server_app.load_progress()
    assert reloaded["Pic de Test"]["done"] is True
    assert reloaded["Pic de Test"]["comment"] == "Superbe"
    assert not server_app.PROGRESS_PATH.with_suffix(".tmp").exists()


def test_merged_peaks_reflects_progress_overlay(isolated_dirs):
    server_app.save_progress({
        "Pic de Test": {
            "done": True,
            "comment": "Vue magnifique",
            "photos": [{"filename": "abc.jpg", "type": "image"}],
            "gpx": "pic-de-test.gpx",
        }
    })
    peaks = server_app.merged_peaks()
    p = next(p for p in peaks if p["name"] == "Pic de Test")
    assert p["done"] is True
    assert p["comment"] == "Vue magnifique"
    assert p["photos"] == ["abc.jpg"]
    assert p["gpx"] == "/gpx/pic-de-test.gpx"
    assert p["altitude_m"] == 3123  # le catalogue public reste intact


# ---------------------------------------------------------------------------
# Bout en bout : vrai serveur HTTP sur un port éphémère
# ---------------------------------------------------------------------------

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


def _get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def test_healthz(live_server):
    status, body = _get(f"{live_server}/healthz")
    assert status == 200
    assert json.loads(body) == {"ok": True}


def test_get_mountains_json(live_server):
    status, body = _get(f"{live_server}/mountains.json")
    assert status == 200
    assert len(json.loads(body)) == 2


def test_path_traversal_on_photos_is_rejected(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{live_server}/photos/..%2f..%2fserver%2fapp.py")
    assert exc.value.code == 400


def test_unknown_extension_route_is_not_found(live_server):
    with pytest.raises(urllib.error.HTTPError) as exc:
        _get(f"{live_server}/server/app.py")
    assert exc.value.code == 404


def test_unknown_peak_returns_404(live_server):
    name = urllib.parse.quote("Sommet Inexistant")
    req = urllib.request.Request(
        f"{live_server}/api/peaks/{name}/done",
        data=json.dumps({"done": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 404


def test_done_and_comment_roundtrip(live_server):
    name = urllib.parse.quote("Pic de Test")

    req = urllib.request.Request(
        f"{live_server}/api/peaks/{name}/done",
        data=json.dumps({"done": True}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        assert r.status == 200

    req = urllib.request.Request(
        f"{live_server}/api/peaks/{name}/comment",
        data=json.dumps({"comment": "Testé automatiquement"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        assert r.status == 200

    _, body = _get(f"{live_server}/mountains.json")
    p = next(p for p in json.loads(body) if p["name"] == "Pic de Test")
    assert p["done"] is True
    assert p["comment"] == "Testé automatiquement"


def test_photo_upload_and_delete_roundtrip(live_server):
    name = urllib.parse.quote("Pic de Test")
    boundary = "TESTBOUNDARY"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="test.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode() + b"\xff\xd8\xff\xe0FAKE" + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{live_server}/api/peaks/{name}/photos",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        result = json.loads(r.read())
    assert result["ok"] is True
    filename = result["filename"]

    _, body2 = _get(f"{live_server}/mountains.json")
    p = next(p for p in json.loads(body2) if p["name"] == "Pic de Test")
    assert filename in p["photos"]

    status, _ = _get(f"{live_server}/photos/pic-de-test/{filename}")
    assert status == 200

    del_req = urllib.request.Request(
        f"{live_server}/api/peaks/{name}/photos/{filename}", method="DELETE"
    )
    with urllib.request.urlopen(del_req) as r:
        assert r.status == 200

    _, body3 = _get(f"{live_server}/mountains.json")
    p = next(p for p in json.loads(body3) if p["name"] == "Pic de Test")
    assert filename not in p["photos"]


def test_photo_upload_rejects_bad_extension(live_server):
    name = urllib.parse.quote("Pic de Test")
    boundary = "TESTBOUNDARY"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="malware.exe"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
        f"data\r\n--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        f"{live_server}/api/peaks/{name}/photos",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400
