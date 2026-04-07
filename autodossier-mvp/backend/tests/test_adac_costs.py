"""Tests for adac_parser – heuristic cost segments and year adjustment."""

import pytest
from services.adac_parser import _heuristic, estimate_monthly_costs, get_costs


# ─── Heuristic Tier Assignment ────────────────────────────────────────────────

def test_heuristic_luxury_bmw():
    r = _heuristic("BMW", "3er", "2019")
    assert r["total_monthly"] >= 800
    assert r["source"] == "heuristic (ADAC-based estimate)"

def test_heuristic_luxury_mercedes():
    r = _heuristic("Mercedes-Benz", "C-Klasse", "2020")
    assert r["total_monthly"] >= 800

def test_heuristic_luxury_volvo():
    r = _heuristic("Volvo", "V60", "2020")
    assert r["total_monthly"] >= 800

def test_heuristic_mid_vw():
    r = _heuristic("Volkswagen", "Golf", "2021")
    assert r["fuel_monthly"] < 200
    assert r["total_monthly"] < 700

def test_heuristic_mid_toyota():
    r = _heuristic("Toyota", "Corolla", "2022")
    assert r["total_monthly"] < 700

def test_heuristic_economy_dacia():
    r = _heuristic("Dacia", "Sandero", "2021")
    assert r["total_monthly"] < 400

def test_heuristic_unknown_make():
    """Unknown make → default 'mid' tier, must not crash."""
    r = _heuristic("Trabant", "601", "2000")
    assert r["total_monthly"] > 0
    assert "source" in r

def test_heuristic_has_all_fields():
    r = _heuristic("BMW", "X5", "2020")
    required = {"fuel_monthly", "insurance_monthly", "tax_monthly",
                "maintenance_monthly", "depreciation_monthly", "total_monthly", "source"}
    assert required.issubset(r.keys())

def test_heuristic_total_is_sum():
    r = _heuristic("Volkswagen", "Golf", "2021")
    expected_total = round(
        r["fuel_monthly"] + r["insurance_monthly"] + r["tax_monthly"]
        + r["maintenance_monthly"] + r["depreciation_monthly"]
    )
    assert r["total_monthly"] == expected_total


# ─── Year Adjustment ──────────────────────────────────────────────────────────

def test_heuristic_old_car_lower_depreciation():
    """Cars older than 5 years get 40% lower depreciation."""
    new = _heuristic("BMW", "3er", "2023")
    old = _heuristic("BMW", "3er", "2015")
    assert old["depreciation_monthly"] < new["depreciation_monthly"]

def test_heuristic_old_car_higher_maintenance():
    """Older cars get 30% higher maintenance."""
    new = _heuristic("BMW", "3er", "2023")
    old = _heuristic("BMW", "3er", "2015")
    assert old["maintenance_monthly"] > new["maintenance_monthly"]

def test_heuristic_invalid_year_no_crash():
    r = _heuristic("BMW", "3er", "abc")
    assert r["total_monthly"] > 0


# ─── estimate_monthly_costs (public function) ─────────────────────────────────

def test_estimate_monthly_costs_returns_dict():
    r = estimate_monthly_costs("BMW", "3er", "2019")
    assert isinstance(r, dict)
    assert "total_monthly" in r

def test_estimate_monthly_costs_empty_make():
    r = estimate_monthly_costs("", "", "")
    assert isinstance(r, dict)
    assert "total_monthly" in r


# ─── get_costs uniform interface ─────────────────────────────────────────────

def test_get_costs_bmw_ctx(bmw_ctx):
    r = get_costs(bmw_ctx)
    assert r["total_monthly"] >= 800

def test_get_costs_volvo_ctx(volvo_ctx):
    r = get_costs(volvo_ctx)
    assert r["total_monthly"] >= 800

def test_get_costs_sparse_ctx(sparse_ctx):
    r = get_costs(sparse_ctx)
    assert isinstance(r, dict)
    assert "total_monthly" in r
