"""
VIN Decoder Service
Nutzt die auto.dev API zur Entschlüsselung.
Gibt ein Dict mit make, model, year, engine, trim, fuel_type, transmission zurück.
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