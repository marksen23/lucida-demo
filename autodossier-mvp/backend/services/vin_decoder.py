"""
VIN Decoder Service
===================
Priority chain:
  1. freevindecoder.eu   – httpx scrape, EU-focused, best for German VINs
  2. driving-tests.org   – httpx scrape, second free source
  3. WMI table           – instant, offline, comprehensive EU coverage
  4. NHTSA vPIC API      – httpx, US/international, last resort

Results are cached 24 h (TTLCache, 500 slots).
Every result carries a `confidence` float (0.0–1.0).
"""

import asyncio
import json
import logging
import re
from threading import Lock
from typing import Any

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# ─── Cache ────────────────────────────────────────────────────────────────────

_cache: TTLCache = TTLCache(maxsize=500, ttl=86_400)   # 24 h
_lock = Lock()


def _cache_get(vin: str) -> dict | None:
    with _lock:
        return _cache.get(vin)


def _cache_set(vin: str, value: dict) -> None:
    with _lock:
        _cache[vin] = value


# ─── Shared HTTP Config ───────────────────────────────────────────────────────

_TIMEOUT = httpx.Timeout(connect=5, read=9, write=5, pool=2)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "DNT":             "1",
}

_NHTSA_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevinextended/{}?format=json"


# ─── Public API ───────────────────────────────────────────────────────────────

async def decode_vin(vin: str) -> dict[str, Any]:
    """
    Decode a 17-char VIN.
    Always returns a dict; guaranteed `make` + `year` for any WMI in the table.
    """
    vin = vin.upper().strip()

    cached = _cache_get(vin)
    if cached is not None:
        logger.debug("VIN %s served from cache", vin)
        return cached

    result = await _decode_chain(vin)
    _cache_set(vin, result)
    logger.info(
        "VIN %s → make=%r model=%r year=%r confidence=%.2f source=%r",
        vin,
        result.get("make"),
        result.get("model"),
        result.get("year"),
        result.get("confidence", 0.0),
        result.get("source"),
    )
    return result


# ─── Decode Chain ─────────────────────────────────────────────────────────────

async def _decode_chain(vin: str) -> dict:
    # Step 1 – freevindecoder.eu
    try:
        r = await asyncio.wait_for(_freevindecoder(vin), timeout=10)
        if r.get("make"):
            return {**r, "confidence": 0.90, "source": "freevindecoder.eu"}
    except Exception as exc:
        logger.warning("freevindecoder.eu failed for %s: %s", vin, exc)

    # Step 2 – driving-tests.org
    try:
        r = await asyncio.wait_for(_driving_tests(vin), timeout=10)
        if r.get("make"):
            return {**r, "confidence": 0.85, "source": "driving-tests.org"}
    except Exception as exc:
        logger.warning("driving-tests.org failed for %s: %s", vin, exc)

    # Step 3 – WMI table (instant, offline)
    wmi = _wmi_decode(vin)

    # Step 4 – NHTSA to enrich WMI data (or as sole source for unknown WMI)
    try:
        nhtsa = await asyncio.wait_for(_nhtsa(vin), timeout=9)
        if nhtsa.get("make"):
            # NHTSA wins on most fields; WMI fills remaining gaps.
            # But WMI year (from position-9 char, defaulting to 2010+ cycle)
            # is more reliable than NHTSA for EU VINs, so preserve it.
            merged = {**wmi, **{k: v for k, v in nhtsa.items() if v}}
            if wmi.get("year"):
                merged["year"] = wmi["year"]
            # Keep WMI origin_country (manufacturer HQ, from VIN pos 0)
            # separately from NHTSA's plant_country (assembly location)
            if wmi.get("origin_country"):
                merged["origin_country"] = wmi["origin_country"]
            merged["confidence"] = 0.80 if wmi.get("make") else 0.65
            merged["source"] = "NHTSA+WMI" if wmi.get("make") else "NHTSA"
            return _clean(merged)
    except Exception as exc:
        logger.warning("NHTSA failed for %s: %s", vin, exc)

    # WMI-only result
    if wmi.get("make"):
        return {**wmi, "confidence": 0.60, "source": "WMI"}

    return {"confidence": 0.0, "source": "unknown"}


# ─── Source 1: freevindecoder.eu ─────────────────────────────────────────────

async def _freevindecoder(vin: str) -> dict:
    """
    Fetch freevindecoder.eu results page and parse the HTML table / dl.
    They render server-side HTML, so httpx works without a browser.
    """
    urls_to_try = [
        f"https://freevindecoder.eu/results/{vin}",
        f"https://freevindecoder.eu/?vin={vin}",
        f"https://freevindecoder.eu/vin/{vin}",
    ]

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={**_BROWSER_HEADERS, "Referer": "https://freevindecoder.eu/"},
        http2=True,
    ) as client:
        for url in urls_to_try:
            try:
                resp = await client.get(url)
                if resp.status_code == 200 and len(resp.text) > 500:
                    result = _parse_generic_vin_html(resp.text, vin)
                    if result.get("make"):
                        return result
            except Exception:
                continue

    return {}


# ─── Source 2: driving-tests.org ─────────────────────────────────────────────

async def _driving_tests(vin: str) -> dict:
    url = f"https://driving-tests.org/vin-decoder/?vin={vin}"

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={**_BROWSER_HEADERS, "Referer": "https://driving-tests.org/"},
        http2=True,
    ) as client:
        resp = await client.get(url)

    if resp.status_code != 200:
        return {}

    return _parse_generic_vin_html(resp.text, vin)


# ─── HTML Parser (shared for multiple sites) ──────────────────────────────────

_FIELD_MAP: dict[str, str] = {
    "make":         ["make", "brand", "manufacturer", "marke", "hersteller"],
    "model":        ["model", "modell"],
    "year":         ["year", "model year", "baujahr", "modelljahr"],
    "trim":         ["trim", "series", "ausstattung", "version"],
    "engine":       ["engine", "motor", "displacement", "hubraum"],
    "fuel_type":    ["fuel", "kraftstoff", "fuel type"],
    "transmission": ["transmission", "getriebe", "gearbox"],
    "body_style":   ["body", "karosserie", "body type", "body style"],
    "drive_type":   ["drive", "antrieb", "drive type"],
    "country":      ["country", "plant country", "land"],
    "manufacturer": ["manufacturer name", "hersteller"],
}


def _match_field(label: str) -> str | None:
    label = label.lower().strip()
    for field, keywords in _FIELD_MAP.items():
        if any(kw in label for kw in keywords):
            return field
    return None


def _parse_generic_vin_html(html: str, vin: str) -> dict:
    data: dict[str, str] = {}

    # A) JSON-LD / application/json embedded in page
    for m in re.finditer(
        r'<script[^>]*type="application/(?:ld\+)?json"[^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        try:
            obj = json.loads(m.group(1))
            _extract_json_vin(obj, data)
        except Exception:
            pass
    if data.get("make"):
        return _clean(data)

    # B) <table> rows with 2+ <td> cells
    for row in re.finditer(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL | re.IGNORECASE):
        cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row.group(1),
                           re.DOTALL | re.IGNORECASE)
        cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if len(cells) >= 2 and cells[0] and cells[1]:
            f = _match_field(cells[0])
            if f and cells[1] not in ("-", "N/A", "n/a", ""):
                data.setdefault(f, cells[1])

    if data.get("make"):
        return _clean(data)

    # C) <dt>/<dd> definition lists
    dts = re.findall(r'<dt[^>]*>(.*?)</dt>', html, re.DOTALL | re.IGNORECASE)
    dds = re.findall(r'<dd[^>]*>(.*?)</dd>', html, re.DOTALL | re.IGNORECASE)
    for dt_raw, dd_raw in zip(dts, dds):
        label = re.sub(r'<[^>]+>', '', dt_raw).strip()
        value = re.sub(r'<[^>]+>', '', dd_raw).strip()
        f = _match_field(label)
        if f and value and value not in ("-", "N/A", "n/a", ""):
            data.setdefault(f, value)

    if data.get("make"):
        return _clean(data)

    # D) key: value patterns in plain text
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)
    for m in re.finditer(r'([\w\s/()-]{3,30}):\s*([^\n;,<]{2,40})', text):
        f = _match_field(m.group(1))
        v = m.group(2).strip()
        if f and v and v not in ("-", "N/A", "n/a"):
            data.setdefault(f, v)

    return _clean(data)


def _extract_json_vin(obj: Any, data: dict) -> None:
    """Recursively walk a JSON object looking for VIN field mappings."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            f = _match_field(str(k))
            if f and isinstance(v, str) and v.strip():
                data.setdefault(f, v.strip())
            _extract_json_vin(v, data)
    elif isinstance(obj, list):
        for item in obj:
            _extract_json_vin(item, data)


_MAKE_FIX = {
    "Bmw": "BMW", "Vw": "VW", "Mg": "MG", "Lti": "LTI",
    "Gmc": "GMC", "Bmwm": "BMW M", "Ag": "AG",
}

def _clean(data: dict) -> dict:
    """Normalise make capitalisation and strip year noise."""
    if data.get("make"):
        mk = data["make"].title()
        # Fix known all-caps brands that title() mangles
        for wrong, right in _MAKE_FIX.items():
            mk = mk.replace(wrong, right)
        mk = mk.replace(" Ag", " AG").replace(" Gmbh", " GmbH").replace("Benz", "Benz")
        data["make"] = mk.strip()
    year = data.get("year", "")
    m = re.search(r"\b(19[7-9]\d|20[0-3]\d)\b", str(year))
    if m:
        data["year"] = m.group(1)
    return data


# ─── Source 4: NHTSA vPIC ────────────────────────────────────────────────────

async def _nhtsa(vin: str) -> dict:
    url = _NHTSA_URL.format(vin)
    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"Accept": "application/json"},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        payload = resp.json()

    _SKIP = {"Not Applicable", "0", "null", "NULL", "None", ""}
    kv: dict[str, str] = {
        (item.get("Variable") or "").strip(): (item.get("Value") or "").strip()
        for item in payload.get("Results", [])
        if (item.get("Value") or "").strip() not in _SKIP
    }

    make = kv.get("Make", "")
    if not make:
        return {}

    displ    = kv.get("Displacement (L)", "")
    cyl      = kv.get("Engine Number of Cylinders", "")
    eng      = " ".join(filter(None, [f"{displ}L" if displ else "", f"{cyl}Zyl" if cyl else ""]))

    return {
        "make":                make.title(),
        "model":               kv.get("Model", ""),
        "year":                kv.get("Model Year", ""),
        "trim":                kv.get("Trim", ""),
        "engine":              eng,
        "engine_displacement": f"{displ}L" if displ else "",
        "cylinders":           cyl,
        "fuel_type":           kv.get("Fuel Type - Primary", ""),
        "transmission":        kv.get("Transmission Style", ""),
        "drive_type":          kv.get("Drive Type", ""),
        "body_style":          kv.get("Body Class", ""),
        "country":             kv.get("Plant Country", ""),
        "manufacturer":        kv.get("Manufacturer Name", ""),
    }


# ─── WMI Table (offline, instant) ─────────────────────────────────────────────

_WMI: dict[str, str] = {
    # ── Germany ───────────────────────────────────────────────────────────────
    "WBA": "BMW",            "WBS": "BMW M",         "WBY": "BMW",
    "WVW": "Volkswagen",     "WV1": "Volkswagen",     "WV2": "Volkswagen",
    "WAU": "Audi",           "WUA": "Audi",           "WAP": "Audi",
    "WDD": "Mercedes-Benz",  "WDB": "Mercedes-Benz",  "WDC": "Mercedes-Benz",
    "WDF": "Mercedes-Benz",  "WMX": "Mercedes-Benz",  "WME": "Smart",
    "WP0": "Porsche",        "WP1": "Porsche",
    "W0L": "Opel",           "W0V": "Opel",           "W0G": "Opel",
    "WMA": "MAN",            "WJM": "Jeep",
    "WF0": "Ford EU",        "WF0": "Ford EU",
    "TRU": "Audi",           "TMA": "Audi",
    # ── Austria / Czech / Hungary ─────────────────────────────────────────────
    "TMB": "Škoda",          "TM8": "Škoda",
    "VWV": "Volkswagen AT",
    # ── Spain ─────────────────────────────────────────────────────────────────
    "VSS": "SEAT",           "VSE": "SEAT",           "VNK": "Toyota",
    "VS6": "Ford",           "VS7": "Chrysler",
    # ── France ────────────────────────────────────────────────────────────────
    "VF1": "Renault",        "VF3": "Peugeot",        "VF7": "Citroën",
    "VNE": "Renault",        "VFA": "Renault",
    "VF6": "Peugeot",        "VF8": "Citroën",
    # ── Italy ─────────────────────────────────────────────────────────────────
    "ZFF": "Ferrari",        "ZHW": "Lamborghini",    "ZAR": "Alfa Romeo",
    "ZFA": "Fiat",           "ZCF": "Iveco",          "ZAA": "Lancia",
    "ZDB": "De Tomaso",
    # ── UK ────────────────────────────────────────────────────────────────────
    "SAL": "Land Rover",     "SAJ": "Jaguar",         "SAR": "Rover",
    "SCF": "Aston Martin",   "SCA": "Rolls-Royce",    "SCC": "Lotus",
    "SDB": "Bentley",        "SEA": "Rolls-Royce",
    # ── Sweden ────────────────────────────────────────────────────────────────
    "YV1": "Volvo",          "YV2": "Volvo",          "YS3": "Saab",
    "LVY": "Volvo CN",
    # ── Netherlands / Belgium ─────────────────────────────────────────────────
    "XLE": "DAF",
    # ── Russia ────────────────────────────────────────────────────────────────
    "XTA": "Lada",           "X9F": "GAZ",
    # ── Japan ─────────────────────────────────────────────────────────────────
    "JHM": "Honda",          "JN1": "Nissan",         "JN8": "Nissan",
    "JT2": "Toyota",         "JT3": "Toyota",         "JT6": "Lexus",
    "JF1": "Subaru",         "JF2": "Subaru",
    "JMB": "Mitsubishi",     "JM1": "Mazda",          "JM6": "Mazda",
    "JS1": "Suzuki",         "JS2": "Suzuki",
    # ── Korea ─────────────────────────────────────────────────────────────────
    "KMH": "Hyundai",        "KMF": "Hyundai",
    "KNA": "Kia",            "KNM": "Kia",
    "KL1": "Daewoo",
    # ── USA ───────────────────────────────────────────────────────────────────
    "1G1": "Chevrolet",      "1GC": "Chevrolet",      "1GT": "GMC",
    "1FA": "Ford",           "1FB": "Ford",           "1FT": "Ford",
    "1HG": "Honda",          "2HG": "Honda",          "3HG": "Honda",
    "1J4": "Jeep",           "1B3": "Dodge",          "2C3": "Chrysler",
    # ── China ─────────────────────────────────────────────────────────────────
    "LFV": "Volkswagen",     "LVS": "Ford",           "LSG": "General Motors",
}

# Model hints: 4–5 VIN chars → model family
_WMI_MODEL: dict[str, str] = {
    # BMW
    "WBA1": "1er",   "WBA2": "2er",   "WBA3": "3er",   "WBA4": "4er",
    "WBA5": "5er",   "WBA6": "6er",   "WBA7": "7er",   "WBA8": "8er",
    "WBY0": "i3",    "WBY1": "i8",    "WBYX": "X",
    # VW
    "WVWZ": "Golf",  "WVWA": "Golf",  "WVWH": "Polo",  "WVWJ": "Passat",
    "WVWP": "Touareg","WVWT": "Tiguan",
    # Audi
    "WAUA": "A4",    "WAUB": "A5",    "WAUC": "A6",    "WAUD": "A8",
    "WAUE": "A3",    "WAU2": "Q5",    "WAU3": "Q7",    "WAU7": "Q8",
    # Mercedes
    "WDD1": "C-Klasse","WDD2": "E-Klasse","WDD3": "S-Klasse",
    "WDC0": "GLC",   "WDC1": "GLE",   "WDC2": "GLS",
    # Porsche
    "WP0A": "911",   "WP0B": "Boxster","WP0C": "Cayenne",
    "WP0Z": "Panamera","WP0Y": "Macan",
    # Opel/Vauxhall
    "W0LA": "Astra", "W0LE": "Corsa", "W0LG": "Insignia","W0LV": "Zafira",
    # Volvo (position 4 = model series)
    "YV1Z": "V60",   "YV1B": "V60",   "YV1F": "XC60",  "YV1L": "XC90",
    "YV1A": "V90",   "YV1C": "S60",   "YV1D": "S90",   "YV1X": "XC40",
}


# VIN position 0 → manufacturer's home country (ISO 3166-1 alpha-2 style labels)
_VIN_ORIGIN: dict[str, str] = {
    "1": "USA", "2": "Kanada", "3": "Mexiko",
    "4": "USA", "5": "USA",
    "6": "Australien", "7": "Neuseeland",
    "8": "Argentinien", "9": "Brasilien",
    "A": "Südafrika",
    "J": "Japan",
    "K": "Südkorea",
    "L": "China",
    "M": "Indien",
    "N": "Niederlande",
    "P": "Philippinen",
    "R": "Taiwan",
    "S": "Großbritannien",
    "T": "Tschechien",        # TMB = Škoda CZ
    "U": "Rumänien",
    "V": "Frankreich",
    "W": "Deutschland",
    "X": "Russland",
    "Y": "Schweden",
    "Z": "Italien",
}


def _wmi_decode(vin: str) -> dict:
    wmi3 = vin[:3].upper()
    make = _WMI.get(wmi3)

    model = (
        _WMI_MODEL.get(vin[:4].upper())
        or _WMI_MODEL.get(vin[:5].upper())
        or ""
    )

    year_char = vin[9].upper() if len(vin) >= 10 else ""
    year = _year_from_char(year_char)

    origin = _VIN_ORIGIN.get(vin[0].upper(), "") if vin else ""

    result: dict = {}
    if make:
        result["make"] = make
    if model:
        result["model"] = model
    if year:
        result["year"] = str(year)
    if origin:
        result["origin_country"] = origin
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
    }.get(c)
