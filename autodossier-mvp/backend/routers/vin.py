"""VIN Router – Phase 2

Thin orchestration layer: validates VIN, delegates to report_builder,
returns the complete structured report.

GET /api/vin/{vin}
  Optional query params:
    asking_price: int  – Angefragter Kaufpreis in EUR (für Score-Berechnung)
    mileage:      int  – Kilometerstand (für Score-Berechnung)
"""

import asyncio
import logging
import re

from fastapi import APIRouter, HTTPException, Path, Query

from services.report_builder import build_report

logger = logging.getLogger(__name__)
router = APIRouter()


def _validate_vin(vin: str) -> str:
    vin = vin.strip().upper()
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        raise HTTPException(
            status_code=422,
            detail="Ungültige VIN (17 alphanumerische Zeichen, keine I/O/Q)",
        )
    return vin


@router.get("/vin/{vin}", summary="Vollständiger Fahrzeug-Report aus VIN")
async def get_vehicle_report(
    vin: str = Path(
        ...,
        min_length=17,
        max_length=17,
        description="17-stellige Fahrzeug-Identifikationsnummer (VIN/FIN)",
    ),
    asking_price: int | None = Query(
        None,
        ge=500,
        le=500_000,
        description="Angefragter Kaufpreis in EUR (optional, verbessert Score-Genauigkeit)",
    ),
    mileage: int | None = Query(
        None,
        ge=0,
        le=999_999,
        description="Kilometerstand in km (optional, verbessert Score-Genauigkeit)",
    ),
):
    """Generiert einen vollständigen Fahrzeug-Report:

    - VIN-Dekodierung (Hersteller, Modell, Baujahr, Motor, …)
    - Technische Specs (PS, Verbrauch, CO₂, …)
    - Serienausstattung (Teoalida-Datenbank)
    - Monatliche Kosten (ADAC-Schätzwerte)
    - Marktpreise (mobile.de / autoscout24.de)
    - Koeffizient-Score (0–100) mit Breakdown

    Optional: `asking_price` und `mileage` für präzisere Score-Berechnung.
    """
    vin = _validate_vin(vin)
    logger.info("Report für VIN %s (asking=%s mileage=%s)", vin, asking_price, mileage)

    try:
        report = await asyncio.wait_for(
            build_report(vin, asking_price=asking_price, mileage=mileage),
            timeout=50,
        )
    except asyncio.TimeoutError:
        logger.error("Report-Timeout für VIN %s", vin)
        raise HTTPException(
            status_code=504,
            detail="Analyse-Timeout – bitte erneut versuchen",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Report-Fehler für VIN %s: %s", vin, exc)
        raise HTTPException(status_code=500, detail="Interner Fehler bei der Analyse")

    return report
