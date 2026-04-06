"""
VIN Decoder Service
===================
Strategy: fail-safe layered approach
  1. WMI table   – instant, always succeeds, gives make + year
  2. NHTSA vPIC  – free official API, enriches with model/trim/engine/etc.
  Result = merge(WMI, NHTSA); WMI guarantees baseline, NHTSA adds detail.
"""

import asyncio
import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_NHTSA_URL  = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevin/{}?format=json"
_NHTSA_EXT  = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevinextended/{}?format=json"


# ─── Public API ───────────────────────────────────────────────────────────────

async def decode_vin(vin: str) -> dict[str, Any]:
    """
    Always returns a dict. Guaranteed to contain at least 'make' and 'year'
    for any VIN whose WMI prefix is in the table.
    """
    # Step 1: instant WMI baseline (no network, no failure)
    base = _wmi_fallback(vin)

    # Step 2: try NHTSA – if it works, merge richer data on top
    try:
        nhtsa = await asyncio.wait_for(_decode_nhtsa(vin), timeout=9)
        if nhtsa.get("make"):
            # NHTSA wins for every field it has; WMI fills gaps
            merged = {**base, **{k: v for k, v in nhtsa.items() if v}}
            logger.info("VIN %s → NHTSA: %s %s %s",
                        vin, merged.get("make"), merged.get("model"), merged.get("year"))
            return merged
    except asyncio.TimeoutError:
        logger.warning("NHTSA timeout for VIN %s – using WMI fallback", vin)
    except Exception as exc:
        logger.warning("NHTSA error for VIN %s: %s – using WMI fallback", vin, exc)

    logger.info("VIN %s → WMI: %s %s", vin, base.get("make"), base.get("year"))
    return base


# ─── NHTSA vPIC API ───────────────────────────────────────────────────────────

async def _decode_nhtsa(vin: str) -> dict:
    """
    Call NHTSA extended VIN decoder.
    Returns {} if VIN is unknown or response is malformed.
    """
    url = _NHTSA_EXT.format(vin)
    async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
        resp = await client.get(url, headers={"Accept": "application/json"})
        resp.raise_for_status()
        payload = resp.json()

    _BAD = {"Not Applicable", "0", "null", "NULL", "None", ""}
    kv: dict[str, str] = {}
    for item in payload.get("Results", []):
        var = (item.get("Variable") or "").strip()
        val = (item.get("Value")    or "").strip()
        if var and val and val not in _BAD:
            kv[var] = val

    make  = kv.get("Make",  "")
    model = kv.get("Model", "")
    year  = kv.get("Model Year", "")

    if not make:
        return {}

    displ     = kv.get("Displacement (L)", "")
    cyl       = kv.get("Engine Number of Cylinders", "")
    kw        = kv.get("Engine Power (kW)", "")
    displ_str = f"{displ}L"  if displ else ""
    cyl_str   = f"{cyl}Zyl" if cyl   else ""
    engine_str = " ".join(filter(None, [displ_str, cyl_str]))

    return {
        "make":                make.title(),
        "model":               model,
        "year":                year,
        "trim":                kv.get("Trim", ""),
        "series":              kv.get("Series", ""),
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
        "plant_country":       kv.get("Plant Country", ""),
        "source":              "NHTSA vPIC",
    }


# ─── WMI Fallback (offline, no network) ──────────────────────────────────────

_WMI: dict[str, str] = {
    # Germany
    "WBA": "BMW",            "WBS": "BMW M",         "WBY": "BMW",
    "WVW": "Volkswagen",     "WV1": "Volkswagen",     "WV2": "Volkswagen",
    "WAU": "Audi",           "WUA": "Audi",           "WAP": "Audi",
    "WDD": "Mercedes-Benz",  "WDB": "Mercedes-Benz",  "WDC": "Mercedes-Benz",
    "WDF": "Mercedes-Benz",  "WMX": "Mercedes-Benz",  "WME": "Smart",
    "WP0": "Porsche",        "WP1": "Porsche",
    "W0L": "Opel",           "W0V": "Opel",
    "WMA": "MAN",
    # Other EU
    "VSS": "SEAT",           "VSE": "SEAT",
    "TMB": "Škoda",
    "TRU": "Audi",
    "ZFF": "Ferrari",        "ZHW": "Lamborghini",    "ZAR": "Alfa Romeo",
    "ZFA": "Fiat",           "ZCF": "Iveco",
    "VF1": "Renault",        "VF3": "Peugeot",        "VF7": "Citroën",
    "VNE": "Renault",        "VNK": "Toyota EU",
    "SAL": "Land Rover",     "SAJ": "Jaguar",         "SAR": "Rover",
    "SCF": "Aston Martin",   "SCA": "Rolls-Royce",    "SCC": "Lotus",
    "YV1": "Volvo",          "YV2": "Volvo",
    "XTA": "Lada",
    # North America
    "1HG": "Honda",          "1FT": "Ford",           "1G1": "Chevrolet",
    "1GC": "Chevrolet",      "1FA": "Ford",           "1J4": "Jeep",
    "2HG": "Honda",          "3HG": "Honda",
    # Japan / Korea
    "JHM": "Honda",          "JN1": "Nissan",
    "JT2": "Toyota",         "JT3": "Toyota",         "JT6": "Lexus",
    "JF1": "Subaru",         "JMB": "Mitsubishi",
    "KMH": "Hyundai",        "KNA": "Kia",            "KNM": "Kia",
    # China
    "LVS": "Ford CN",        "LFV": "Volkswagen CN",
}

# Model hints for EU VINs where we know the model from WMI + position 4-8
_WMI_MODEL_HINTS: dict[str, str] = {
    # BMW position 4 encodes series
    "WBA3": "3er",  "WBA4": "4er",  "WBA5": "5er",  "WBA6": "6er",
    "WBA7": "7er",  "WBA8": "8er",  "WBA1": "1er",  "WBA2": "2er",
    "WBY0": "i3",   "WBY1": "i8",   "WBY2": "iX",
    # VW position 4-5 encodes model
    "WVWZ": "Golf", "WVWA": "Golf", "WVWH": "Polo", "WVWJ": "Passat",
    "WVWP": "Touareg",
    # Audi
    "WAUA": "A4",  "WAUB": "A5",  "WAUC": "A6",  "WAUD": "A8",
    "WAU2": "Q5",  "WAU3": "Q7",  "WAUE": "A3",
    # Mercedes
    "WDD1": "C-Klasse", "WDD2": "E-Klasse", "WDD2": "S-Klasse",
    "WDC0": "GLC",      "WDC1": "GLE",
    # Porsche
    "WP0A": "911",  "WP0B": "Boxster", "WP0C": "Cayenne",
    "WP0Z": "Panamera", "WP0Y": "Macan",
}


def _wmi_fallback(vin: str) -> dict:
    wmi3 = vin[:3].upper()
    make = _WMI.get(wmi3)

    # Model hint from first 4-5 chars
    model_hint = (_WMI_MODEL_HINTS.get(vin[:4].upper())
                  or _WMI_MODEL_HINTS.get(vin[:5].upper())
                  or "")

    year_char = vin[9].upper() if len(vin) >= 10 else ""
    year = _year_from_char(year_char)

    result: dict = {"source": "WMI"}
    if make:
        result["make"] = make
    if model_hint:
        result["model"] = model_hint
    if year:
        result["year"] = str(year)
    return result


def _year_from_char(c: str) -> int | None:
    return {
        "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014,
        "F": 2015, "G": 2016, "H": 2017, "J": 2018, "K": 2019,
        "L": 2020, "M": 2021, "N": 2022, "P": 2023, "R": 2024,
        "S": 2025, "T": 2026, "V": 2027, "W": 2028, "X": 2029,
        "Y": 2030,
        "1": 2001, "2": 2002, "3": 2003, "4": 2004, "5": 2005,
        "6": 2006, "7": 2007, "8": 2008, "9": 2009,
    }.get(c.upper())
