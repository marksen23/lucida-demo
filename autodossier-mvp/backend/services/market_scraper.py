"""
Market Price Scraper
Searches mobile.de (primary) or autoscout24.de (fallback) for comparable listings.
Returns avg/min/max price and up to 3 listings.
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
_MAX_LISTINGS = 3


async def scrape_market(make: str, model: str, year: str = "") -> dict[str, Any]:
    """Return market data dict. Never raises."""
    if not PLAYWRIGHT_AVAILABLE or not make:
        return {}
    try:
        result = await asyncio.wait_for(_scrape_mobile_de(make, model, year), timeout=35)
        if result.get("listings"):
            return result
        return await asyncio.wait_for(_scrape_autoscout24(make, model, year), timeout=35)
    except asyncio.TimeoutError:
        logger.warning("market_scraper timeout")
        return {}
    except Exception as exc:
        logger.error("market_scraper error: %s", exc)
        return {}


def _parse_price(text: str) -> int | None:
    """Extract integer price from text like '12.500 €' or '12,500 EUR'."""
    text = text.replace(".", "").replace(",", "").replace("\xa0", "")
    m = re.search(r"(\d{3,6})", text)
    if m:
        val = int(m.group(1))
        return val if 500 < val < 500_000 else None
    return None


def _aggregate(listings: list[dict]) -> dict:
    prices = [l["price"] for l in listings if l.get("price")]
    if not prices:
        return {"listings": listings}
    return {
        "avg_price": round(sum(prices) / len(prices)),
        "min_price": min(prices),
        "max_price": max(prices),
        "listings": listings[:_MAX_LISTINGS],
    }


# ─── Source 1: mobile.de ─────────────────────────────────────────────────────

async def _scrape_mobile_de(make: str, model: str, year: str) -> dict:
    # Build search URL – mobile.de supports simple query params
    query = quote(f"{make} {model}")
    url = (
        f"https://suchen.mobile.de/fahrzeuge/search.html"
        f"?makeModelVariant1.makeId=&makeModelVariant1.modelDescription={query}"
        f"&isSearchRequest=true&scopeId=C"
    )
    if year:
        # Only keep first-registration year range
        url += f"&minFirstRegistrationDate={year}-01&maxFirstRegistrationDate={year}-12"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1400, "height": 900},
            locale="de-DE",
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await asyncio.sleep(2)

            # Accept cookies if banner present
            try:
                cookie_btn = await page.query_selector("button#consentAcceptAll, button[data-testid='cookie-accept']")
                if cookie_btn:
                    await cookie_btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            listings = []
            cards = await page.query_selector_all(
                "article.cBox, .result-item, .cBox-body, [data-testid='result-list-item']"
            )[:6]

            for card in cards:
                try:
                    title_el = await card.query_selector("h2, .headline, .vehicle-title, h3")
                    price_el = await card.query_selector(".price-block, .u-monetary-value, .price")
                    km_el    = await card.query_selector(".ml-5, .mileage, [data-testid='mileage']")
                    year_el  = await card.query_selector(".year, [data-testid='first-registration']")
                    link_el  = await card.query_selector("a")

                    title = (await title_el.inner_text()).strip() if title_el else f"{make} {model}"
                    price_text = (await price_el.inner_text()).strip() if price_el else ""
                    price = _parse_price(price_text)
                    km    = (await km_el.inner_text()).strip() if km_el else ""
                    yr    = (await year_el.inner_text()).strip() if year_el else year
                    href  = await link_el.get_attribute("href") if link_el else None

                    if href and not href.startswith("http"):
                        href = "https://suchen.mobile.de" + href

                    if price:
                        listings.append({
                            "title": title[:60],
                            "price": price,
                            "mileage": _parse_km(km),
                            "year": yr[:4] if yr else "",
                            "source": "mobile.de",
                            "url": href,
                        })
                except Exception as e:
                    logger.debug("card parse error: %s", e)

            return _aggregate(listings)

        except PWTimeout:
            logger.warning("mobile.de timed out")
            return {}
        finally:
            await browser.close()


# ─── Source 2: autoscout24.de (fallback) ─────────────────────────────────────

async def _scrape_autoscout24(make: str, model: str, year: str) -> dict:
    query = quote(f"{make} {model}")
    url = f"https://www.autoscout24.de/lst?q={query}&sort=relevance&desc=0&ustate=N%2CU&size=10"
    if year:
        url += f"&fregfrom={year}&fregto={year}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1400, "height": 900},
            locale="de-DE",
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await asyncio.sleep(2)

            # Accept cookies
            try:
                btn = await page.query_selector("button#_evidon-accept-all-button, button[data-testid='accept-all']")
                if btn:
                    await btn.click()
                    await asyncio.sleep(1)
            except Exception:
                pass

            listings = []
            cards = await page.query_selector_all(
                "article[data-testid='listing-item'], .ListItem_wrapper, .cldt-summary-full-item"
            )[:6]

            for card in cards:
                try:
                    title_el  = await card.query_selector("h2, .ListItem_title, [data-testid='listing-title']")
                    price_el  = await card.query_selector(".Price_price, [data-testid='listing-price'], .price")
                    miles_el  = await card.query_selector("[data-testid='listing-mileage'], .mileage")
                    year_el   = await card.query_selector("[data-testid='listing-firstregistration'], .year")
                    link_el   = await card.query_selector("a")

                    title = (await title_el.inner_text()).strip() if title_el else f"{make} {model}"
                    price_text = (await price_el.inner_text()).strip() if price_el else ""
                    price = _parse_price(price_text)
                    km    = (await miles_el.inner_text()).strip() if miles_el else ""
                    yr    = (await year_el.inner_text()).strip() if year_el else year
                    href  = await link_el.get_attribute("href") if link_el else None
                    if href and not href.startswith("http"):
                        href = "https://www.autoscout24.de" + href

                    if price:
                        listings.append({
                            "title": title[:60],
                            "price": price,
                            "mileage": _parse_km(km),
                            "year": yr[:4] if yr else "",
                            "source": "autoscout24.de",
                            "url": href,
                        })
                except Exception as e:
                    logger.debug("AS24 card parse error: %s", e)

            return _aggregate(listings)

        except PWTimeout:
            logger.warning("autoscout24 timed out")
            return {}
        finally:
            await browser.close()


def _parse_km(text: str) -> str:
    m = re.search(r"([\d.,]+)\s*km", text, re.I)
    if m:
        return m.group(1).replace(".", "").replace(",", "")
    return ""
