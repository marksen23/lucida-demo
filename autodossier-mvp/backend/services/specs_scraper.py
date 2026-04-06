"""
Technical Specs Scraper
Searches auto-data.net for the given Make + Model and extracts key specs.
"""

import asyncio
import logging
import re
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)


async def scrape_specs(make: str, model: str, year: str = "") -> dict[str, Any]:
    """Return technical specs dict. Never raises."""
    if not PLAYWRIGHT_AVAILABLE or not make:
        return {}
    try:
        return await asyncio.wait_for(_scrape(make, model, year), timeout=30)
    except asyncio.TimeoutError:
        logger.warning("specs_scraper timeout for %s %s", make, model)
        return {}
    except Exception as exc:
        logger.error("specs_scraper error: %s", exc)
        return {}


async def _scrape(make: str, model: str, year: str) -> dict:
    search_query = " ".join(filter(None, [make, model, year]))
    search_url = f"https://www.auto-data.net/en/search?search={quote(search_query)}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1280, "height": 900},
        )
        page = await ctx.new_page()

        try:
            # Step 1: Search page
            await page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(1.5)

            # Click first search result (car model link)
            first_link = await page.query_selector(
                "a.car, .search-results a, .result a, table.data a, a[href*='/en/']"
            )
            if not first_link:
                logger.info("No search results on auto-data.net for '%s'", search_query)
                return {}

            href = await first_link.get_attribute("href")
            if not href:
                return {}
            if not href.startswith("http"):
                href = "https://www.auto-data.net" + href

            # Step 2: Model/generation page → find specific variant
            await page.goto(href, wait_until="domcontentloaded", timeout=20_000)
            await asyncio.sleep(1.5)

            # Try to click into the closest matching generation/variant
            variant_link = await page.query_selector(
                "table.data a, .car-versions a, .version a, article a"
            )
            if variant_link:
                v_href = await variant_link.get_attribute("href")
                if v_href:
                    if not v_href.startswith("http"):
                        v_href = "https://www.auto-data.net" + v_href
                    await page.goto(v_href, wait_until="domcontentloaded", timeout=20_000)
                    await asyncio.sleep(1.5)

            # Step 3: Parse specs table
            return await _parse_specs_table(page)

        except PWTimeout:
            logger.warning("auto-data.net timed out")
            return {}
        finally:
            await browser.close()


async def _parse_specs_table(page) -> dict:
    data: dict = {}

    rows = await page.query_selector_all(
        "table.data tr, .specs-table tr, .technical-data tr, table tr"
    )

    def norm_val(v: str) -> str:
        return v.strip().rstrip(".")

    for row in rows:
        cells = await row.query_selector_all("td, th")
        if len(cells) < 2:
            continue
        label = (await cells[0].inner_text()).strip().lower()
        value = norm_val(await cells[1].inner_text())
        if not value or value in ("-", "n/a", "—"):
            continue

        # Map labels to our schema
        if any(k in label for k in ("power", "leistung", "ps", "hp", "bhp")):
            m = re.search(r"(\d+)\s*(?:ps|hp|bhp|kw)", value, re.I)
            if m:
                data["power_ps"] = int(m.group(1))
        elif "displacement" in label or "hubraum" in label or "ccm" in label or "engine size" in label:
            data["engine_displacement"] = value
        elif "fuel consumption" in label or "verbrauch" in label or "consumption" in label:
            m = re.search(r"([\d.,]+)\s*l", value, re.I)
            if m:
                data["fuel_consumption"] = m.group(1).replace(",", ".")
        elif "co2" in label or "co₂" in label:
            m = re.search(r"(\d+)", value)
            if m:
                data["co2"] = m.group(1) + " g/km"
        elif "top speed" in label or "höchstgeschwind" in label or "vmax" in label:
            m = re.search(r"(\d+)", value)
            if m:
                data["top_speed"] = int(m.group(1))
        elif "0-100" in label or "0–100" in label or "acceleration" in label:
            m = re.search(r"([\d.,]+)\s*s", value, re.I)
            if m:
                data["acceleration"] = m.group(1).replace(",", ".")
        elif "curb weight" in label or "leergewicht" in label or "weight" in label:
            m = re.search(r"(\d+)", value.replace(",", "").replace(".", ""))
            if m:
                data["curb_weight"] = int(m.group(1))
        elif "cylinder" in label or "zylinder" in label:
            m = re.search(r"(\d+)", value)
            if m:
                data["cylinders"] = int(m.group(1))
        elif "fuel type" in label or "kraftstoff" in label:
            data["fuel_type"] = value
        elif "transmission" in label or "getriebe" in label:
            data["transmission"] = value
        elif "body" in label or "karosserie" in label:
            data["body_type"] = value
        elif "make" in label or "marke" in label:
            data["make"] = value.title()
        elif "model" in label and "make" not in label:
            if not data.get("model"):
                data["model"] = value
        elif "year" in label or "baujahr" in label:
            if not data.get("year"):
                data["year"] = value

    return data
