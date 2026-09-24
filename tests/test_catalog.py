"""Validation du vrai catalogue public (static/mountains.json) : garde-fou contre les fautes
de frappe lors de l'ajout/la modification d'un sommet (champ manquant, cotation inconnue,
coordonnées inversées, doublon…)."""
import json
import re
from pathlib import Path

import pytest

CATALOG_PATH = Path(__file__).resolve().parent.parent / "static" / "mountains.json"
REQUIRED_FIELDS = {
    "id": str,
    "name": str,
    "altitude_m": int,
    "lat": float,
    "lon": float,
    "massif": str,
    "region": str,
    "difficulty": str,
    "notes": str,
    "source": str,
    "source_url": str,
}
# Champs gérés par le serveur (data/progress.json) : ne doivent jamais apparaître dans le catalogue.
PRIVATE_FIELDS = {"done", "comment", "photos", "gpx"}
REGIONS = {"Alpes", "Pyrénées"}
DIFFICULTIES = {"T2", "T3", "T4"}
# Emprise large Alpes + Pyrénées françaises (sommets frontaliers inclus).
LAT_RANGE = (42.3, 46.5)
LON_RANGE = (-2.0, 7.8)

CATALOG = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_catalog_is_non_empty_list():
    assert isinstance(CATALOG, list) and CATALOG


@pytest.mark.parametrize("peak", CATALOG, ids=lambda p: p.get("name", "?"))
def test_peak_entry_is_valid(peak):
    for field, typ in REQUIRED_FIELDS.items():
        assert field in peak, f"champ manquant : {field}"
        value = peak[field]
        if typ is float:
            assert isinstance(value, (int, float)) and not isinstance(value, bool), field
        else:
            assert isinstance(value, typ), f"{field} doit être de type {typ.__name__}"
        if typ is str:
            assert value.strip(), f"{field} vide"
    assert not PRIVATE_FIELDS & peak.keys(), "données personnelles dans le catalogue"
    assert peak["region"] in REGIONS
    assert peak["difficulty"] in DIFFICULTIES
    assert peak["altitude_m"] >= 3000
    assert LAT_RANGE[0] <= peak["lat"] <= LAT_RANGE[1], "latitude hors emprise (lat/lon inversés ?)"
    assert LON_RANGE[0] <= peak["lon"] <= LON_RANGE[1], "longitude hors emprise (lat/lon inversés ?)"
    assert peak["source_url"].startswith("https://")
    # L'id sert de clé dans data/progress.json ET de nom de dossier (photos, gpx) : format
    # strict, et il ne doit JAMAIS changer une fois publié (même si le nom est corrigé).
    assert re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", peak["id"]), "id invalide (a-z, 0-9, tirets)"
    if "crampon" in peak:
        c = peak["crampon"]
        assert set(c) == {"grade", "confirmed", "season", "note"}
        assert isinstance(c["confirmed"], bool)
        assert all(isinstance(c[k], str) and c[k].strip() for k in ("grade", "season", "note"))


def test_peak_names_are_unique():
    names = [p["name"] for p in CATALOG]
    assert len(names) == len(set(names))


def test_peak_ids_are_unique():
    ids = [p["id"] for p in CATALOG]
    assert len(ids) == len(set(ids))
