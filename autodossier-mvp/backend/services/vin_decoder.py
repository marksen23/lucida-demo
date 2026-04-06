"""
VIN Decoder Service
===================
Primary:  NHTSA vPIC API — official US government endpoint, 100 % free,
          no key, no sign-up, returns make/model/year/engine/trim/etc.
          https://vpic.nhtsa.dot.gov/api/

Fallback: WMI prefix table  (make + year from VIN characters, always works)
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{}?format=json"

# ─── Public API ───────────────────────────────────────────────────────────────

async def decode_vin(vin: str) -> dict[str, Any]:
    """Return decoded VIN fields. Always returns a dict (never raises)."""
    try:
        result = await asyncio.wait_for(_decode_nhtsa(vin), timeout=12)
        if result.get("make"):
            logger.info("NHTSA decoded VIN %s → %s %s %s",
                        vin, result.get("make"), result.get("model"), result.get("year"))
            return result
    except Exception as exc:
        logger.warning("NHTSA API failed for %s: %s", vin, exc)

    # Pure-local fallback – always succeeds for known WMI prefixes
    return _wmi_fallback(vin)


# ─── Source: NHTSA vPIC API ───────────────────────────────────────────────────

async def _decode_nhtsa(vin: str) -> dict:
    url = _NHTSA_URL.format(vin)
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        payload = resp.json()

    # Results is a flat list of {Variable, Value, ValueId, VariableId}
    kv: dict[str, str] = {}
    for item in payload.get("Results", []):
        var = (item.get("Variable") or "").strip()
        val = (item.get("Value")    or "").strip()
        if val and val not in ("Not Applicable", "0", "null", ""):
            kv[var] = val

    make  = kv.get("Make",  "")
    model = kv.get("Model", "")
    year  = kv.get("Model Year", "")

    if not make:
        return {}

    # Build a human-readable engine string
    displ = kv.get("Displacement (L)", "")
    cyl   = kv.get("Engine Number of Cylinders", "")
    kw    = kv.get("Engine Power (kW)", "")
    displ_str  = f"{displ}L"    if displ else ""
    cyl_str    = f"{cyl}Zyl"    if cyl   else ""
    engine_str = " ".join(filter(None, [displ_str, cyl_str]))

    return {
        "make":                make.title(),
        "model":               model,
        "year":                year,
        "trim":                kv.get("Trim", ""),
        "engine":              engine_str,
        "engine_displacement": displ_str,
        "cylinders":           cyl,
        "power_kw":            kw,
        "fuel_type":           kv.get("Fuel Type - Primary", ""),
        "transmission":        kv.get("Transmission Style", ""),
        "drive_type":          kv.get("Drive Type", ""),
        "body_style":          kv.get("Body Class", ""),
        "doors":               kv.get("Doors", ""),
        "manufacturer":        kv.get("Manufacturer Name", ""),
        "country":             kv.get("Plant Country", ""),
        "series":              kv.get("Series", ""),
        "source":              "NHTSA vPIC",
    }


# ─── WMI Fallback Table ───────────────────────────────────────────────────────

_WMI_TABLE = {
    # German
    "WBA": "BMW",  "WBS": "BMW M", "WBY": "BMW",
    "WVW": "Volkswagen", "WV1": "Volkswagen", "WV2": "Volkswagen",
    "WAU": "Audi", "WUA": "Audi",  "WAP": "Audi",
    "WDD": "Mercedes-Benz", "WDB": "Mercedes-Benz", "WDC": "Mercedes-Benz",
    "WDF": "Mercedes-Benz", "WMX": "Mercedes-Benz",
    "WP0": "Porsche", "WP1": "Porsche",
    "WMA": "MAN",
    "W0L": "Opel", "W0V": "Opel",
    # Other European
    "VSS": "SEAT", "VSE": "SEAT",
    "TMB": "Škoda",
    "TRU": "Audi Hungary",
    "ZFF": "Ferrari", "ZHW": "Lamborghini", "ZAR": "Alfa Romeo",
    "ZFA": "Fiat",    "ZCF": "Iveco",
    "VF1": "Renault", "VF3": "Peugeot", "VF7": "Citroën",
    "VNE": "Renault",
    "SAL": "Land Rover", "SAJ": "Jaguar", "SAR": "Rover",
    "SCF": "Aston Martin",
    "SCA": "Rolls-Royce", "SCC": "Lotus",
    # US
    "1HG": "Honda US", "1FT": "Ford",   "1G1": "Chevrolet",
    "1GC": "Chevrolet", "1FA": "Ford",  "1J4": "Jeep",
    "2HG": "Honda CA",  "3HG": "Honda MX",
    # Asian
    "JHM": "Honda",   "JN1": "Nissan",  "JT2": "Toyota", "JT3": "Toyota",
    "JF1": "Subaru",  "JMB": "Mitsubishi",
    "KMH": "Hyundai", "KNA": "Kia",     "KNM": "Kia",
    "NM0": "Ford ES",
}


def _wmi_fallback(vin: str) -> dict:
    wmi  = vin[:3].upper()
    make = _WMI_TABLE.get(wmi) or _WMI_TABLE.get(vin[:2].upper() + "0")
    year_char = vin[9].upper() if len(vin) >= 10 else ""
    year = _year_from_char(year_char)

    result: dict = {"source": "WMI fallback"}
    if make:
        result["make"] = make
    if year:
        result["year"] = str(year)
    return result


def _year_from_char(c: str) -> int | None:
    # NHTSA model year position encoding (position 10, 0-indexed 9)
    # Repeats in 30-year cycles (1980–2009, 2010–2039)
    mapping = {
        "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014,
        "F": 2015, "G": 2016, "H": 2017, "J": 2018, "K": 2019,
        "L": 2020, "M": 2021, "N": 2022, "P": 2023, "R": 2024,
        "S": 2025, "T": 2026, "V": 2027, "W": 2028, "X": 2029,
        "Y": 2030,
        "1": 2001, "2": 2002, "3": 2003, "4": 2004, "5": 2005,
        "6": 2006, "7": 2007, "8": 2008, "9": 2009,
    }
    return mapping.get(c.upper())
