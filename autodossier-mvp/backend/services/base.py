"""
Shared base types for all AutoDossier services.

Every service function receives a VehicleContext (populated by vin_decoder)
and returns a plain dict.  No ABC / Protocol overhead — just TypedDict.
"""

from typing import Any, TypedDict


class VehicleContext(TypedDict, total=False):
    """Accumulated vehicle data passed through the service pipeline.

    Populated progressively:
      - ``vin`` is always set (required)
      - All other keys are optional; services must guard with .get()
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    vin: str                  # 17-char VIN (always set)
    make: str                 # e.g. "BMW", "Volkswagen"
    model: str                # e.g. "3er", "Golf", "XC40"
    year: str                 # 4-digit string, e.g. "2020"
    trim: str                 # e.g. "Sport", "Comfortline"

    # ── Powertrain ────────────────────────────────────────────────────────────
    engine: str               # e.g. "2.00L 4Zyl"
    engine_displacement: str  # e.g. "2.00L"
    cylinders: str            # e.g. "4"
    fuel_type: str            # e.g. "Gasoline", "Diesel", "Electric"
    transmission: str         # e.g. "Automatic"
    drive_type: str           # e.g. "AWD", "FWD"

    # ── Body ──────────────────────────────────────────────────────────────────
    body_style: str           # e.g. "Sedan/Saloon", "SUV", "Estate"

    # ── Origin ────────────────────────────────────────────────────────────────
    country: str              # Assembly-plant country (from NHTSA)
    origin_country: str       # Manufacturer HQ country (from VIN prefix)
    manufacturer: str         # Full manufacturer name, e.g. "VOLVO CAR CORPORATION"

    # ── Metadata ──────────────────────────────────────────────────────────────
    confidence: float         # 0.0–1.0 decode confidence
    source: str               # "NHTSA+WMI" | "freevindecoder.eu" | …


# Convenience alias used by report_builder
VehicleData = VehicleContext


def ctx_from_vin_data(vin: str, vin_data: dict[str, Any]) -> VehicleContext:
    """Build a VehicleContext from the raw vin_decoder result."""
    ctx: VehicleContext = {"vin": vin}
    for key in VehicleContext.__annotations__:
        if key != "vin" and key in vin_data:
            ctx[key] = vin_data[key]  # type: ignore[literal-required]
    return ctx
