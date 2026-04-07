"""Shared pytest fixtures for AutoDossier backend tests."""

import pytest
from services.base import VehicleContext


@pytest.fixture
def bmw_ctx() -> VehicleContext:
    return {
        "vin":   "WBA3A5G59DNP26082",
        "make":  "BMW",
        "model": "3er",
        "year":  "2019",
        "fuel_type":    "Gasoline",
        "transmission": "Automatic",
        "confidence":   0.90,
        "source":       "NHTSA+WMI",
    }


@pytest.fixture
def volvo_ctx() -> VehicleContext:
    return {
        "vin":   "YV1ZWA8UDL2388160",
        "make":  "Volvo",
        "model": "V60",
        "year":  "2020",
        "fuel_type": "Diesel",
        "confidence": 0.80,
        "source": "NHTSA+WMI",
    }


@pytest.fixture
def sparse_ctx() -> VehicleContext:
    return {"vin": "00000000000000001", "confidence": 0.0, "source": "unknown"}


@pytest.fixture
def market_result_bmw() -> dict:
    return {
        "avg_price": 28_500,
        "min_price": 24_900,
        "max_price": 33_900,
        "listings": [
            {
                "title": "BMW 3er 320d",
                "price": 27_500,
                "mileage": "85000",
                "year": "2019",
                "source": "autoscout24.de",
                "url": None,
            }
        ],
    }


@pytest.fixture
def costs_luxury() -> dict:
    return {
        "fuel_monthly":          195,
        "insurance_monthly":     130,
        "tax_monthly":            55,
        "maintenance_monthly":   120,
        "depreciation_monthly":  400,
        "total_monthly":         900,
        "source": "heuristic (ADAC-based estimate)",
    }


@pytest.fixture
def market_empty() -> dict:
    return {"avg_price": None, "min_price": None, "max_price": None, "listings": []}


@pytest.fixture
def market_multi() -> dict:
    return {
        "avg_price": 22_000,
        "min_price": 19_000,
        "max_price": 26_000,
        "listings": [
            {"title": "VW Golf", "price": 21_000, "mileage": "55000",
             "year": "2021", "source": "mobile.de", "url": None},
            {"title": "VW Golf", "price": 23_000, "mileage": "40000",
             "year": "2021", "source": "autoscout24.de", "url": None},
        ],
    }


@pytest.fixture
def vin_data_bmw() -> dict:
    """VIN data as returned by decode_vin() (no 'vin' key)."""
    return {
        "make": "BMW", "model": "3er", "year": "2019",
        "fuel_type": "Gasoline", "transmission": "Automatic",
        "confidence": 0.90, "source": "NHTSA+WMI",
    }


@pytest.fixture
def vin_data_empty() -> dict:
    return {}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture
def mock_build_report(vin_data_bmw, market_result_bmw):
    """Patches routers.vin.build_report with a minimal valid report."""
    from unittest.mock import patch, AsyncMock
    report = {
        "vin":   "WBA3A5G59DNP26082",
        "tier":  "free",
        "vehicle":   vin_data_bmw,
        "specs":     {},
        "equipment": {},
        "costs":     {"total_monthly": 400},
        "market":    market_result_bmw,
        "score": {
            "wert": 75,
            "ampel": {
                "klasse": "gelb", "icon": "!", "label": "Faire Bewertung",
                "css": "ampel-yellow",
            },
            "breakdown": [
                {"dimension": "Preis",          "abzug": 5,  "max": 40, "text": "Fairer Preis"},
                {"dimension": "Betriebskosten", "abzug": 5,  "max": 25, "text": "Moderate Kosten"},
                {"dimension": "Fahrzeugalter",  "abzug": 10, "max": 20, "text": "Mittleres Alter"},
                {"dimension": "Kilometerstand", "abzug": 4,  "max": 15, "text": "Moderate Laufleistung"},
            ],
        },
        "warnings": [],
    }
    with patch("routers.vin.build_report", new_callable=AsyncMock, return_value=report) as m:
        yield m
