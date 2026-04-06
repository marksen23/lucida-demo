"""
ADAC Live-Scraper
Scrapes adac.de/rund-ums-fahrzeug/auto-kaufen-verkaufen/autokosten/ directly
to get monthly cost estimates for a given vehicle class.

Falls back to the static heuristic table in adac_parser.py if scraping fails.
"""

import asyncio
import logging
import re
from typing import Any

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

# ADAC Autokosten page (no login required, publicly accessible)
_ADAC_URL = "https://www.adac.de/rund-ums-fahrzeug/auto-kaufen-verkaufen/autokosten/autokosten-rechner/"


async def scrape_adac_costs(make: str, model: str, year: str = "") -> dict[str, Any] | None:
    """
    Try to get ADAC cost data live from adac.de.
    Returns cost dict or None if unavailable.
    """
    if not PLAYWRIGHT_AVAILABLE:
        return None
    try:
        return await asyncio.wait_for(_scrape(make, model, year), timeout=40)
    except asyncio.TimeoutError:
        logger.warning("ADAC scraper timed out")
        return None
    except Exception as exc:
        logger.error("ADAC scraper error: %s", exc)
        return None


async def _scrape(make: str, model: str, year: str) -> dict | None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1440, "height": 900},
            locale="de-DE",
        )
        page = await ctx.new_page()

        try:
            await page.goto(_ADAC_URL, wait_until="domcontentloaded", timeout=25_000)
            await asyncio.sleep(2)

            # Accept cookie banner
            for selector in [
                "button#consentAcceptAll",
                "button[data-tracking='CookieBanner_AcceptAll']",
                "button.accept-all",
                "[aria-label*='Alle akzeptieren']",
                "[aria-label*='Akzeptieren']",
            ]:
                try:
                    btn = await page.query_selector(selector)
                    if btn:
                        await btn.click()
                        await asyncio.sleep(1)
                        break
                except Exception:
                    pass

            # Try to search/select vehicle
            # ADAC Autokosten-Rechner has dropdown selects for Hersteller / Modell
            await _select_vehicle(page, make, model, year)
            await asyncio.sleep(3)

            # Parse the result table / cost breakdown
            return await _parse_cost_result(page)

        except PWTimeout:
            logger.warning("ADAC page timed out")
            return None
        finally:
            await browser.close()


async def _select_vehicle(page, make: str, model: str, year: str):
    """Try to navigate ADAC Autokosten-Rechner dropdowns."""
    make_lower = make.lower()

    # Try select elements first (dropdown-based UI)
    try:
        # Hersteller select
        hersteller_sel = await page.query_selector(
            "select[name*='hersteller'], select[name*='make'], select[aria-label*='Hersteller'], select#hersteller"
        )
        if hersteller_sel:
            options = await hersteller_sel.query_selector_all("option")
            for opt in options:
                val = (await opt.get_attribute("value") or "").lower()
                txt = (await opt.inner_text()).lower()
                if make_lower in val or make_lower in txt:
                    await hersteller_sel.select_option(value=await opt.get_attribute("value"))
                    await asyncio.sleep(1.5)
                    break

        # Modell select (may be populated after Hersteller selection)
        modell_sel = await page.query_selector(
            "select[name*='modell'], select[name*='model'], select[aria-label*='Modell'], select#modell"
        )
        if modell_sel and model:
            model_lower = model.lower()
            options = await modell_sel.query_selector_all("option")
            for opt in options:
                val = (await opt.get_attribute("value") or "").lower()
                txt = (await opt.inner_text()).lower()
                if model_lower in val or model_lower in txt:
                    await modell_sel.select_option(value=await opt.get_attribute("value"))
                    await asyncio.sleep(1.5)
                    break

        # Submit / Berechnen button
        submit = await page.query_selector(
            "button[type='submit'], button:has-text('Berechnen'), button:has-text('Suchen'), button:has-text('Anzeigen')"
        )
        if submit:
            await submit.click()
            await asyncio.sleep(3)

    except Exception as exc:
        logger.debug("Vehicle select error: %s", exc)


async def _parse_cost_result(page) -> dict | None:
    """Extract cost breakdown from ADAC result page."""
    data = {}

    # Try structured result containers
    result_selectors = [
        ".autokosten__result",
        ".kosten-result",
        ".cost-result",
        "[class*='result']",
        "[class*='kosten']",
        "table",
    ]

    page_text = await page.evaluate("() => document.body.innerText")

    # Pattern-based extraction from page text
    patterns = {
        "fuel_monthly": [
            r"kraftstoff[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"benzin[kosten]{0,6}[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"fuel[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
        ],
        "insurance_monthly": [
            r"versicherung[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"haftpflicht[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
        ],
        "tax_monthly": [
            r"kfz.?steuer[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"steuer[kosten]{0,6}[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
        ],
        "maintenance_monthly": [
            r"wartung[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"reparatur[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"werkstatt[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
        ],
        "depreciation_monthly": [
            r"wertverlust[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"wertminderung[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
        ],
        "total_monthly": [
            r"gesamt[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"gesamtkosten[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
            r"monatlich[^\d]{0,20}(\d+[.,]\d+|\d+)\s*€",
        ],
    }

    for field, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, page_text, re.I)
            if m:
                try:
                    data[field] = float(m.group(1).replace(",", "."))
                    break
                except ValueError:
                    pass

    # Also try table rows
    rows = await page.query_selector_all("table tr, .cost-row, .kosten-row, [class*='cost-item']")
    for row in rows:
        try:
            txt = await row.inner_text()
            txt_low = txt.lower()
            m_val = re.search(r"(\d+[.,]\d+)\s*€", txt)
            if not m_val:
                continue
            val = float(m_val.group(1).replace(",", "."))

            if "kraftstoff" in txt_low or "benzin" in txt_low:
                data.setdefault("fuel_monthly", val)
            elif "versicherung" in txt_low:
                data.setdefault("insurance_monthly", val)
            elif "steuer" in txt_low:
                data.setdefault("tax_monthly", val)
            elif "wartung" in txt_low or "reparatur" in txt_low:
                data.setdefault("maintenance_monthly", val)
            elif "wertverlust" in txt_low:
                data.setdefault("depreciation_monthly", val)
            elif "gesamt" in txt_low:
                data.setdefault("total_monthly", val)
        except Exception:
            pass

    if len(data) < 2:
        return None

    if "total_monthly" not in data and len(data) >= 2:
        data["total_monthly"] = round(sum(
            v for k, v in data.items() if k != "total_monthly"
        ))

    data["source"] = "adac.de (live)"
    return data
