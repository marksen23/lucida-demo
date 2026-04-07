"""
API endpoint tests – GET /api/vin/{vin}
=======================================
Uses FastAPI TestClient (synchronous).
All calls to build_report are mocked via the `mock_build_report` fixture
so no real network I/O occurs.
"""

import asyncio
from unittest.mock import patch, AsyncMock

import pytest
from fastapi import HTTPException


# ─── Helpers ──────────────────────────────────────────────────────────────────

VALID_VIN  = "WBA3A5G59DNP26082"   # BMW 3er, passes regex
VOLVO_VIN  = "YV1ZWA8UDL2388160"  # Volvo V60


# ─── 2a. Health endpoints ─────────────────────────────────────────────────────

def test_root_ok(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_root_allows_get(client):
    r = client.get("/")
    assert r.status_code != 405


def test_docs_available(client):
    r = client.get("/docs")
    assert r.status_code == 200


# ─── 2b. VIN validation ───────────────────────────────────────────────────────

def test_vin_too_short(client):
    r = client.get("/api/vin/WBA3A5G59DNP2608")   # 16 chars
    assert r.status_code == 422


def test_vin_too_long(client):
    r = client.get("/api/vin/WBA3A5G59DNP260822")  # 18 chars
    assert r.status_code == 422


def test_vin_with_I(client):
    r = client.get("/api/vin/WBA3A5I59DNP26082")   # forbidden 'I'
    assert r.status_code == 422


def test_vin_with_O(client):
    r = client.get("/api/vin/WBA3A5O59DNP26082")   # forbidden 'O'
    assert r.status_code == 422


def test_vin_with_Q(client):
    r = client.get("/api/vin/WBA3A5Q59DNP26082")   # forbidden 'Q'
    assert r.status_code == 422


def test_vin_with_space(client):
    # URL-encoded space → the path segment becomes 16-char or still triggers 422
    r = client.get("/api/vin/WBA3A5G59%20NP26082")
    assert r.status_code == 422


def test_vin_lowercase_accepted_after_normalization(client, mock_build_report):
    # _validate_vin does .upper() before the regex check, so lowercase passes
    r = client.get("/api/vin/wba3a5g59dnp26082")
    assert r.status_code == 200


def test_vin_exactly_17_but_invalid_char(client):
    r = client.get("/api/vin/WBA3A5I00DNP26082")   # 17 chars but has 'I'
    assert r.status_code == 422


def test_vin_valid_bmw(client, mock_build_report):
    r = client.get(f"/api/vin/{VALID_VIN}")
    assert r.status_code == 200


def test_vin_valid_volvo(client, mock_build_report):
    r = client.get(f"/api/vin/{VOLVO_VIN}")
    assert r.status_code == 200


def test_vin_uppercase_normalized(client, mock_build_report):
    # _validate_vin calls .upper() before regex check, so lowercase → 200
    r = client.get(f"/api/vin/{VALID_VIN.lower()}")
    assert r.status_code == 200


def test_vin_all_valid_alpha_chars(client, mock_build_report):
    # A VIN using only uppercase alphanumeric without I, O, Q (17 chars)
    # "WBA3A5G59DNP26082" is already such a VIN – just confirm it passes
    r = client.get(f"/api/vin/{VALID_VIN}")
    assert r.status_code == 200


# ─── 2c. Query parameter validation ──────────────────────────────────────────

def test_asking_price_too_low(client):
    r = client.get(f"/api/vin/{VALID_VIN}?asking_price=499")
    assert r.status_code == 422


def test_asking_price_too_high(client):
    r = client.get(f"/api/vin/{VALID_VIN}?asking_price=500001")
    assert r.status_code == 422


def test_asking_price_min_valid(client, mock_build_report):
    r = client.get(f"/api/vin/{VALID_VIN}?asking_price=500")
    assert r.status_code == 200


def test_asking_price_max_valid(client, mock_build_report):
    r = client.get(f"/api/vin/{VALID_VIN}?asking_price=500000")
    assert r.status_code == 200


def test_mileage_negative(client):
    r = client.get(f"/api/vin/{VALID_VIN}?mileage=-1")
    assert r.status_code == 422


def test_mileage_too_high(client):
    r = client.get(f"/api/vin/{VALID_VIN}?mileage=1000000")
    assert r.status_code == 422


def test_mileage_min_valid(client, mock_build_report):
    r = client.get(f"/api/vin/{VALID_VIN}?mileage=0")
    assert r.status_code == 200


def test_mileage_max_valid(client, mock_build_report):
    r = client.get(f"/api/vin/{VALID_VIN}?mileage=999999")
    assert r.status_code == 200


def test_both_params_valid(client, mock_build_report):
    r = client.get(f"/api/vin/{VALID_VIN}?asking_price=25000&mileage=80000")
    assert r.status_code == 200


# ─── 2d. Response structure ───────────────────────────────────────────────────

def test_response_has_required_keys(client, mock_build_report):
    r = client.get(f"/api/vin/{VALID_VIN}")
    body = r.json()
    for key in ("vin", "tier", "vehicle", "specs", "equipment", "costs", "market", "score", "warnings"):
        assert key in body, f"Missing key: {key}"


def test_score_has_wert_ampel_breakdown(client, mock_build_report):
    body = client.get(f"/api/vin/{VALID_VIN}").json()
    score = body["score"]
    assert "wert" in score
    assert "ampel" in score
    assert "breakdown" in score


def test_ampel_klasse_valid(client, mock_build_report):
    score = client.get(f"/api/vin/{VALID_VIN}").json()["score"]
    assert score["ampel"]["klasse"] in ("grün", "gelb", "rot")


def test_breakdown_has_4_dimensions(client, mock_build_report):
    score = client.get(f"/api/vin/{VALID_VIN}").json()["score"]
    assert len(score["breakdown"]) == 4


def test_tier_is_free_by_default(client, mock_build_report):
    body = client.get(f"/api/vin/{VALID_VIN}").json()
    assert body["tier"] == "free"


def test_warnings_is_list(client, mock_build_report):
    body = client.get(f"/api/vin/{VALID_VIN}").json()
    assert isinstance(body["warnings"], list)


def test_vin_echoed_in_response(client, mock_build_report):
    body = client.get(f"/api/vin/{VALID_VIN}").json()
    assert body["vin"] == VALID_VIN


# ─── 2e. Error responses ──────────────────────────────────────────────────────

def test_build_report_timeout_returns_504(client):
    with patch("routers.vin.build_report", new_callable=AsyncMock,
               side_effect=asyncio.TimeoutError()):
        r = client.get(f"/api/vin/{VALID_VIN}")
    assert r.status_code == 504


def test_build_report_internal_error_returns_500(client):
    with patch("routers.vin.build_report", new_callable=AsyncMock,
               side_effect=ValueError("unexpected")):
        r = client.get(f"/api/vin/{VALID_VIN}")
    assert r.status_code == 500


def test_http_exception_propagated(client):
    with patch("routers.vin.build_report", new_callable=AsyncMock,
               side_effect=HTTPException(status_code=418, detail="I'm a teapot")):
        r = client.get(f"/api/vin/{VALID_VIN}")
    assert r.status_code == 418


def test_504_detail_contains_timeout(client):
    with patch("routers.vin.build_report", new_callable=AsyncMock,
               side_effect=asyncio.TimeoutError()):
        r = client.get(f"/api/vin/{VALID_VIN}")
    assert "imeout" in r.json().get("detail", "") or "erneut" in r.json().get("detail", "")


def test_500_detail_contains_fehler(client):
    with patch("routers.vin.build_report", new_callable=AsyncMock,
               side_effect=RuntimeError("boom")):
        r = client.get(f"/api/vin/{VALID_VIN}")
    assert r.status_code == 500
    detail = r.json().get("detail", "")
    assert "Fehler" in detail or "fehler" in detail or "nternal" in detail


def test_vin_not_found_still_returns_200(client, mock_build_report):
    """Even if vehicle data is empty, the endpoint returns 200 (no 404)."""
    r = client.get(f"/api/vin/{VALID_VIN}")
    assert r.status_code == 200
