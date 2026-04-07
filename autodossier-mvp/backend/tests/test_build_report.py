"""
Tests for report_builder.build_report() – the async orchestrator.
===================================================================
All network services are mocked so tests run offline.
Uses asyncio.run() (same pattern as existing test files, no pytest.ini needed).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.report_builder import build_report, _safe


# ─── Constants ────────────────────────────────────────────────────────────────

VALID_VIN = "WBA3A5G59DNP26082"

_DEFAULT_VIN_DATA = {
    "make": "BMW", "model": "3er", "year": "2019",
    "confidence": 0.90, "source": "NHTSA+WMI",
}
_DEFAULT_SPECS    = {"power_ps": 156, "source": "heuristic"}
_DEFAULT_EQUIP    = {"standard": ["ABS", "ESP"], "source": "teoalida-sample"}
_DEFAULT_COSTS    = {"total_monthly": 400, "source": "heuristic (ADAC-based estimate)"}
_DEFAULT_MARKET   = {
    "avg_price": 28_500,
    "listings": [{"title": "BMW", "price": 27_000, "mileage": "85000",
                  "year": "2019", "source": "autoscout24.de", "url": None}],
}


def _run(coro):
    """Run a coroutine without disturbing the thread's current event loop."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mock_all_services(
    vin_data=None,
    specs=None,
    equip=None,
    costs=None,
    market=None,
):
    """Context manager that patches all five services used by build_report."""
    vd = vin_data if vin_data is not None else _DEFAULT_VIN_DATA
    sp = specs   if specs   is not None else _DEFAULT_SPECS
    eq = equip   if equip   is not None else _DEFAULT_EQUIP
    co = costs   if costs   is not None else _DEFAULT_COSTS
    mk = market  if market  is not None else _DEFAULT_MARKET

    return (
        patch("services.report_builder.decode_vin",   new=AsyncMock(return_value=vd)),
        patch("services.report_builder.get_specs",    new=AsyncMock(return_value=sp)),
        patch("services.report_builder.get_equipment",new=AsyncMock(return_value=eq)),
        patch("services.report_builder.get_costs",    new=MagicMock(return_value=co)),
        patch("services.report_builder.get_market",   new=AsyncMock(return_value=mk)),
    )


# ─── 3d. _safe() helper (sync, no mocking needed) ─────────────────────────────

def test_safe_with_exception():
    assert _safe(ValueError("oops")) == {}

def test_safe_with_dict():
    assert _safe({"key": "val"}) == {"key": "val"}

def test_safe_with_none():
    assert _safe(None) == {}

def test_safe_with_empty_dict():
    assert _safe({}) == {}

def test_safe_with_base_exception():
    assert _safe(BaseException("fatal")) == {}


# ─── 3a. Happy path ───────────────────────────────────────────────────────────

def test_build_report_has_all_keys():
    """Report must contain all top-level keys."""
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN))
    for key in ("vin", "tier", "vehicle", "specs", "equipment", "costs", "market", "score", "warnings"):
        assert key in report, f"Missing: {key}"


def test_build_report_returns_vin():
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN))
    assert report["vin"] == VALID_VIN


def test_build_report_vehicle_equals_vin_data():
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN))
    assert report["vehicle"]["make"] == "BMW"
    assert report["vehicle"]["year"] == "2019"


def test_build_report_score_valid_range():
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN))
    assert 0 <= report["score"]["wert"] <= 100


def test_build_report_no_warnings_on_success():
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN))
    assert report["warnings"] == []


def test_build_report_tier_is_free():
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN))
    assert report["tier"] == "free"


def test_build_report_with_asking_price_cheap():
    """Cheap asking_price → Preis-Abzug = 0."""
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN, asking_price=20_000))
    breakdown = {b["dimension"]: b for b in report["score"]["breakdown"]}
    assert breakdown["Preis"]["abzug"] == 0


def test_build_report_with_asking_price_expensive():
    """Very expensive asking_price → Preis-Abzug = 40."""
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN, asking_price=45_000))
    breakdown = {b["dimension"]: b for b in report["score"]["breakdown"]}
    assert breakdown["Preis"]["abzug"] == 40


def test_build_report_with_low_mileage():
    """Low mileage → KM-Abzug = 0."""
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN, mileage=10_000))
    breakdown = {b["dimension"]: b for b in report["score"]["breakdown"]}
    assert breakdown["Kilometerstand"]["abzug"] == 0


def test_build_report_asking_price_none_uses_listing_proxy():
    """When asking_price=None, listing[0].price is used as proxy."""
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN, asking_price=None))
    # listing price = 27_000, avg = 28_500 → ratio ≈ 0.947 → ≤1.05 → ded=5
    breakdown = {b["dimension"]: b for b in report["score"]["breakdown"]}
    assert breakdown["Preis"]["abzug"] == 5


# ─── 3b. Service failures ─────────────────────────────────────────────────────

def test_specs_exception_adds_warning():
    p = _mock_all_services(specs=RuntimeError("net error"))
    with (
        patch("services.report_builder.decode_vin",    new=AsyncMock(return_value=_DEFAULT_VIN_DATA)),
        patch("services.report_builder.get_specs",     new=AsyncMock(side_effect=RuntimeError("net error"))),
        patch("services.report_builder.get_equipment", new=AsyncMock(return_value=_DEFAULT_EQUIP)),
        patch("services.report_builder.get_costs",     new=MagicMock(return_value=_DEFAULT_COSTS)),
        patch("services.report_builder.get_market",    new=AsyncMock(return_value=_DEFAULT_MARKET)),
    ):
        report = _run(build_report(VALID_VIN))
    assert report["specs"] == {}
    assert any("specs" in w.lower() for w in report["warnings"])


def test_market_exception_adds_warning():
    with (
        patch("services.report_builder.decode_vin",    new=AsyncMock(return_value=_DEFAULT_VIN_DATA)),
        patch("services.report_builder.get_specs",     new=AsyncMock(return_value=_DEFAULT_SPECS)),
        patch("services.report_builder.get_equipment", new=AsyncMock(return_value=_DEFAULT_EQUIP)),
        patch("services.report_builder.get_costs",     new=MagicMock(return_value=_DEFAULT_COSTS)),
        patch("services.report_builder.get_market",    new=AsyncMock(side_effect=ConnectionError("refused"))),
    ):
        report = _run(build_report(VALID_VIN))
    assert report["market"] == {}
    assert any("market" in w.lower() for w in report["warnings"])


def test_equipment_exception_adds_warning():
    with (
        patch("services.report_builder.decode_vin",    new=AsyncMock(return_value=_DEFAULT_VIN_DATA)),
        patch("services.report_builder.get_specs",     new=AsyncMock(return_value=_DEFAULT_SPECS)),
        patch("services.report_builder.get_equipment", new=AsyncMock(side_effect=KeyError("db"))),
        patch("services.report_builder.get_costs",     new=MagicMock(return_value=_DEFAULT_COSTS)),
        patch("services.report_builder.get_market",    new=AsyncMock(return_value=_DEFAULT_MARKET)),
    ):
        report = _run(build_report(VALID_VIN))
    assert report["equipment"] == {}
    assert any("equipment" in w.lower() for w in report["warnings"])


def test_vin_decoder_exception_adds_warning():
    with (
        patch("services.report_builder.decode_vin",    new=AsyncMock(side_effect=ValueError("bad vin"))),
        patch("services.report_builder.get_specs",     new=AsyncMock(return_value=_DEFAULT_SPECS)),
        patch("services.report_builder.get_equipment", new=AsyncMock(return_value=_DEFAULT_EQUIP)),
        patch("services.report_builder.get_costs",     new=MagicMock(return_value=_DEFAULT_COSTS)),
        patch("services.report_builder.get_market",    new=AsyncMock(return_value=_DEFAULT_MARKET)),
    ):
        report = _run(build_report(VALID_VIN))
    assert report["vehicle"] == {}
    assert any("VIN" in w or "vin" in w.lower() for w in report["warnings"])


def test_vin_decoder_timeout_adds_warning():
    with (
        patch("services.report_builder.decode_vin",    new=AsyncMock(side_effect=asyncio.TimeoutError())),
        patch("services.report_builder.get_specs",     new=AsyncMock(return_value=_DEFAULT_SPECS)),
        patch("services.report_builder.get_equipment", new=AsyncMock(return_value=_DEFAULT_EQUIP)),
        patch("services.report_builder.get_costs",     new=MagicMock(return_value=_DEFAULT_COSTS)),
        patch("services.report_builder.get_market",    new=AsyncMock(return_value=_DEFAULT_MARKET)),
    ):
        report = _run(build_report(VALID_VIN))
    assert report["vehicle"] == {}
    assert len(report["warnings"]) >= 1


def test_all_services_fail_report_still_builds():
    """Even when every service fails, build_report() returns a valid dict."""
    with (
        patch("services.report_builder.decode_vin",    new=AsyncMock(side_effect=Exception("a"))),
        patch("services.report_builder.get_specs",     new=AsyncMock(side_effect=Exception("b"))),
        patch("services.report_builder.get_equipment", new=AsyncMock(side_effect=Exception("c"))),
        patch("services.report_builder.get_costs",     new=MagicMock(side_effect=Exception("d"))),
        patch("services.report_builder.get_market",    new=AsyncMock(side_effect=Exception("e"))),
    ):
        report = _run(build_report(VALID_VIN))
    assert report["vin"] == VALID_VIN
    assert report["specs"]     == {}
    assert report["equipment"] == {}
    assert report["market"]    == {}
    # VIN-decoder failure → 1 warning; 4 gather-level failures → 4 warnings
    assert len(report["warnings"]) >= 4


def test_multiple_service_failures_each_add_warning():
    """Each failing service produces its own warning entry."""
    with (
        patch("services.report_builder.decode_vin",    new=AsyncMock(return_value=_DEFAULT_VIN_DATA)),
        patch("services.report_builder.get_specs",     new=AsyncMock(side_effect=RuntimeError("x"))),
        patch("services.report_builder.get_equipment", new=AsyncMock(side_effect=RuntimeError("y"))),
        patch("services.report_builder.get_costs",     new=MagicMock(return_value=_DEFAULT_COSTS)),
        patch("services.report_builder.get_market",    new=AsyncMock(return_value=_DEFAULT_MARKET)),
    ):
        report = _run(build_report(VALID_VIN))
    assert len(report["warnings"]) == 2


# ─── 3c. Premium hook ─────────────────────────────────────────────────────────

def test_premium_false_extra_services_not_called():
    mock_svc = AsyncMock(return_value={"extra": "data"})
    mock_svc.__name__ = "mock_svc"
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        _run(build_report(VALID_VIN, premium=False, extra_services=[mock_svc]))
    mock_svc.assert_not_awaited()


def test_premium_true_extra_services_called():
    mock_svc = AsyncMock(return_value={"extra": "data"})
    mock_svc.__name__ = "mock_svc"
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        _run(build_report(VALID_VIN, premium=True, extra_services=[mock_svc]))
    mock_svc.assert_awaited_once()


def test_premium_tier_set_when_premium_true():
    mock_svc = AsyncMock(return_value={"extra": "data"})
    mock_svc.__name__ = "mock_svc"
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN, premium=True, extra_services=[mock_svc]))
    assert report["tier"] == "premium"


def test_premium_service_failure_adds_warning():
    mock_svc = AsyncMock(side_effect=RuntimeError("premium failure"))
    mock_svc.__name__ = "mock_svc"
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN, premium=True, extra_services=[mock_svc]))
    assert any("premium" in w.lower() for w in report["warnings"])


def test_premium_result_merged_into_report():
    mock_svc = AsyncMock(return_value={"history": ["no accidents"]})
    mock_svc.__name__ = "history_service"
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN, premium=True, extra_services=[mock_svc]))
    assert "history_service" in report
    assert report["history_service"] == {"history": ["no accidents"]}


def test_premium_none_extra_services_tier_stays_free():
    p = _mock_all_services()
    with p[0], p[1], p[2], p[3], p[4]:
        report = _run(build_report(VALID_VIN, premium=True, extra_services=None))
    assert report["tier"] == "free"
