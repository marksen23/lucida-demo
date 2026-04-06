"""
Market Price Scraper
====================
Sources (in priority order):
  1. mobile.de       — Germany's largest car portal, text-search URL
  2. Kleinanzeigen.de — Formerly eBay Kleinanzeigen, easier to parse
  3. autoscout24.de  — Fallback

Strategy: wide-net approach — extract all price-like numbers from each card
using regex as backup to CSS selectors, so selector drift doesn't break us.
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

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
_MAX_LISTINGS = 3


# ─── Public API ───────────────────────────────────────────────────────────────

async def scrape_market(make: str, model: str, year: str = "") -> dict[str, Any]:
    """Return market data dict. Never raises."""
    if not PLAYWRIGHT_AVAILABLE or not make:
        return {}

    for scraper, label in [
        (_scrape_mobile_de,    "mobile.de"),
        (_scrape_kleinanzeigen,"Kleinanzeigen"),
        (_scrape_autoscout24,  "autoscout24"),
    ]:
        try:
            result = await asyncio.wait_for(
                scraper(make, model, year), timeout=40
            )
            if result.get("listings"):
                logger.info("Market data from %s: %d listings", label, len(result["listings"]))
                return result
        except asyncio.TimeoutError:
            logger.warning("%s timed out", label)
        except Exception as exc:
            logger.warning("%s error: %s", label, exc)

    return {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_price(text: str) -> int | None:
    """Extract price from German-formatted text like '12.500 €' or '9.990,-'."""
    # Remove thousands separators (German: dot), keep value
    t = text.replace("\xa0", " ").replace("\u202f", "")
    # Pattern: 3-6 digit number (optionally with . thousands separator)
    m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{4,6})", t)
    if m:
        val = int(m.group(1).replace(".", ""))
        return val if 500 < val < 500_000 else None
    return None


def _parse_km(text: str) -> str:
    m = re.search(r"([\d.,]+)\s*km", text, re.I)
    if m:
        return m.group(1).replace(".", "").replace(",", "")
    return ""


def _aggregate(listings: list[dict]) -> dict:
    prices = [l["price"] for l in listings if l.get("price")]
    if not prices:
        return {"listings": listings}
    return {
        "avg_price": round(sum(prices) / len(prices)),
        "min_price": min(prices),
        "max_price": max(prices),
        "listings":  listings[:_MAX_LISTINGS],
    }


async def _accept_cookies(page, selectors: list[str]):
    """Try clicking a cookie consent button from a list of selectors."""
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await btn.click()
                await asyncio.sleep(1)
                return
        except Exception:
            pass


async def _extract_cards_text(page, card_selectors: str) -> list[tuple[str, str | None]]:
    """
    Return list of (full_text, href) for each matching card.
    Falls back to extracting all text blobs containing price indicators.
    """
    cards = await page.query_selector_all(card_selectors)
    results = []
    for card in cards[:8]:
        try:
            text = await card.inner_text()
            link = await card.query_selector("a[href]")
            href = (await link.get_attribute("href")) if link else None
            results.append((text, href))
        except Exception:
            pass
    return results


# ─── Source 1: mobile.de ─────────────────────────────────────────────────────

async def _scrape_mobile_de(make: str, model: str, year: str) -> dict:
    search_term = f"{make} {model}"
    if year:
        search_term += f" {year}"
    url = (
        f"https://suchen.mobile.de/fahrzeuge/search.html"
        f"?sText={quote(search_term)}"
        f"&scopeId=C&isSearchRequest=true&ref=srpHead"
    )

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_UA, viewport={"width": 1400, "height": 900},
            locale="de-DE", timezone_id="Europe/Berlin",
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await asyncio.sleep(2.5)

            await _accept_cookies(page, [
                "button#consentAcceptAll",
                "button[data-testid='mde-consent-accept-btn']",
                "button.mde-consent-accept-btn",
                ".consent-banner button[class*='accept']",
                "button:has-text('Alle akzeptieren')",
                "button:has-text('Zustimmen')",
            ])
            await asyncio.sleep(1.5)

            # Wait for results
            try:
                await page.wait_for_selector(
                    ".result-list-item, article[data-item-id], .cBox",
                    timeout=8_000,
                )
            except Exception:
                pass

            raw_cards = await _extract_cards_text(
                page,
                ".result-list-item, article[data-item-id], .cBox-body--resultItem",
            )

            listings = _parse_cards_generic(raw_cards, make, model, year, "mobile.de",
                                            base_url="https://suchen.mobile.de")
            return _aggregate(listings)

        except PWTimeout:
            logger.warning("mobile.de timed out")
            return {}
        finally:
            await browser.close()


# ─── Source 2: Kleinanzeigen.de ──────────────────────────────────────────────

async def _scrape_kleinanzeigen(make: str, model: str, year: str) -> dict:
    search_term = f"{make} {model}"
    url = f"https://www.kleinanzeigen.de/s-autos/q-{quote(search_term).replace('%20', '-')}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_UA, viewport={"width": 1280, "height": 900},
            locale="de-DE",
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            await asyncio.sleep(2)

            await _accept_cookies(page, [
                "button#gdpr-banner-accept",
                "button[data-testid='gdpr-banner-accept']",
                "button:has-text('Alle akzeptieren')",
                "#gdpr-banner-cta",
            ])
            await asyncio.sleep(1)

            try:
                await page.wait_for_selector("article.aditem, li.ad-listitem", timeout=6_000)
            except Exception:
                pass

            raw_cards = await _extract_cards_text(
                page, "article.aditem, li.ad-listitem"
            )

            listings = _parse_cards_generic(raw_cards, make, model, year, "kleinanzeigen.de",
                                            base_url="https://www.kleinanzeigen.de")
            return _aggregate(listings)

        except PWTimeout:
            logger.warning("Kleinanzeigen timed out")
            return {}
        finally:
            await browser.close()


# ─── Source 3: autoscout24.de ────────────────────────────────────────────────

async def _scrape_autoscout24(make: str, model: str, year: str) -> dict:
    # Use path-based URL which is less aggressively bot-checked
    make_slug  = make.lower().replace(" ", "-").replace("-benz", "").replace("ü","ue")
    model_slug = model.lower().replace(" ", "-").replace("/","-")
    url = f"https://www.autoscout24.de/lst/{make_slug}/{model_slug}"
    if year:
        url += f"?fregfrom={year}&fregto={year}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_UA, viewport={"width": 1400, "height": 900},
            locale="de-DE",
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await asyncio.sleep(3)

            await _accept_cookies(page, [
                "button#_evidon-accept-all-button",
                "button[data-testid='accept-all-close']",
                "button:has-text('Alle akzeptieren')",
                "button:has-text('Akzeptieren')",
                ".sc-button-primary",
            ])
            await asyncio.sleep(2)

            try:
                await page.wait_for_selector(
                    "article[data-guid], article[data-testid='listing-item'], .cldt-summary-full-item",
                    timeout=8_000,
                )
            except Exception:
                pass

            raw_cards = await _extract_cards_text(
                page,
                "article[data-guid], article[data-testid='listing-item'], .cldt-summary-full-item",
            )

            listings = _parse_cards_generic(raw_cards, make, model, year, "autoscout24.de",
                                            base_url="https://www.autoscout24.de")
            return _aggregate(listings)

        except PWTimeout:
            logger.warning("autoscout24 timed out")
            return {}
        finally:
            await browser.close()


# ─── Generic Card Parser ──────────────────────────────────────────────────────

def _parse_cards_generic(
    raw_cards: list[tuple[str, str | None]],
    make: str,
    model: str,
    year: str,
    source: str,
    base_url: str = "",
) -> list[dict]:
    """
    Parse (text, href) pairs into listing dicts.
    Uses regex on full card text — resilient to CSS selector drift.
    """
    listings = []

    for text, href in raw_cards:
        if not text.strip():
            continue

        lines = [l.strip() for l in text.splitlines() if l.strip()]

        # Price: look for Euro amounts
        price = None
        for line in lines:
            if "€" in line or "EUR" in line or ",-" in line:
                p = _parse_price(line)
                if p:
                    price = p
                    break
        if not price:
            # Try any number that looks like a price (4-6 digits)
            for line in lines:
                p = _parse_price(line)
                if p:
                    price = p
                    break

        if not price:
            continue

        # Title: first substantial line or make+model
        title = next(
            (l for l in lines if len(l) > 8 and not re.match(r"^\d", l) and "€" not in l),
            f"{make} {model}",
        )[:65]

        # Mileage
        km = ""
        for line in lines:
            km = _parse_km(line)
            if km:
                break

        # Year
        yr = year
        for line in lines:
            m = re.search(r"\b(19[89]\d|20[012]\d)\b", line)
            if m:
                yr = m.group(1)
                break

        # Normalise href
        full_href: str | None = None
        if href:
            full_href = href if href.startswith("http") else base_url + href

        listings.append({
            "title":   title,
            "price":   price,
            "mileage": km,
            "year":    yr,
            "source":  source,
            "url":     full_href,
        })

    return listings
