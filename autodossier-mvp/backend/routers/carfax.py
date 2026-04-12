"""
Carfax / AutoCheck Router
=========================
GET  /api/carfax/records/{vin}           – Anzahl verfügbarer Historie-Einträge
POST /api/carfax/report/{vin}/{provider} – Kostenpflichtigen Report abrufen

Ohne konfigurierte API-Keys liefert der Records-Endpoint immer {carfax:0, autocheck:0}.
Sobald CARFAX_API_KEY gesetzt ist, kann hier die echte Integration ergänzt werden.
"""

import logging
import os

from fastapi import APIRouter, HTTPException, Path

logger = logging.getLogger(__name__)
router = APIRouter(tags=["carfax"])

_CARFAX_API_KEY = os.environ.get("CARFAX_API_KEY", "")


@router.get("/carfax/records/{vin}", summary="Carfax/AutoCheck Eintragsanzahl prüfen")
async def get_carfax_records(
    vin: str = Path(..., min_length=17, max_length=17),
):
    """Gibt zurück, wie viele Einträge für diese VIN in Carfax und AutoCheck vorliegen.

    Gibt 0 zurück solange kein API-Key konfiguriert ist (CARFAX_API_KEY env var).
    """
    vin = vin.upper().strip()

    if not _CARFAX_API_KEY:
        logger.debug("Carfax: kein API-Key – Fallback 0 für VIN %s", vin)
        return {"carfax": 0, "autocheck": 0}

    # TODO: echte Carfax-API-Integration wenn Key vorhanden
    # Beispiel-Struktur der Antwort:
    # resp = await httpx.AsyncClient().get(
    #     "https://api.carfax.com/v1/records",
    #     params={"vin": vin},
    #     headers={"Authorization": f"Bearer {_CARFAX_API_KEY}"},
    # )
    # data = resp.json()
    # return {"carfax": data.get("count", 0), "autocheck": 0}

    return {"carfax": 0, "autocheck": 0}


@router.post("/carfax/report/{vin}/{provider}", summary="Fahrzeughistorie-Report abrufen")
async def buy_carfax_report(
    vin: str = Path(..., min_length=17, max_length=17),
    provider: str = Path(..., description="'carfax' oder 'autocheck'"),
):
    """Ruft einen vollständigen kostenpflichtigen Fahrzeughistorie-Report ab.

    Erfordert CARFAX_API_KEY Umgebungsvariable.
    Gibt einen Link zum fertigen Report zurück.
    """
    vin = vin.upper().strip()

    if not _CARFAX_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Carfax-API nicht konfiguriert – bitte CARFAX_API_KEY setzen.",
        )

    if provider not in ("carfax", "autocheck"):
        raise HTTPException(status_code=400, detail="Unbekannter Provider (carfax / autocheck)")

    # TODO: echte Carfax-API-Integration
    # resp = await httpx.AsyncClient().post(
    #     "https://api.carfax.com/v1/reports",
    #     json={"vin": vin},
    #     headers={"Authorization": f"Bearer {_CARFAX_API_KEY}"},
    # )
    # return {"link": resp.json()["report_url"]}

    raise HTTPException(status_code=501, detail="Carfax-Report-API noch nicht implementiert.")
