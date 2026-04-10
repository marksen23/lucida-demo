"""
VIN Decoder Service
Scrapes freevindecoder.eu with Playwright (fallback: driving-tests.org).
Returns a dict with make, model, year, engine, trim, fuel_type, transmission.
"""
import httpx
import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

async def decode_vin(vin: str) -> dict:
    url = f"https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues/{vin}?format=json"
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            data = response.json()
            
            results = data.get("Results", [])[0]
            
            make = results.get("Make", "").title()
            model = results.get("Model", "")
            year = results.get("ModelYear", "")
            
            if make:
                return {
                    "make": make,
                    "model": model,
                    "year": year,
                    "engine": results.get("DisplacementL", "") + "L",
                    "fuel_type": results.get("FuelTypePrimary", ""),
                    "body_style": results.get("BodyClass", "")
                }
            return {}
    except Exception as e:
        logger.error(f"NHTSA API Error: {e}")
        return {}


# ─── WMI Fallback Table ───────────────────────────────────────────────────────
# Covers the most common European & global WMI codes

_WMI_TABLE = {
    "WBA": "BMW", "WBS": "BMW M", "WBY": "BMW",
    "WVW": "Volkswagen", "WV1": "Volkswagen", "WV2": "Volkswagen",
    "WAU": "Audi", "WUA": "Audi",
    "WDD": "Mercedes-Benz", "WDB": "Mercedes-Benz", "WDC": "Mercedes-Benz",
    "WP0": "Porsche", "WP1": "Porsche",
    "VSS": "SEAT", "VSE": "SEAT",
    "TMB": "Škoda",
    "ZFF": "Ferrari", "ZHW": "Lamborghini", "ZAR": "Alfa Romeo",
    "VF1": "Renault", "VF3": "Peugeot", "VF7": "Citroën",
    "SAL": "Land Rover", "SAJ": "Jaguar",
    "1HG": "Honda", "1FT": "Ford", "1G1": "Chevrolet",
    "JHM": "Honda", "JN1": "Nissan", "JT2": "Toyota",
    "KMH": "Hyundai", "KNA": "Kia",
}

def _wmi_fallback(vin: str) -> dict:
    wmi = vin[:3].upper()
    make = _WMI_TABLE.get(wmi)
    # Year character: position 9 (0-indexed)
    year_char = vin[9].upper() if len(vin) >= 10 else ""
    year = _year_from_char(year_char)
    result = {}
    if make:
        result["make"] = make
    if year:
        result["year"] = str(year)
    return result


def _year_from_char(c: str) -> int | None:
    # NHTSA model year encoding
    mapping = {
        "A": 2010, "B": 2011, "C": 2012, "D": 2013, "E": 2014,
        "F": 2015, "G": 2016, "H": 2017, "J": 2018, "K": 2019,
        "L": 2020, "M": 2021, "N": 2022, "P": 2023, "R": 2024,
        "S": 2025, "1": 2001, "2": 2002, "3": 2003, "4": 2004,
        "5": 2005, "6": 2006, "7": 2007, "8": 2008, "9": 2009,
    }
    return mapping.get(c.upper())
