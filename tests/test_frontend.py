"""Tests du frontend (static/) dans un vrai navigateur (Chromium, via Playwright) : le vrai site,
servi par le vrai serveur, avec des données dans un dossier temporaire.

Ignorés si Playwright ou Chromium ne sont pas installés :
    pip install -r requirements-dev.txt && python -m playwright install chromium
"""
import json
import re
import threading
from http.server import ThreadingHTTPServer

import pytest

from server import app as server_app
from server import auth, storage

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect

PASSWORD = "motdepasse-1234"
CATALOG = json.loads((storage.STATIC_DIR / "mountains.json").read_text(encoding="utf-8"))
TILES = re.compile(r"^https://(tile\.openstreetmap\.org|data\.geopf\.fr)/")


@pytest.fixture
def site(tmp_path, monkeypatch):
    """Serveur sur le vrai static/, données dans tmp_path ; alice (admin), bob (membre), gus (invité)."""
    monkeypatch.setattr(storage, "DATA_DIR", tmp_path)
    monkeypatch.setattr(server_app, "throttle", auth.LoginThrottle())
    store = storage.users_store()
    store.create("alice", PASSWORD, "admin")
    store.create("bob", PASSWORD, "member")
    store.create("gus", PASSWORD, "guest")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server_app.Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    # « localhost » : Chromium y accepte les cookies « Secure » sans HTTPS.
    yield f"http://localhost:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()
    thread.join(timeout=5)


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as pw:
        try:
            b = pw.chromium.launch()
        except sync_api.Error as e:
            pytest.skip(f"Chromium absent ({e.message.splitlines()[0]}) : python -m playwright install chromium")
        yield b
        b.close()


@pytest.fixture
def open_page(browser, site):
    """open_page(utilisateur, chemin) : page connectée ; toute erreur JavaScript fait échouer le test."""
    contexts, errors = [], []

    def _open(username, path="/"):
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block")
        ctx.route(TILES, lambda route: route.abort())  # pas de réseau externe pendant les tests
        contexts.append(ctx)
        page = ctx.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"{site}/login")
        page.fill("#login-form input:not([type=password])", username)
        page.fill("#login-form input[type=password]", PASSWORD)
        page.click("#login-form button[type=submit]")
        page.wait_for_url(f"{site}/")
        if path != "/":
            page.goto(site + path)
        page.wait_for_selector(".peak-item")
        return page

    yield _open
    for ctx in contexts:
        ctx.close()
    assert not errors, f"erreurs JavaScript : {errors}"


def progress_of(username):
    path = storage.user_dir(username) / "progress.json"
    return json.loads(path.read_text()) if path.exists() else {}


def open_peak(page, name):
    page.locator(".peak-item", has_text=name).first.click()
    expect(page.locator("#peak-panel-body h3")).to_contain_text(name)


def fill_peak_form(page, **fields):
    for field, value in fields.items():
        selector = f"#cp-{field}"
        if field in ("difficulty", "region"):
            page.select_option(selector, value)
        else:
            page.fill(selector, str(value))
    page.click("#custom-peak-form button[type=submit]")


# ---------------------------------------------------------------------------

def test_member_sees_whole_catalog(open_page):
    page = open_page("bob")
    expect(page.locator(".peak-item")).to_have_count(len(CATALOG))
    expect(page.locator("#count")).to_contain_text(f"{len(CATALOG)} sommets affichés")
    expect(page.locator("#custom-peak-open")).to_be_visible()


def test_guest_has_no_personal_controls(open_page):
    page = open_page("gus")
    expect(page.locator(".peak-item")).to_have_count(len(CATALOG))
    expect(page.locator("#custom-peak-open")).to_be_hidden()
    expect(page.locator("#status-chips")).to_be_hidden()
    open_peak(page, CATALOG[0]["name"])
    expect(page.locator("#peak-panel .pop-comment-row")).to_be_hidden()


def test_search_filters_list(open_page):
    page = open_page("bob")
    target = CATALOG[0]["name"]
    page.fill("#search", target)
    expect(page.locator(".peak-item .name")).to_have_text([target])


def test_done_and_comment_are_saved(open_page):
    page = open_page("bob")
    peak = CATALOG[0]
    open_peak(page, peak["name"])
    page.check("#peak-panel .pop-done-checkbox")
    page.fill("#peak-panel .pop-comment-input", "  Belle course  ")
    page.locator("#peak-panel .pop-comment-input").blur()
    expect(page.locator("#peak-panel .pop-comment-status")).to_have_text("Enregistré sur le serveur.")
    assert progress_of("bob")[peak["id"]] == {"done": True, "comment": "Belle course"}

    page.reload()
    page.wait_for_selector(".peak-item")
    expect(page.locator("#count")).to_contain_text("1 fait au total")
    page.locator(".chip", has_text="Fait").first.click()
    expect(page.locator(".peak-item .name")).to_have_text([peak["name"]])
    open_peak(page, peak["name"])
    expect(page.locator("#peak-panel .pop-done-checkbox")).to_be_checked()
    expect(page.locator("#peak-panel .pop-comment-input")).to_have_value("Belle course")
    # Hauteur mesurée panneau visible (sinon zone écrasée à 0 px à la première ouverture).
    assert page.locator("#peak-panel .pop-comment-input").bounding_box()["height"] > 20


def test_add_edit_and_delete_custom_peak(open_page):
    page = open_page("bob")
    page.click("#custom-peak-open")
    fill_peak_form(page, name="Pointe du Test", altitude="3111", difficulty="T4", massif="Écrins",
                   lat="45.1", lon="6.3", notes="Par l'arête.", links="https://example.org/topo")
    expect(page.locator("#placement-bar")).to_be_visible()
    expect(page.locator(".placing-arrow")).to_have_count(4)
    page.click("#placement-confirm")
    expect(page.locator("#placement-bar")).to_be_hidden()
    expect(page.locator("#peak-panel-body h3")).to_contain_text("Pointe du Test")
    expect(page.locator("#peak-panel .pop-links a")).to_have_attribute("href", "https://example.org/topo")
    expect(page.locator(".peak-item")).to_have_count(len(CATALOG) + 1)
    [custom] = storage.load_custom_peaks("bob")
    assert (custom["lat"], custom["lon"], custom["difficulty"]) == (45.1, 6.3, "T4")

    # Modification : formulaire prérempli, même id à la fin.
    page.click("#peak-panel .pop-custom-edit")
    expect(page.locator("#custom-peak-title")).to_have_text("Modifier le sommet")
    expect(page.locator("#cp-name")).to_have_value("Pointe du Test")
    expect(page.locator("#cp-links")).to_have_value("https://example.org/topo")
    fill_peak_form(page, name="Pointe Renommée", altitude="3222")
    page.click("#placement-confirm")
    expect(page.locator("#peak-panel-body h3")).to_contain_text("Pointe Renommée")
    expect(page.locator(".peak-item", has_text="Pointe Renommée")).to_contain_text("3222 m")
    expect(page.locator(".peak-item", has_text="Pointe du Test")).to_have_count(0)
    [edited] = storage.load_custom_peaks("bob")
    assert edited["id"] == custom["id"] and edited["name"] == "Pointe Renommée"

    page.reload()
    page.wait_for_selector(".peak-item")
    open_peak(page, "Pointe Renommée")
    page.once("dialog", lambda d: d.accept())
    page.click("#peak-panel .pop-custom-delete")
    expect(page.locator("#peak-panel")).to_be_hidden()
    expect(page.locator(".peak-item")).to_have_count(len(CATALOG))
    assert storage.load_custom_peaks("bob") == []


def test_custom_peak_form_checks(open_page):
    page = open_page("bob")
    page.click("#custom-peak-open")
    fill_peak_form(page, name="Sommet X", altitude="3000", lat="45.2")
    expect(page.locator("#cp-status")).to_contain_text("latitude ET la longitude")
    fill_peak_form(page, lat="", name=CATALOG[0]["name"].upper())
    expect(page.locator("#cp-status")).to_have_text("Un sommet porte déjà ce nom.")
    fill_peak_form(page, name="Sommet X", links="ftp://exemple")
    expect(page.locator("#cp-status")).to_contain_text("Lien invalide")
    page.click("#cp-cancel")
    expect(page.locator("#custom-peak-dialog")).to_be_hidden()
    assert storage.load_custom_peaks("bob") == []


def test_storage_banner_when_space_is_full(open_page, monkeypatch):
    page = open_page("bob")
    expect(page.locator("#storage-banner")).to_be_hidden()

    # Envoi refusé faute de place : bandeau rouge, qui reste affiché.
    monkeypatch.setattr(storage, "QUOTA_BYTES", 1000)
    open_peak(page, CATALOG[0]["name"])
    page.set_input_files("#peak-panel .photos-file-input",
                         files=[{"name": "grande.jpg", "mimeType": "image/jpeg", "buffer": b"x" * 2000}])
    expect(page.locator("#peak-panel .photos-status")).to_contain_text("espace de stockage plein")
    banner = page.locator("#storage-banner")
    expect(banner).to_be_visible()
    expect(banner).to_contain_text("Espace plein")
    page.click("#peak-panel-close")
    expect(banner).to_be_visible()

    # Espace déjà plein au chargement de la page.
    (storage.user_dir("bob") / "photos").mkdir(parents=True, exist_ok=True)
    (storage.user_dir("bob") / "photos" / "occupe.bin").write_bytes(b"x" * 1000)
    page.reload()
    page.wait_for_selector(".peak-item")
    expect(banner).to_contain_text("Espace plein")


def test_admin_views_other_space_read_only(open_page):
    storage.save_progress("bob", {CATALOG[0]["id"]: {"done": True, "comment": "note de bob"}})
    page = open_page("alice", "/?space=bob")
    expect(page.locator("#space-banner")).to_contain_text("bob")
    expect(page.locator("#custom-peak-open")).to_be_hidden()
    expect(page.locator("#storage-banner")).to_be_hidden()
    open_peak(page, CATALOG[0]["name"])
    expect(page.locator("#peak-panel .pop-done-checkbox")).to_be_disabled()
    expect(page.locator("#peak-panel .pop-comment-input")).to_have_value("note de bob")
