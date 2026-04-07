"""
Equipment Service – Teoalida-Sample (offline, kein Netzwerk)
============================================================
Liefert typische Serienausstattungs-Daten für die top 30 deutschen Markt-Modelle.

Datenquelle: Teoalida Car Database Sample + Hersteller-Konfiguratoren
             (siehe services/data/equipment_teoalida.json)

Lookup-Logik:
  1. Normalisierter Key: "{make_lower}|{model_normalized}"
  2. Alias-Tabelle: "3 Series" → "3er", "C-Class" → "c-klasse", etc.
  3. Keine Netzwerk-Anfragen, kein TTL-Cache nötig (O(1) dict-Lookup)
"""

from __future__ import annotations

import functools
import json
import logging
import re
from pathlib import Path
from typing import Any

from services.base import VehicleContext

logger = logging.getLogger(__name__)

# ─── Fixture Loader ───────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1)
def _load_db() -> dict[str, Any]:
    path = Path(__file__).parent / "data" / "equipment_teoalida.json"
    if not path.exists():
        logger.warning("Equipment fixture not found: %s", path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        # Strip meta key
        return {k: v for k, v in data.items() if not k.startswith("_")}
    except Exception as e:
        logger.error("Failed to load equipment fixture: %s", e)
        return {}


# ─── Normalization ────────────────────────────────────────────────────────────

# Maps incoming model name variants → canonical fixture key (model part only)
_MODEL_ALIASES: dict[str, str] = {
    # BMW
    "3 series":        "3er",
    "3-series":        "3er",
    "series 3":        "3er",
    "3er bmw":         "3er",
    "5 series":        "5er",
    "5-series":        "5er",
    "1 series":        "1er",
    "1-series":        "1er",
    "7 series":        "7er",
    "x 3":             "x3",
    "x 5":             "x5",
    # Mercedes
    "c-class":         "c-klasse",
    "c class":         "c-klasse",
    "e-class":         "e-klasse",
    "e class":         "e-klasse",
    "a-class":         "a-klasse",
    "a class":         "a-klasse",
    "glc-class":       "glc",
    # VW
    "golf gti":        "golf",
    "golf gtd":        "golf",
    "golf r":          "golf",
    "golf variant":    "golf",
    "golf alltrack":   "golf",
    # Audi
    "a 3":             "a3",
    "a 4":             "a4",
    "a 6":             "a6",
    "q 3":             "q3",
    "q 5":             "q5",
    # Skoda
    "kodiaq":          "karoq",   # Karoq alias for missing entry
    # Misc
    "crossland":       "astra",
    "grandland":       "astra",
    "308 sw":          "308",
    "308 gt":          "308",
    "civic":           "golf",    # fallback to closest segment
}

# Maps incoming make name variants → canonical fixture key (make part only)
_MAKE_ALIASES: dict[str, str] = {
    "vw":              "volkswagen",
    "merc":            "mercedes-benz",
    "mercedes":        "mercedes-benz",
    "mb":              "mercedes-benz",
    "bmwm":            "bmw",
    "alfa romeo":      "alfa-romeo",
    "alfa":            "alfa-romeo",
    "land rover":      "land-rover",
}


def _normalize_make(make: str) -> str:
    m = make.strip().lower()
    return _MAKE_ALIASES.get(m, m)


def _normalize_model(model: str) -> str:
    m = model.strip().lower()
    # Strip generation suffix: "Golf 8" → "golf", "3er G20" → "3er"
    m = re.sub(r'\s+[a-z]\d+\b', '', m)          # " G20", " F30"
    m = re.sub(r'\s+(?:mk|gen|generation)\s*\d+', '', m, flags=re.I)
    m = re.sub(r'\s+\d+$', '', m).strip()         # trailing digits
    return _MODEL_ALIASES.get(m, m)


def _lookup_key(make: str, model: str) -> str | None:
    """Return the best matching db key or None if not found."""
    db = _load_db()
    if not db:
        return None

    norm_make  = _normalize_make(make)
    norm_model = _normalize_model(model)
    exact = f"{norm_make}|{norm_model}"
    if exact in db:
        return exact

    # Partial match: same make, model is substring of key
    for key in db:
        km, kmod = key.split("|", 1)
        if km == norm_make and (norm_model in kmod or kmod in norm_model):
            return key

    # Make-only fallback: return first entry for this make
    for key in db:
        if key.startswith(norm_make + "|"):
            logger.debug("Equipment: make-only match %s → %s", exact, key)
            return key

    return None


# ─── Public API ───────────────────────────────────────────────────────────────

async def get_equipment(ctx: VehicleContext) -> dict[str, Any]:
    """Uniform interface: VehicleContext → equipment dict.

    Returns offline Teoalida-style equipment data.
    Never raises; returns {"available": False} when no data found.
    """
    make  = ctx.get("make", "")
    model = ctx.get("model", "")

    if not make:
        return {"available": False}

    key = _lookup_key(make, model)
    if not key:
        logger.info("Equipment: no data for %s %s", make, model)
        return {"available": False}

    db    = _load_db()
    entry = db[key]

    return {
        "available":         True,
        "serienausstattung": entry.get("serienausstattung", []),
        "sicherheit":        entry.get("sicherheit", []),
        "typisch_optional":  entry.get("typisch_optional", []),
        "euro_norm":         entry.get("euro_norm", ""),
        "source":            "Teoalida-Datenbank (Musterdaten)",
        "matched_model":     key,
    }
