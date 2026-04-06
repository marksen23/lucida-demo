"""
VIN Decoder Service
Scrapes freevindecoder.eu with Playwright (fallback: driving-tests.org).
Returns a dict with make, model, year, engine, trim, fuel_type, transmission.
"""

import asyncio
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Try to import Playwright; degrade gracefully if not installed
try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed – VIN decoder will return empty results")


# ─── Public API ───────────────────────────────────────────────────────────────

async def decode_vin(vin: str) -> dict[str, Any]:
    """Return decoded VIN fields. Always returns a dict (never raises)."""
    if not PLAYWRIGHT_AVAILABLE:
        return {}
    try:
        result = await _decode_freevindecoder(vin)
        if result.get("make"):
            return result
        # Fallback
        return await _decode_driving_tests(vin)
    except Exception as exc:
        logger.error("VIN decode error: %s", exc)
        return {}


# ─── Source 1: freevindecoder.eu ─────────────────────────────────────────────

async def _decode_freevindecoder(vin: str) -> dict:
    url = f"https://freevindecoder.eu/results/{vin}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(2)  # polite delay

            data: dict = {}

            # freevindecoder.eu renders a table with label/value rows
            rows = await page.query_selector_all("table tr, .vin-result tr, .result-table tr")
            for row in rows:
                cells = await row.query_selector_all("td, th")
                if len(cells) >= 2:
                    label = (await cells[0].inner_text()).strip().lower()
                    value = (await cells[1].inner_text()).strip()
                    if not value or value in ("-", "n/a", ""):
                        continue
                    if "make" in label or "brand" in label or "manufacturer" in label:
                        data["make"] = value.title()
                    elif "model" in label:
                        data["model"] = value
                    elif "year" in label or "model year" in label:
                        data["year"] = value
                    elif "engine" in label:
                        data["engine"] = value
                    elif "trim" in label or "series" in label:
                        data["trim"] = value
                    elif "fuel" in label:
                        data["fuel_type"] = value
                    elif "transmission" in label:
                        data["transmission"] = value
                    elif "body" in label:
                        data["body_style"] = value

            # Also try definition list pattern
            if not data.get("make"):
                dts = await page.query_selector_all("dt")
                dds = await page.query_selector_all("dd")
                for dt, dd in zip(dts, dds):
                    label = (await dt.inner_text()).strip().lower()
                    value = (await dd.inner_text()).strip()
                    if not value or value in ("-", "n/a"):
                        continue
                    if "make" in label or "brand" in label:
                        data["make"] = value.title()
                    elif "model" in label:
                        data["model"] = value
                    elif "year" in label:
                        data["year"] = value

            return data
        except PWTimeout:
            logger.warning("freevindecoder.eu timed out for VIN %s", vin)
            return {}
        finally:
            await browser.close()


# ─── Source 2: driving-tests.org (fallback) ──────────────────────────────────

async def _decode_driving_tests(vin: str) -> dict:
    url = f"https://driving-tests.org/vin-decoder/?vin={vin}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=25_000)
            await asyncio.sleep(2)

            data: dict = {}
            rows = await page.query_selector_all(".vin-results tr, .vehicle-data tr, table tr")
            for row in rows:
                cells = await row.query_selector_all("td")
                if len(cells) >= 2:
                    label = (await cells[0].inner_text()).strip().lower()
                    value = (await cells[1].inner_text()).strip()
                    if not value or value in ("-", "n/a", ""):
                        continue
                    if "make" in label:
                        data["make"] = value.title()
                    elif "model" in label:
                        data["model"] = value
                    elif "year" in label:
                        data["year"] = value
                    elif "engine" in label:
                        data["engine"] = value
                    elif "fuel" in label:
                        data["fuel_type"] = value
                    elif "transmission" in label:
                        data["transmission"] = value

            # Try WMI-based fallback decode from raw VIN characters
            if not data.get("make"):
                data.update(_wmi_fallback(vin))

            return data
        except PWTimeout:
            return _wmi_fallback(vin)
        finally:
            await browser.close()


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
