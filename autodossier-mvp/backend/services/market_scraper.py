"""
Market Price Scraper
====================
Strategy: httpx-first (no browser, fast, avoids Playwright cold-start cost),
then Playwright as fallback.

Sources:
  1. mobile.de    – parses __NEXT_DATA__ JSON blob embedded in HTML
  2. Kleinanzeigen.de – server-rendered HTML, simpler to parse
  3. autoscout24.de   – Playwright fallback (bot-protected, last resort)

The scraper works even if only 'make' is known (model/year optional).
"""

import asyncio
import json
import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_MAX_LISTINGS = 3

_HEADERS = {
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.6",
    "Accept-Encoding": "gzip, deflate, br",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


# ─── Public API ───────────────────────────────────────────────────────────────

async def scrape_market(make: str, model: str, year: str = "") -> dict[str, Any]:
    """Return market data dict. Never raises. Works even with empty make."""
    search_term = " ".join(filter(None, [make, model])).strip()
    if not search_term:
        return {}

    for scraper, label in [
        (_httpx_mobile_de,     "mobile.de"),
        (_httpx_kleinanzeigen, "Kleinanzeigen"),
        (_playwright_autoscout24, "autoscout24"),
    ]:
        try:
            result = await asyncio.wait_for(
                scraper(make, model, year), timeout=35
            )
            if result.get("listings"):
                logger.info("Market: %d listings from %s", len(result["listings"]), label)
                return result
            logger.info("Market: %s returned 0 listings", label)
        except asyncio.TimeoutError:
            logger.warning("Market: %s timed out", label)
        except Exception as exc:
            logger.warning("Market: %s error: %s", label, exc)

    return {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_price(text: str) -> int | None:
    t = text.replace("\xa0", "").replace("\u202f", "").replace(" ", "")
    # German thousands: 12.500 or 12500 or 12.500,-
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


def _extract_year(text: str, fallback: str = "") -> str:
    m = re.search(r"\b(19[89]\d|20[012]\d)\b", text)
    return m.group(1) if m else fallback


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


# ─── Source 1: mobile.de via httpx ───────────────────────────────────────────

async def _httpx_mobile_de(make: str, model: str, year: str) -> dict:
    search = " ".join(filter(None, [make, model]))
    url = (
        f"https://suchen.mobile.de/fahrzeuge/search.html"
        f"?sText={quote(search)}&scopeId=C&isSearchRequest=true"
    )
    if year:
        url += f"&minFirstRegistrationDate={year}-01&maxFirstRegistrationDate={year}-12"

    async with httpx.AsyncClient(
        timeout=15, follow_redirects=True, headers=_HEADERS
    ) as client:
        resp = await client.get(url, headers={**_HEADERS, "Referer": "https://www.mobile.de/"})

    if resp.status_code != 200:
        logger.info("mobile.de returned HTTP %s", resp.status_code)
        return {}

    html = resp.text

    # Strategy A: parse embedded __NEXT_DATA__ JSON (React SSR data blob)
    listings = _parse_next_data_mobile(html, make, model, year)
    if listings:
        return _aggregate(listings)

    # Strategy B: parse HTML cards with regex
    listings = _parse_html_cards_mobile(html, make, model, year)
    return _aggregate(listings)


def _parse_next_data_mobile(html: str, make: str, model: str, year: str) -> list[dict]:
    """Extract listings from mobile.de's __NEXT_DATA__ SSR JSON blob."""
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
                  html, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []

    # Walk the JSON tree looking for listing arrays
    listings = []
    _walk_for_listings(data, listings, make, model, year)
    return listings


def _walk_for_listings(obj, listings: list, make: str, model: str, year: str, depth: int = 0):
    if depth > 12 or len(listings) >= 8:
        return
    if isinstance(obj, list):
        for item in obj:
            _walk_for_listings(item, listings, make, model, year, depth + 1)
    elif isinstance(obj, dict):
        # Heuristic: a listing dict has price and some title-like key
        price_keys  = {"price", "grossPrice", "amount", "priceFormatted"}
        title_keys  = {"title", "vehicleName", "headline", "description"}
        link_keys   = {"url", "link", "href", "relativeUrl", "path"}
        km_keys     = {"mileage", "kilometrage", "km"}

        has_price = any(k in obj for k in price_keys)
        has_title = any(k in obj for k in title_keys)

        if has_price and has_title:
            raw_price = next((obj[k] for k in price_keys if k in obj), None)
            raw_title = next((obj[k] for k in title_keys if k in obj), "")
            raw_km    = next((obj[k] for k in km_keys    if k in obj), "")
            raw_link  = next((obj[k] for k in link_keys  if k in obj), None)

            price = _parse_price(str(raw_price or ""))
            if price:
                km   = _parse_km(str(raw_km)) if raw_km else ""
                yr   = _extract_year(str(raw_title) + str(raw_km), year)
                href = str(raw_link) if raw_link else None
                if href and not href.startswith("http"):
                    href = "https://suchen.mobile.de" + href
                listings.append({
                    "title":   str(raw_title)[:65],
                    "price":   price,
                    "mileage": km,
                    "year":    yr,
                    "source":  "mobile.de",
                    "url":     href,
                })
        else:
            for v in obj.values():
                _walk_for_listings(v, listings, make, model, year, depth + 1)


def _parse_html_cards_mobile(html: str, make: str, model: str, year: str) -> list[dict]:
    """Regex-based fallback: find price blocks adjacent to title-like text."""
    listings = []
    # Find all price occurrences
    price_pattern = re.compile(r'([\d]{1,3}(?:\.[\d]{3})+)\s*€')
    for m in price_pattern.finditer(html):
        raw_price = m.group(0)
        price = _parse_price(raw_price)
        if not price:
            continue

        # Grab surrounding context (500 chars before price)
        start = max(0, m.start() - 500)
        snippet = html[start:m.end() + 100]
        snippet_clean = re.sub(r'<[^>]+>', ' ', snippet)   # strip HTML tags
        snippet_clean = re.sub(r'\s+', ' ', snippet_clean).strip()

        km   = _parse_km(snippet_clean)
        yr   = _extract_year(snippet_clean, year)
        # Title: first substantial text segment in snippet
        words = [w for w in snippet_clean.split() if len(w) > 3 and not w.startswith("http")]
        title = " ".join(words[:8]) if words else f"{make} {model}"

        listings.append({
            "title":   title[:65],
            "price":   price,
            "mileage": km,
            "year":    yr,
            "source":  "mobile.de",
            "url":     None,
        })
        if len(listings) >= 8:
            break

    return listings


# ─── Source 2: Kleinanzeigen.de via httpx ────────────────────────────────────

async def _httpx_kleinanzeigen(make: str, model: str, year: str) -> dict:
    search = "-".join(filter(None, [make, model])).replace(" ", "-")
    url = f"https://www.kleinanzeigen.de/s-autos/{quote(search.lower())}/k0"

    async with httpx.AsyncClient(
        timeout=15, follow_redirects=True, headers=_HEADERS
    ) as client:
        resp = await client.get(url, headers={
            **_HEADERS, "Referer": "https://www.kleinanzeigen.de/"
        })

    if resp.status_code != 200:
        logger.info("Kleinanzeigen returned HTTP %s", resp.status_code)
        return {}

    html = resp.text
    listings = _parse_kleinanzeigen_html(html, make, model, year)
    return _aggregate(listings)


def _parse_kleinanzeigen_html(html: str, make: str, model: str, year: str) -> list[dict]:
    """
    Kleinanzeigen.de is server-side rendered.
    Listings are in <article class="aditem"> blocks.
    """
    listings = []

    # Extract article blocks
    articles = re.findall(
        r'<article[^>]*class="[^"]*aditem[^"]*"[^>]*>(.*?)</article>',
        html, re.DOTALL | re.IGNORECASE
    )
    if not articles:
        # Fallback: try li elements
        articles = re.findall(
            r'<li[^>]*class="[^"]*ad-listitem[^"]*"[^>]*>(.*?)</li>',
            html, re.DOTALL | re.IGNORECASE
        )

    for art in articles[:10]:
        clean = re.sub(r'<[^>]+>', ' ', art)
        clean = re.sub(r'\s+', ' ', clean).strip()

        price = _parse_price(clean)
        if not price:
            continue

        km   = _parse_km(clean)
        yr   = _extract_year(clean, year)

        # Title: first non-number, non-short segment
        words = [w for w in clean.split() if len(w) > 3 and not re.match(r'^\d', w)]
        title = " ".join(words[:8]) if words else f"{make} {model}"

        # Extract href
        href_m = re.search(r'href="(/s-anzeige/[^"]+)"', art)
        href = ("https://www.kleinanzeigen.de" + href_m.group(1)) if href_m else None

        listings.append({
            "title":   title[:65],
            "price":   price,
            "mileage": km,
            "year":    yr,
            "source":  "kleinanzeigen.de",
            "url":     href,
        })

    return listings


# ─── Source 3: autoscout24 via Playwright (fallback) ─────────────────────────

async def _playwright_autoscout24(make: str, model: str, year: str) -> dict:
    if not PLAYWRIGHT_AVAILABLE:
        return {}

    make_slug  = re.sub(r'[^a-z0-9]', '-', make.lower()).strip('-')
    model_slug = re.sub(r'[^a-z0-9]', '-', model.lower()).strip('-') if model else ""
    path = f"/lst/{make_slug}/{model_slug}" if model_slug else f"/lst/{make_slug}"
    url  = f"https://www.autoscout24.de{path}"
    if year:
        url += f"?fregfrom={year}&fregto={year}"

    try:
        from playwright.async_api import async_playwright, TimeoutError as PWTimeout
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            ctx = await browser.new_context(
                user_agent=_HEADERS["User-Agent"],
                viewport={"width": 1400, "height": 900},
                locale="de-DE",
            )
            page = await ctx.new_page()
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=25_000)
                await asyncio.sleep(2.5)

                # Accept cookies
                for sel in [
                    "button#_evidon-accept-all-button",
                    "button[data-testid='accept-all-close']",
                    "button:has-text('Alle akzeptieren')",
                ]:
                    try:
                        btn = await page.query_selector(sel)
                        if btn and await btn.is_visible():
                            await btn.click()
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        pass

                await asyncio.sleep(2)
                html = await page.content()
                listings = _parse_autoscout24_html(html, make, model, year)
                return _aggregate(listings)

            except PWTimeout:
                return {}
            finally:
                await browser.close()
    except Exception as exc:
        logger.warning("autoscout24 Playwright error: %s", exc)
        return {}


def _parse_autoscout24_html(html: str, make: str, model: str, year: str) -> list[dict]:
    """Extract price data from autoscout24 HTML using __NEXT_DATA__ or regex."""
    # Try __NEXT_DATA__ first
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            listings = []
            _walk_for_listings(data, listings, make, model, year)
            if listings:
                return listings
        except Exception:
            pass

    # Regex fallback
    listings = []
    price_pat = re.compile(r'([\d]{1,3}(?:\.[\d]{3})+)\s*€')
    for pm in price_pat.finditer(html):
        price = _parse_price(pm.group(0))
        if not price:
            continue
        start   = max(0, pm.start() - 400)
        snippet = re.sub(r'<[^>]+>', ' ', html[start:pm.end() + 50])
        snippet = re.sub(r'\s+', ' ', snippet).strip()
        km  = _parse_km(snippet)
        yr  = _extract_year(snippet, year)
        words = [w for w in snippet.split() if len(w) > 3 and not re.match(r'^\d', w)]
        listings.append({
            "title":   (" ".join(words[:8]) or f"{make} {model}")[:65],
            "price":   price,
            "mileage": km,
            "year":    yr,
            "source":  "autoscout24.de",
            "url":     None,
        })
        if len(listings) >= 8:
            break
    return listings
