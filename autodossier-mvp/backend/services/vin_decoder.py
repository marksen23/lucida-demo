"""
VIN Decoder Service
Scrapes freevindecoder.eu with Playwright (fallback: driving-tests.org).
Returns a dict with make, model, year, engine, trim, fuel_type, transmission.
"""
import logging
import httpx
from typing import Any

logger = logging.getLogger(__name__)

# Dein persönlicher API Key von auto.dev
AUTO_DEV_API_KEY = "sk_ad_37BwESTyfmqFbxUCykRFbF7O"

async def decode_vin(vin: str) -> dict[str, Any]:
    """Return decoded VIN fields using auto.dev API."""
    url = f"https://api.auto.dev/vin/{vin}"
    headers = {
        "Authorization": f"Bearer {AUTO_DEV_API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        # Asynchrone Anfrage an die API
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, timeout=15.0)
            
            if response.status_code != 200:
                logger.error(f"auto.dev API Fehler: {response.status_code} - {response.text}")
                return {}
                
            data = response.json()
            
            # auto.dev strukturiert die Basis-Daten oft in einem 'vehicle' Objekt
            vehicle_info = data.get("vehicle", {})
            
            # Daten extrahieren und in das Format mappen, das deine anderen Scraper erwarten
            result = {
                "make": vehicle_info.get("make", ""),
                "model": vehicle_info.get("model", ""),
                "year": str(vehicle_info.get("year", "")),
                "engine": data.get("engine", ""),
                "transmission": data.get("transmission", ""),
                "body_style": data.get("body", ""),
                "trim": data.get("trim", ""),
                "fuel_type": data.get("fuelType", "")
            }
            
            # Leere Werte herausfiltern, damit wir saubere Daten haben
            clean_result = {k: v for k, v in result.items() if v}
            
            logger.info(f"Erfolgreich dekodiert: {clean_result.get('make')} {clean_result.get('model')}")
            return clean_result

    except Exception as exc:
        logger.error(f"VIN decode error (auto.dev): {exc}")
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
