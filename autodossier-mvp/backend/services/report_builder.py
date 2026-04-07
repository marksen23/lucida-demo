"""
Report Builder – Phase 2
========================
Orchestriert alle Services, berechnet den Koeffizient-Score und baut
den finalen Report zusammen.

Öffentliche API:
    async def build_report(vin, *, asking_price=None, mileage=None, premium=False)

Score-Algorithmus: Strafpunkte-Modell (Start 100, Abzüge pro Dimension)
    Preis          0–40 Pkt  (Angebotspreis vs. Ø-Marktpreis)
    Betriebskosten 0–25 Pkt  (monatliche Gesamtkosten)
    Fahrzeugalter  0–20 Pkt  (Baujahr vs. aktuelles Jahr)
    Kilometerstand 0–15 Pkt  (Laufleistung aus erstem Listing)
    ──────────────────────────────
    Gesamt         0–100 Pkt
    ≥80 → Guter Kauf (grün)
    ≥55 → Faire Bewertung (gelb)
     <55 → Teuer / Prüfen (rot)

Premium-Hook: if premium: lade optionale Premium-Services nach.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Any

from services.base import VehicleContext, ctx_from_vin_data
from services.vin_decoder import decode_vin
from services.specs_scraper import get_specs
from services.equipment_service import get_equipment
from services.market_scraper import get_market
from services.adac_parser import get_costs

logger = logging.getLogger(__name__)

# ─── Score Helpers ────────────────────────────────────────────────────────────

_CURRENT_YEAR = date.today().year


def _score_price(asking: int | None, market: dict) -> tuple[int, str]:
    """Abzug 0–40: Verhältnis Kaufpreis / Ø-Marktpreis."""
    avg = market.get("avg_price")
    if not avg or not asking:
        return 0, "Keine Marktpreisdaten verfügbar"
    ratio = asking / avg
    if ratio <= 0.90:
        return 0,  f"Sehr guter Preis (≤90% des Marktdurchschnitts, Ø {avg:,.0f} €)"
    if ratio <= 1.05:
        return 5,  f"Fairer Preis (90–105% des Marktdurchschnitts, Ø {avg:,.0f} €)"
    if ratio <= 1.15:
        return 15, f"Leicht überteuert (105–115% des Marktdurchschnitts, Ø {avg:,.0f} €)"
    if ratio <= 1.30:
        return 28, f"Überteuert (115–130% des Marktdurchschnitts, Ø {avg:,.0f} €)"
    return 40,     f"Stark überteuert (>130% des Marktdurchschnitts, Ø {avg:,.0f} €)"


def _score_costs(costs: dict) -> tuple[int, str]:
    """Abzug 0–25: monatliche Gesamtkosten."""
    total = costs.get("total_monthly", 0) or 0
    if not total:
        return 0, "Keine Kostendaten verfügbar"
    if total < 300:
        return 0,  f"Geringe Betriebskosten ({total:.0f} €/Monat)"
    if total < 480:
        return 5,  f"Moderate Kosten ({total:.0f} €/Monat)"
    if total < 650:
        return 12, f"Erhöhte Kosten ({total:.0f} €/Monat)"
    if total < 900:
        return 20, f"Hohe Kosten ({total:.0f} €/Monat)"
    return 25,     f"Sehr hohe Kosten ({total:.0f} €/Monat)"


def _score_age(year_str: str) -> tuple[int, str]:
    """Abzug 0–20: Fahrzeugalter."""
    try:
        age = _CURRENT_YEAR - int(year_str)
    except (TypeError, ValueError):
        return 0, "Baujahr unbekannt"
    if age < 0:
        age = 0
    if age <= 2:
        return 0,  f"Neufahrzeug ({age} {'Jahr' if age == 1 else 'Jahre'})"
    if age <= 5:
        return 5,  f"Junger Gebrauchter ({age} Jahre)"
    if age <= 9:
        return 10, f"Mittleres Alter ({age} Jahre)"
    if age <= 14:
        return 16, f"Älteres Fahrzeug ({age} Jahre)"
    return 20,     f"Sehr alt ({age} Jahre)"


def _score_mileage(mileage: int | None) -> tuple[int, str]:
    """Abzug 0–15: Kilometerstand."""
    if mileage is None:
        return 0, "Kilometerstand unbekannt"
    if mileage < 0:
        mileage = 0
    if mileage <= 40_000:
        return 0,  f"Niedrige Laufleistung ({mileage:,} km)".replace(",", ".")
    if mileage <= 90_000:
        return 4,  f"Moderate Laufleistung ({mileage:,} km)".replace(",", ".")
    if mileage <= 140_000:
        return 9,  f"Hohe Laufleistung ({mileage:,} km)".replace(",", ".")
    if mileage <= 200_000:
        return 13, f"Sehr hohe Laufleistung ({mileage:,} km)".replace(",", ".")
    return 15,     f"Extreme Laufleistung ({mileage:,} km)".replace(",", ".")


def _compute_score(
    ctx: VehicleContext,
    costs: dict,
    market: dict,
    asking_price: int | None,
    mileage: int | None,
) -> dict[str, Any]:
    """Berechne den Koeffizient-Score (0–100) mit Breakdown."""
    # Wenn kein asking_price übergeben → ersten Listing-Preis als Proxy nutzen
    listings = market.get("listings", [])
    if asking_price is None and listings:
        try:
            asking_price = int(listings[0].get("price") or 0) or None
        except (TypeError, ValueError):
            asking_price = None

    # Wenn kein mileage übergeben → ersten Listing-KM-Stand als Proxy
    if mileage is None and listings:
        try:
            mileage = int(listings[0].get("mileage") or 0) or None
        except (TypeError, ValueError):
            mileage = None

    p_ded, p_text = _score_price(asking_price, market)
    c_ded, c_text = _score_costs(costs)
    a_ded, a_text = _score_age(ctx.get("year", ""))
    m_ded, m_text = _score_mileage(mileage)

    total_deduction = p_ded + c_ded + a_ded + m_ded
    score = max(0, 100 - total_deduction)

    if score >= 80:
        ampel = {"klasse": "grün",  "icon": "✓", "label": "Guter Kauf",       "css": "ampel-green"}
    elif score >= 55:
        ampel = {"klasse": "gelb",  "icon": "!", "label": "Faire Bewertung",   "css": "ampel-yellow"}
    else:
        ampel = {"klasse": "rot",   "icon": "✕", "label": "Teuer / Prüfen",   "css": "ampel-red"}

    return {
        "wert":      score,
        "ampel":     ampel,
        "breakdown": [
            {"dimension": "Preis",          "abzug": p_ded, "max": 40, "text": p_text},
            {"dimension": "Betriebskosten", "abzug": c_ded, "max": 25, "text": c_text},
            {"dimension": "Fahrzeugalter",  "abzug": a_ded, "max": 20, "text": a_text},
            {"dimension": "Kilometerstand", "abzug": m_ded, "max": 15, "text": m_text},
        ],
    }


# ─── Report Assembly ──────────────────────────────────────────────────────────

def _safe(result: Any) -> dict:
    """Return {} for exceptions, otherwise the dict."""
    return {} if isinstance(result, (Exception, BaseException)) else (result or {})


# ─── Public API ───────────────────────────────────────────────────────────────

async def build_report(
    vin: str,
    *,
    asking_price: int | None = None,
    mileage:      int | None = None,
    premium:      bool = False,
    extra_services: list | None = None,
) -> dict[str, Any]:
    """Build a complete vehicle report for the given VIN.

    Args:
        vin:            17-char VIN (uppercase, already validated)
        asking_price:   Optional buying price in EUR for score calculation
        mileage:        Optional odometer reading in km for score calculation
        premium:        If True, load extra premium services (Phase 3)
        extra_services: List of async callables accepting VehicleContext (premium)

    Returns:
        Complete report dict with keys:
        vin, tier, vehicle, specs, equipment, costs, market, score, warnings
    """
    warnings: list[str] = []

    # ── 1. VIN dekodieren ─────────────────────────────────────────────────────
    try:
        vin_data = await asyncio.wait_for(decode_vin(vin), timeout=15)
    except asyncio.TimeoutError:
        vin_data = {}
        warnings.append("VIN-Dekodierung Timeout")
    except Exception as e:
        vin_data = {}
        warnings.append(f"VIN-Dekodierung fehlgeschlagen: {e}")

    ctx = ctx_from_vin_data(vin, vin_data)

    # ── 2. Parallel-Gather aller Free-Services ────────────────────────────────
    specs_t    = asyncio.create_task(asyncio.wait_for(get_specs(ctx),     timeout=22))
    equip_t    = asyncio.create_task(asyncio.wait_for(get_equipment(ctx), timeout=5))
    costs_t    = asyncio.create_task(asyncio.wait_for(
        asyncio.to_thread(get_costs, ctx), timeout=15
    ))
    market_t   = asyncio.create_task(asyncio.wait_for(get_market(ctx),    timeout=30))

    results = await asyncio.gather(
        specs_t, equip_t, costs_t, market_t,
        return_exceptions=True,
    )

    specs, equipment, costs, market = (
        _safe(results[0]), _safe(results[1]),
        _safe(results[2]), _safe(results[3]),
    )

    # Log any service-level errors
    labels = ("specs", "equipment", "costs", "market")
    for label, res in zip(labels, results):
        if isinstance(res, (Exception, BaseException)):
            warnings.append(f"{label}: {type(res).__name__}: {res}")
            logger.warning("Service '%s' failed: %s", label, res)

    # ── 3. Premium-Hook (Phase 3 erweiterbar) ────────────────────────────────
    tier = "free"
    premium_data: dict[str, Any] = {}
    if premium and extra_services:
        tier = "premium"
        prem_results = await asyncio.gather(
            *[asyncio.wait_for(svc(ctx), timeout=20) for svc in extra_services],
            return_exceptions=True,
        )
        for svc, res in zip(extra_services, prem_results):
            name = getattr(svc, "__name__", str(svc))
            if not isinstance(res, (Exception, BaseException)):
                premium_data[name] = res
            else:
                warnings.append(f"premium/{name}: {res}")

    # ── 4. Score berechnen ────────────────────────────────────────────────────
    score = _compute_score(ctx, costs, market, asking_price, mileage)

    # ── 5. Report zusammenbauen ───────────────────────────────────────────────
    report: dict[str, Any] = {
        "vin":       vin,
        "tier":      tier,
        "vehicle":   vin_data,
        "specs":     specs,
        "equipment": equipment,
        "costs":     costs,
        "market":    market,
        "score":     score,
        "warnings":  warnings,
    }

    if premium_data:
        report.update(premium_data)

    logger.info(
        "Report built for %s: make=%r year=%r score=%d tier=%s warnings=%d",
        vin,
        vin_data.get("make"),
        vin_data.get("year"),
        score["wert"],
        tier,
        len(warnings),
    )
    return report
