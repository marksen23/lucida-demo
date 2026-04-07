"""Tests for equipment_service – key lookup, aliases, model coverage."""

import pytest
import asyncio
from services.equipment_service import get_equipment, _lookup_key, _load_db


# ─── _lookup_key ──────────────────────────────────────────────────────────────

def test_lookup_key_exact_bmw_3er():
    key = _lookup_key("BMW", "3er")
    assert key == "bmw|3er"

def test_lookup_key_alias_3series():
    key = _lookup_key("BMW", "3 Series")
    assert key == "bmw|3er"

def test_lookup_key_alias_c_class():
    key = _lookup_key("Mercedes-Benz", "C-Class")
    assert key == "mercedes-benz|c-klasse"

def test_lookup_key_alias_golf_gti():
    key = _lookup_key("Volkswagen", "Golf GTI")
    assert key == "volkswagen|golf"

def test_lookup_key_make_alias_vw():
    key = _lookup_key("VW", "Golf")
    assert key == "volkswagen|golf"

def test_lookup_key_make_alias_mercedes():
    key = _lookup_key("Mercedes", "E-Klasse")
    assert key is not None
    assert "mercedes" in key

def test_lookup_key_volvo_v60():
    key = _lookup_key("Volvo", "V60")
    assert key == "volvo|v60"

def test_lookup_key_unknown_returns_none():
    key = _lookup_key("Trabant", "601")
    assert key is None

def test_lookup_key_empty_make():
    key = _lookup_key("", "Golf")
    assert key is None


# ─── _load_db ─────────────────────────────────────────────────────────────────

def test_load_db_not_empty():
    db = _load_db()
    assert len(db) >= 20

def test_load_db_bmw_3er_present():
    db = _load_db()
    assert "bmw|3er" in db

def test_load_db_volvo_v60_present():
    db = _load_db()
    assert "volvo|v60" in db

def test_load_db_volkswagen_golf_present():
    db = _load_db()
    assert "volkswagen|golf" in db

def test_load_db_structure_fields():
    db = _load_db()
    entry = db.get("bmw|3er", {})
    assert "serienausstattung" in entry
    assert isinstance(entry["serienausstattung"], list)
    assert len(entry["serienausstattung"]) >= 3


# ─── get_equipment (async) ────────────────────────────────────────────────────

def test_get_equipment_bmw(bmw_ctx):
    result = asyncio.get_event_loop().run_until_complete(get_equipment(bmw_ctx))
    assert result.get("available") is True
    assert len(result.get("serienausstattung", [])) >= 3
    assert result.get("source") == "Teoalida-Datenbank (Musterdaten)"

def test_get_equipment_volvo(volvo_ctx):
    result = asyncio.get_event_loop().run_until_complete(get_equipment(volvo_ctx))
    assert result.get("available") is True
    assert "V60" in result.get("matched_model", "").upper() or "v60" in result.get("matched_model", "")

def test_get_equipment_sparse_ctx(sparse_ctx):
    result = asyncio.get_event_loop().run_until_complete(get_equipment(sparse_ctx))
    assert result.get("available") is False

def test_get_equipment_returns_sicherheit(bmw_ctx):
    result = asyncio.get_event_loop().run_until_complete(get_equipment(bmw_ctx))
    assert "sicherheit" in result
    assert isinstance(result["sicherheit"], list)

def test_get_equipment_returns_optional(bmw_ctx):
    result = asyncio.get_event_loop().run_until_complete(get_equipment(bmw_ctx))
    assert "typisch_optional" in result
    assert isinstance(result["typisch_optional"], list)

def test_get_equipment_unknown_make():
    ctx = {"vin": "00000000000000001", "make": "Lada", "model": "Niva", "year": "2000"}
    result = asyncio.get_event_loop().run_until_complete(get_equipment(ctx))
    assert result.get("available") is False


# ─── Model Coverage (top-30 check) ───────────────────────────────────────────

@pytest.mark.parametrize("make,model", [
    ("BMW",          "3er"),
    ("BMW",          "5er"),
    ("BMW",          "X3"),
    ("Volkswagen",   "Golf"),
    ("Volkswagen",   "Tiguan"),
    ("Audi",         "A3"),
    ("Audi",         "A4"),
    ("Mercedes-Benz","C-Klasse"),
    ("Mercedes-Benz","E-Klasse"),
    ("Volvo",        "V60"),
    ("Volvo",        "XC60"),
    ("Toyota",       "Corolla"),
    ("Hyundai",      "Tucson"),
    ("Skoda",        "Octavia"),
])
def test_model_coverage(make, model):
    """Every listed model must resolve and return data."""
    ctx = {"vin": "00000000000000001", "make": make, "model": model, "year": "2022"}
    result = asyncio.get_event_loop().run_until_complete(get_equipment(ctx))
    assert result.get("available") is True, f"No equipment data for {make} {model}"
    assert len(result.get("serienausstattung", [])) >= 1
