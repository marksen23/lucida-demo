"""Tests for report_builder – score algorithm (unit tests, no network)."""

import pytest
from services.report_builder import (
    _score_price,
    _score_costs,
    _score_age,
    _score_mileage,
    _compute_score,
)
from services.base import VehicleContext


# ─── _score_price ─────────────────────────────────────────────────────────────

def test_score_price_great_deal():
    ded, text = _score_price(20_000, {"avg_price": 25_000})
    assert ded == 0
    assert "90%" in text or "Sehr guter" in text

def test_score_price_fair():
    ded, text = _score_price(25_000, {"avg_price": 25_000})
    assert ded == 5
    assert "Fairer" in text

def test_score_price_slightly_over():
    ded, text = _score_price(28_000, {"avg_price": 25_000})  # ratio 1.12
    assert ded == 15

def test_score_price_over():
    ded, text = _score_price(31_000, {"avg_price": 25_000})  # ratio 1.24
    assert ded == 28

def test_score_price_strongly_over():
    ded, text = _score_price(40_000, {"avg_price": 25_000})  # ratio 1.6
    assert ded == 40

def test_score_price_no_data():
    ded, text = _score_price(None, {"avg_price": 25_000})
    assert ded == 0
    assert "verfügbar" in text.lower() or "keine" in text.lower()

def test_score_price_no_market():
    ded, text = _score_price(25_000, {})
    assert ded == 0


# ─── _score_costs ─────────────────────────────────────────────────────────────

def test_score_costs_low():
    ded, _ = _score_costs({"total_monthly": 250})
    assert ded == 0

def test_score_costs_moderate():
    ded, _ = _score_costs({"total_monthly": 400})
    assert ded == 5

def test_score_costs_elevated():
    ded, _ = _score_costs({"total_monthly": 550})
    assert ded == 12

def test_score_costs_high():
    ded, _ = _score_costs({"total_monthly": 750})
    assert ded == 20

def test_score_costs_very_high():
    ded, _ = _score_costs({"total_monthly": 950})
    assert ded == 25

def test_score_costs_no_data():
    ded, text = _score_costs({})
    assert ded == 0
    assert "keine" in text.lower() or "verfügbar" in text.lower()


# ─── _score_age ───────────────────────────────────────────────────────────────

def test_score_age_new():
    ded, text = _score_age("2025")
    assert ded == 0
    assert "Neufahrzeug" in text or "Jahr" in text

def test_score_age_young():
    ded, _ = _score_age("2022")
    assert ded == 5

def test_score_age_middle():
    ded, _ = _score_age("2018")
    assert ded == 10

def test_score_age_old():
    ded, _ = _score_age("2013")
    assert ded == 16

def test_score_age_very_old():
    ded, _ = _score_age("2005")
    assert ded == 20

def test_score_age_unknown():
    ded, text = _score_age("")
    assert ded == 0
    assert "unbekannt" in text.lower()

def test_score_age_invalid():
    ded, text = _score_age("not-a-year")
    assert ded == 0


# ─── _score_mileage ───────────────────────────────────────────────────────────

def test_score_mileage_low():
    ded, _ = _score_mileage(20_000)
    assert ded == 0

def test_score_mileage_moderate():
    ded, _ = _score_mileage(60_000)
    assert ded == 4

def test_score_mileage_high():
    ded, _ = _score_mileage(110_000)
    assert ded == 9

def test_score_mileage_very_high():
    ded, _ = _score_mileage(170_000)
    assert ded == 13

def test_score_mileage_extreme():
    ded, _ = _score_mileage(250_000)
    assert ded == 15

def test_score_mileage_none():
    ded, text = _score_mileage(None)
    assert ded == 0
    assert "unbekannt" in text.lower()

def test_score_mileage_negative_clamped():
    ded, _ = _score_mileage(-100)
    assert ded == 0


# ─── _compute_score integration ───────────────────────────────────────────────

def test_compute_score_good_deal(bmw_ctx, market_result_bmw):
    costs = {"total_monthly": 400}  # moderate – not luxury
    score = _compute_score(bmw_ctx, costs, market_result_bmw, asking_price=24_000, mileage=50_000)
    assert 0 <= score["wert"] <= 100
    assert score["ampel"]["klasse"] in ("grün", "gelb", "rot")
    assert len(score["breakdown"]) == 4

def test_compute_score_luxury(bmw_ctx, market_result_bmw, costs_luxury):
    score = _compute_score(bmw_ctx, costs_luxury, market_result_bmw, asking_price=35_000, mileage=90_000)
    # Overpriced (35k vs avg 28.5k), high costs → expect penalty
    assert score["wert"] < 80

def test_compute_score_green_threshold(bmw_ctx, market_result_bmw):
    """Cheap price, low costs → should be grün."""
    costs = {"total_monthly": 200}
    score = _compute_score(bmw_ctx, costs, market_result_bmw, asking_price=20_000, mileage=10_000)
    assert score["wert"] >= 80
    assert score["ampel"]["klasse"] == "grün"

def test_compute_score_red_threshold(bmw_ctx, market_result_bmw):
    """Expensive, high costs, high mileage → should be rot."""
    costs = {"total_monthly": 1_000}
    score = _compute_score(bmw_ctx, costs, market_result_bmw, asking_price=50_000, mileage=220_000)
    assert score["wert"] < 55
    assert score["ampel"]["klasse"] == "rot"

def test_compute_score_no_params(sparse_ctx):
    """Score with minimal context – must not crash, returns valid structure."""
    score = _compute_score(sparse_ctx, {}, {}, asking_price=None, mileage=None)
    assert "wert" in score
    assert "ampel" in score
    assert "breakdown" in score
    assert 0 <= score["wert"] <= 100

def test_compute_score_proxy_listing(bmw_ctx, market_result_bmw):
    """When asking_price=None, first listing price is used as proxy."""
    costs = {"total_monthly": 400}
    score = _compute_score(bmw_ctx, costs, market_result_bmw, asking_price=None, mileage=None)
    # listing price = 27_500, avg = 28_500 → ratio ~0.965 → fair price (ded=5)
    breakdown = {b["dimension"]: b for b in score["breakdown"]}
    assert breakdown["Preis"]["abzug"] == 5

def test_compute_score_max_possible():
    """Theoretically best case: new, cheap, low km, low costs."""
    ctx: VehicleContext = {"vin": "X" * 17, "year": "2025"}
    costs = {"total_monthly": 100}
    market = {"avg_price": 30_000, "listings": [{"price": 25_000, "mileage": "5000"}]}
    score = _compute_score(ctx, costs, market, asking_price=25_000, mileage=5_000)
    assert score["wert"] == 100  # 0 deductions across all 4 dimensions

def test_compute_score_max_deduction():
    """Worst case: very old, overpriced, extreme mileage, very high costs."""
    ctx: VehicleContext = {"vin": "X" * 17, "year": "2000"}
    costs = {"total_monthly": 1_500}
    market = {"avg_price": 10_000, "listings": [{"price": 20_000, "mileage": "300000"}]}
    score = _compute_score(ctx, costs, market, asking_price=20_000, mileage=300_000)
    assert score["wert"] == 0
    assert score["ampel"]["klasse"] == "rot"
