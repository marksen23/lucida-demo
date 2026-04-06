"""VIN router – orchestrates all data sources and returns the merged report."""

import asyncio
import logging
from fastapi import APIRouter, HTTPException, Path

from services.vin_decoder import decode_vin
from services.specs_scraper import scrape_specs
from services.market_scraper import scrape_market
from services.adac_parser import estimate_monthly_costs

logger = logging.getLogger(__name__)
router = APIRouter()


def _validate_vin(vin: str) -> str:
    import re
    vin = vin.strip().upper()
    if not re.fullmatch(r"[A-HJ-NPR-Z0-9]{17}", vin):
        raise HTTPException(status_code=422, detail="Ungültige VIN (17 alphanumerische Zeichen erforderlich)")
    return vin


@router.get("/vin/{vin}", summary="Fahrzeug-Report aus VIN generieren")
async def get_vehicle_report(
    vin: str = Path(..., min_length=17, max_length=17, description="17-stellige Fahrzeug-ID"),
):
    vin = _validate_vin(vin)
    logger.info("Report angefordert für VIN: %s", vin)

    # Step 1: VIN decode (fast, blocking OK)
    try:
        vin_data = await asyncio.wait_for(decode_vin(vin), timeout=15)
    except asyncio.TimeoutError:
        vin_data = {}
    except Exception as exc:
        logger.warning("VIN decode failed: %s", exc)
        vin_data = {}

    make  = vin_data.get("make", "")
    model = vin_data.get("model", "")
    year  = vin_data.get("year", "")

    # If VIN decode returned nothing at all, log a warning but continue –
    # market scraper will use whatever we have (even empty make → falls back to VIN search)
    if not make:
        logger.warning("VIN %s: no make resolved – report will be sparse", vin)

    # Steps 2–4: run in parallel (specs + market + costs)
    specs_task  = asyncio.create_task(scrape_specs(make, model, year))
    market_task = asyncio.create_task(scrape_market(make, model, year))
    costs_task  = asyncio.create_task(
        asyncio.to_thread(estimate_monthly_costs, make, model, year)
    )

    specs_result, market_result, costs_result = await asyncio.gather(
        specs_task, market_task, costs_task, return_exceptions=True
    )

    if isinstance(specs_result, Exception):
        logger.warning("Specs scraper error: %s", specs_result)
        specs_result = {}
    if isinstance(market_result, Exception):
        logger.warning("Market scraper error: %s", market_result)
        market_result = {}
    if isinstance(costs_result, Exception):
        logger.warning("ADAC parser error: %s", costs_result)
        costs_result = {}

    return {
        "vin": vin,
        "vin_data": vin_data,
        "specs": specs_result,
        "costs": costs_result,
        "market": market_result,
    }
