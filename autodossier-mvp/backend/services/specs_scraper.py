"""
Specs Scraper – Phase 2 (httpx-only, kein Playwright)
======================================================
Quelle: auto-data.net (server-side rendered HTML, kein JS nötig)

Navigation:
  1. Search: /en/search?search={make}+{model}
  2. Model page: /en/{Make}-{Model}-model-{id}.html
  3. Generation page: /en/{Make}-{Model}-{Gen}-generation-{id}.html (Jahr-Match)
  4. Variant page: /en/{Make}-{variant}-car-{id}.html → Specs-Tabelle

Fallback: Heuristik-Tabelle für Top-20-Modelle (kein Netzwerkzugriff).
Cache: 24h TTL (Specs ändern sich nicht für ein Modelljahr).
"""

from __future__ import annotations

import asyncio
import logging
import re
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx
from cachetools import TTLCache

from services.base import VehicleContext

logger = logging.getLogger(__name__)

# ─── Cache ────────────────────────────────────────────────────────────────────

_cache: TTLCache = TTLCache(maxsize=300, ttl=86_400)   # 24h
_lock = Lock()


def _cache_get(key: str) -> dict | None:
    with _lock:
        return _cache.get(key)


def _cache_set(key: str, value: dict) -> None:
    with _lock:
        _cache[key] = value


# ─── HTTP Config ──────────────────────────────────────────────────────────────

_BASE = "https://www.auto-data.net"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.auto-data.net/en/",
}

_TIMEOUT = httpx.Timeout(connect=6, read=12, write=5, pool=2)


# ─── Heuristik-Fallback (offline) ────────────────────────────────────────────

_HEURISTIC: dict[str, dict] = {
    "bmw|3er":               {"power_ps": 156, "fuel_consumption": "5.6", "co2": "148 g/km", "top_speed": 230, "acceleration": "8.0"},
    "bmw|5er":               {"power_ps": 190, "fuel_consumption": "6.0", "co2": "157 g/km", "top_speed": 235, "acceleration": "7.3"},
    "bmw|x3":                {"power_ps": 184, "fuel_consumption": "6.8", "co2": "178 g/km", "top_speed": 210, "acceleration": "8.5"},
    "bmw|x5":                {"power_ps": 265, "fuel_consumption": "8.0", "co2": "209 g/km", "top_speed": 235, "acceleration": "6.5"},
    "bmw|1er":               {"power_ps": 136, "fuel_consumption": "5.2", "co2": "136 g/km", "top_speed": 210, "acceleration": "8.5"},
    "volkswagen|golf":       {"power_ps": 110, "fuel_consumption": "5.3", "co2": "139 g/km", "top_speed": 195, "acceleration": "10.0"},
    "volkswagen|passat":     {"power_ps": 150, "fuel_consumption": "5.5", "co2": "143 g/km", "top_speed": 220, "acceleration": "8.5"},
    "volkswagen|tiguan":     {"power_ps": 150, "fuel_consumption": "6.5", "co2": "170 g/km", "top_speed": 205, "acceleration": "9.0"},
    "volkswagen|polo":       {"power_ps": 95,  "fuel_consumption": "4.9", "co2": "127 g/km", "top_speed": 185, "acceleration": "11.5"},
    "audi|a3":               {"power_ps": 116, "fuel_consumption": "5.1", "co2": "133 g/km", "top_speed": 200, "acceleration": "9.5"},
    "audi|a4":               {"power_ps": 150, "fuel_consumption": "5.5", "co2": "143 g/km", "top_speed": 225, "acceleration": "8.3"},
    "audi|a6":               {"power_ps": 190, "fuel_consumption": "6.0", "co2": "156 g/km", "top_speed": 240, "acceleration": "7.5"},
    "audi|q5":               {"power_ps": 190, "fuel_consumption": "7.0", "co2": "182 g/km", "top_speed": 218, "acceleration": "7.8"},
    "mercedes-benz|a-klasse":{"power_ps": 136, "fuel_consumption": "5.3", "co2": "138 g/km", "top_speed": 210, "acceleration": "8.7"},
    "mercedes-benz|c-klasse":{"power_ps": 170, "fuel_consumption": "6.1", "co2": "157 g/km", "top_speed": 235, "acceleration": "7.5"},
    "mercedes-benz|e-klasse":{"power_ps": 195, "fuel_consumption": "6.3", "co2": "163 g/km", "top_speed": 240, "acceleration": "7.2"},
    "mercedes-benz|glc":     {"power_ps": 194, "fuel_consumption": "7.2", "co2": "188 g/km", "top_speed": 222, "acceleration": "7.9"},
    "skoda|octavia":         {"power_ps": 115, "fuel_consumption": "5.2", "co2": "135 g/km", "top_speed": 200, "acceleration": "10.0"},
    "seat|leon":             {"power_ps": 115, "fuel_consumption": "5.3", "co2": "139 g/km", "top_speed": 198, "acceleration": "10.2"},
    "toyota|corolla":        {"power_ps": 122, "fuel_consumption": "4.5", "co2": "119 g/km", "top_speed": 185, "acceleration": "11.0"},
    "renault|megane":        {"power_ps": 115, "fuel_consumption": "5.6", "co2": "146 g/km", "top_speed": 190, "acceleration": "10.5"},
    "volvo|v60":             {"power_ps": 190, "fuel_consumption": "6.3", "co2": "164 g/km", "top_speed": 230, "acceleration": "7.5"},
    "volvo|xc40":            {"power_ps": 170, "fuel_consumption": "7.0", "co2": "183 g/km", "top_speed": 210, "acceleration": "8.3"},
    "volvo|xc60":            {"power_ps": 190, "fuel_consumption": "7.2", "co2": "190 g/km", "top_speed": 215, "acceleration": "8.1"},
    "hyundai|tucson":        {"power_ps": 150, "fuel_consumption": "7.0", "co2": "183 g/km", "top_speed": 200, "acceleration": "9.5"},
    "hyundai|i30":           {"power_ps": 120, "fuel_consumption": "5.5", "co2": "144 g/km", "top_speed": 195, "acceleration": "10.3"},
    "ford|focus":            {"power_ps": 125, "fuel_consumption": "5.5", "co2": "144 g/km", "top_speed": 205, "acceleration": "9.8"},
    "kia|sportage":          {"power_ps": 136, "fuel_consumption": "7.5", "co2": "196 g/km", "top_speed": 188, "acceleration": "10.5"},
    "peugeot|308":           {"power_ps": 130, "fuel_consumption": "5.8", "co2": "152 g/km", "top_speed": 205, "acceleration": "9.5"},
    "opel|astra":            {"power_ps": 130, "fuel_consumption": "5.6", "co2": "146 g/km", "top_speed": 210, "acceleration": "9.5"},
}


def _heuristic_key(make: str, model: str) -> str:
    return f"{make.lower()}|{model.lower()}"


# ─── Slug Helper ──────────────────────────────────────────────────────────────

_MAKE_ALIASES: dict[str, str] = {
    "vw":    "Volkswagen",
    "bmwm":  "BMW M",
}


def _search_query(make: str, model: str) -> str:
    m = _MAKE_ALIASES.get(make.lower(), make)
    return quote(f"{m} {model}".strip())


# ─── HTML Parsers ─────────────────────────────────────────────────────────────

_LABEL_MAP: dict[str, str] = {
    "power":                  "power_ps",
    "max power":              "power_ps",
    "leistung":               "power_ps",
    "engine displacement":    "engine_displacement",
    "displacement":           "engine_displacement",
    "hubraum":                "engine_displacement",
    "fuel consumption":       "fuel_consumption",
    "verbrauch":              "fuel_consumption",
    "combined":               "fuel_consumption",
    "co2 emissions":          "co2",
    "co2":                    "co2",
    "top speed":              "top_speed",
    "höchstgeschwindigkeit":  "top_speed",
    "0-100 km/h":             "acceleration",
    "0–100 km/h":             "acceleration",
    "beschleunigung":         "acceleration",
    "curb weight":            "curb_weight",
    "kerb weight":            "curb_weight",
    "leergewicht":            "curb_weight",
    "cylinders":              "cylinders",
    "zylinder":               "cylinders",
    "fuel type":              "fuel_type",
    "kraftstoff":             "fuel_type",
    "gearbox":                "transmission",
    "transmission":           "transmission",
    "getriebe":               "transmission",
    "body type":              "body_type",
    "karosserie":             "body_type",
}

_PS_PAT    = re.compile(r"(\d{2,4})\s*(?:ps|hp)", re.I)
_KW_PAT    = re.compile(r"(\d{2,4})\s*kw", re.I)
_CCM_PAT   = re.compile(r"([\d\s,.]+)\s*(?:cm³|ccm|cc\b)", re.I)
_LITER_PAT = re.compile(r"(\d+[.,]\d)\s*l\b", re.I)
_L100_PAT  = re.compile(r"(\d+[.,]\d+)\s*(?:l/100|l /100)", re.I)
_CO2_PAT   = re.compile(r"(\d+)\s*g/km", re.I)
_SPEED_PAT = re.compile(r"(\d{2,3})\s*km/h", re.I)
_ACC_PAT   = re.compile(r"(\d+[.,]\d+)\s*s(?:ec)?\b", re.I)
_KG_PAT    = re.compile(r"(\d{3,5})\s*kg", re.I)
_CYL_PAT   = re.compile(r"^\s*(\d{1,2})\s*$")


def _extract_value(field: str, raw: str) -> Any:
    raw = raw.strip()
    if field == "power_ps":
        m = _PS_PAT.search(raw)
        if m:
            return int(m.group(1))
        # Fallback: kW → PS (×1.36)
        m = _KW_PAT.search(raw)
        return round(int(m.group(1)) * 1.36) if m else None
    if field == "engine_displacement":
        m = _CCM_PAT.search(raw)
        if m:
            return m.group(1).replace(" ", "").replace(",", "") + " ccm"
        m = _LITER_PAT.search(raw)
        return m.group(1).replace(",", ".") + " L" if m else None
    if field == "fuel_consumption":
        m = _L100_PAT.search(raw)
        return m.group(1).replace(",", ".") if m else None
    if field == "co2":
        m = _CO2_PAT.search(raw)
        return f"{m.group(1)} g/km" if m else None
    if field == "top_speed":
        m = _SPEED_PAT.search(raw)
        return int(m.group(1)) if m else None
    if field == "acceleration":
        m = _ACC_PAT.search(raw)
        return m.group(1).replace(",", ".") if m else None
    if field == "curb_weight":
        m = _KG_PAT.search(raw)
        return int(m.group(1)) if m else None
    if field == "cylinders":
        m = _CYL_PAT.match(raw)
        return int(m.group(1)) if m else None
    return raw if raw not in ("–", "-", "n/a", "N/A", "") else None


def _parse_specs_html(html: str) -> dict:
    """Parse all <tr><td>label</td><td>value</td></tr> pairs from auto-data.net HTML."""
    data: dict[str, Any] = {}
    for m in re.finditer(
        r'<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        label = re.sub(r'<[^>]+>', '', m.group(1)).strip().lower()
        value = re.sub(r'<[^>]+>', '', m.group(2)).strip()
        if not label or not value:
            continue
        field = next((f for kw, f in _LABEL_MAP.items() if kw in label), None)
        if not field:
            continue
        val = _extract_value(field, value)
        if val is not None:
            data.setdefault(field, val)
    return data


# ─── HTTP Navigation ──────────────────────────────────────────────────────────

async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    for attempt in range(2):
        try:
            resp = await client.get(url)
            if resp.status_code == 429:
                await asyncio.sleep(2)
                continue
            if resp.status_code == 200:
                return resp
            if resp.status_code >= 500:
                await asyncio.sleep(1)
                continue
            return None
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            logger.debug("auto-data.net %s: %s", url[-60:], e)
            if attempt == 0:
                await asyncio.sleep(0.5)
    return None


async def _find_model_url(client: httpx.AsyncClient, make: str, model: str) -> str | None:
    url = f"{_BASE}/en/search?search={_search_query(make, model)}"
    resp = await _get(client, url)
    if not resp:
        return None
    m = re.search(r'href="(/en/[^"]*-model-\d+\.html)"', resp.text, re.I)
    if m:
        return _BASE + m.group(1)
    m = re.search(r'href="(/en/[^"]*(?:model|generation)-\d+\.html)"', resp.text, re.I)
    return (_BASE + m.group(1)) if m else None


async def _find_generation_url(
    client: httpx.AsyncClient, model_url: str, year: str
) -> str | None:
    await asyncio.sleep(0.4)
    resp = await _get(client, model_url)
    if not resp:
        return None

    gen_pat = re.compile(
        r'href="(/en/[^"]*-generation-\d+\.html)"[^>]*>([^<(]*\(?(\d{4})?)',
        re.I,
    )
    candidates = gen_pat.findall(resp.text)

    if not candidates:
        # Single-generation model — model page has the specs directly
        if _parse_specs_html(resp.text).get("power_ps"):
            return model_url
        return None

    if year:
        try:
            yr = int(year)
            valid = [(p, int(ys)) for p, _, ys in candidates if ys and int(ys) <= yr + 1]
            if valid:
                best = max(valid, key=lambda x: x[1])
                return _BASE + best[0]
        except ValueError:
            pass

    return _BASE + candidates[0][0]


async def _find_variant_and_parse(client: httpx.AsyncClient, gen_url: str) -> dict:
    await asyncio.sleep(0.4)
    resp = await _get(client, gen_url)
    if not resp:
        return {}

    specs = _parse_specs_html(resp.text)
    if specs.get("power_ps"):
        return specs

    variant_links = re.findall(r'href="(/en/[^"]*-car-\d+\.html)"', resp.text, re.I)
    if not variant_links:
        return {}

    await asyncio.sleep(0.3)
    resp2 = await _get(client, _BASE + variant_links[0])
    return _parse_specs_html(resp2.text) if resp2 else {}


async def _scrape_auto_data(make: str, model: str, year: str) -> dict:
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True, http2=True,
    ) as client:
        model_url = await _find_model_url(client, make, model)
        if not model_url:
            return {}
        gen_url = await _find_generation_url(client, model_url, year)
        if not gen_url:
            return {}
        specs = await _find_variant_and_parse(client, gen_url)
        if specs:
            specs["source"] = "auto-data.net"
        return specs


# ─── Public API ───────────────────────────────────────────────────────────────

async def get_specs(ctx: VehicleContext) -> dict[str, Any]:
    """Uniform interface: VehicleContext → specs dict.

    Priority: cache (24h) → auto-data.net (httpx) → heuristic table (offline).
    Never raises; returns {} on complete failure.
    """
    make  = ctx.get("make", "")
    model = ctx.get("model", "")
    year  = ctx.get("year", "")

    if not make:
        return {}

    cache_key = f"{make}|{model}|{year}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    try:
        specs = await asyncio.wait_for(_scrape_auto_data(make, model, year), timeout=25)
    except Exception as e:
        logger.warning("auto-data.net error for %s %s: %s", make, model, e)
        specs = {}

    if not specs.get("power_ps"):
        h_key = _heuristic_key(make, model)
        fallback = _HEURISTIC.get(h_key)
        if fallback:
            specs = {**fallback, "source": "heuristic"}
            logger.info("Specs: heuristic fallback for %s %s", make, model)

    _cache_set(cache_key, specs)
    return specs


async def scrape_specs(make: str, model: str, year: str = "") -> dict[str, Any]:
    """Legacy alias for backward compatibility."""
    return await get_specs({"make": make, "model": model, "year": year})  # type: ignore[arg-type]
