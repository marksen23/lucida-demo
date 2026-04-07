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
