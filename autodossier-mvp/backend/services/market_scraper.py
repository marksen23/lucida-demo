"""
Market Price Scraper
====================
100 % httpx – no Playwright, no browser, no Chromium.

Sources:
  1. mobile.de     – DE market leader; parses __NEXT_DATA__ JSON + HTML fallback
  2. autoscout24.de – EU-wide; parses __NEXT_DATA__ JSON + HTML fallback

Both scrapers:
  - Retry up to 2× with 1 s / 2 s delay
  - Browser-like headers (UA, Accept, Accept-Language, Referer, …)
  - http/2 where available
  - Results cached 1 h (TTLCache, 300 slots)

Return structure (unchanged from previous version):
  {
    "avg_price": int | None,
    "min_price": int | None,
    "max_price": int | None,
    "listings": [
      {"title": str, "price": int, "mileage": str, "year": str,
       "source": str, "url": str | None},
      ...
    ]
  }
"""

import asyncio
import json
import logging
import re
from threading import Lock
from typing import Any
from urllib.parse import quote

import httpx
from cachetools import TTLCache

logger = logging.getLogger(__name__)

# ─── Cache ────────────────────────────────────────────────────────────────────

_cache: TTLCache = TTLCache(maxsize=300, ttl=3_600)   # 1 h
_lock = Lock()


def _cache_get(key: str) -> dict | None:
    with _lock:
        return _cache.get(key)


def _cache_set(key: str, value: dict) -> None:
    with _lock:
        _cache[key] = value


# ─── Shared constants ─────────────────────────────────────────────────────────

_MAX_LISTINGS = 3

_TIMEOUT = httpx.Timeout(connect=6, read=12, write=5, pool=2)

_BASE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en-US;q=0.7,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "DNT":             "1",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}


# ─── Public API ───────────────────────────────────────────────────────────────

async def scrape_market(make: str, model: str, year: str = "") -> dict[str, Any]:
    """Return market data dict. Never raises."""
    search_term = " ".join(filter(None, [make, model])).strip()
    if not search_term:
        return {}

    cache_key = f"{make}|{model}|{year}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.debug("Market cache hit: %s", cache_key)
        return cached

    for scraper_fn, label in [
        (_mobile_de,    "mobile.de"),
        (_autoscout24,  "autoscout24.de"),
    ]:
        try:
            result = await asyncio.wait_for(
                scraper_fn(make, model, year), timeout=28
            )
            if result.get("listings"):
                logger.info("Market: %d listings from %s for '%s'",
                            len(result["listings"]), label, search_term)
                _cache_set(cache_key, result)
                return result
            logger.info("Market: %s returned 0 listings for '%s'", label, search_term)
        except asyncio.TimeoutError:
            logger.warning("Market: %s timed out for '%s'", label, search_term)
        except Exception as exc:
            logger.warning("Market: %s error for '%s': %s", label, search_term, exc)

    return {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_price(text: str) -> int | None:
    """Parse German-formatted price like '12.500 €', '12500', '9.990,-'."""
    t = re.sub(r"[\s\xa0\u202f]", "", str(text))
    # German format: 12.500 (dot as thousands separator)
    m = re.search(r"(\d{1,3}(?:\.\d{3})+)", t)
    if m:
        val = int(m.group(1).replace(".", ""))
        return val if 500 < val < 500_000 else None
    # Plain 4-6 digit number
    m = re.search(r"\b(\d{4,6})\b", t)
    if m:
        val = int(m.group(1))
        return val if 500 < val < 500_000 else None
    return None


def _parse_km(text: str) -> str:
    m = re.search(r"([\d.,]+)\s*km", str(text), re.I)
    if m:
        return m.group(1).replace(".", "").replace(",", "")
    return ""


def _parse_year(text: str, fallback: str = "") -> str:
    m = re.search(r"\b(19[89]\d|20[012]\d)\b", str(text))
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


async def _fetch_with_retry(
    client: httpx.AsyncClient,
    url: str,
    max_retries: int = 2,
    extra_headers: dict | None = None,
) -> httpx.Response | None:
    """GET with up to max_retries retries on 429/5xx or transient errors."""
    headers = {**_BASE_HEADERS, **(extra_headers or {})}
    delays  = [1.0, 2.0]

    for attempt in range(max_retries + 1):
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                return resp
            if resp.status_code in (429, 503, 502) and attempt < max_retries:
                await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
                continue
            logger.info("HTTP %s fetching %s", resp.status_code, url)
            return None
        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            if attempt < max_retries:
                await asyncio.sleep(delays[min(attempt, len(delays) - 1)])
            else:
                raise exc

    return None


# ─── __NEXT_DATA__ parser (works for both mobile.de and autoscout24) ──────────

def _extract_next_data(html: str) -> dict | None:
    """Extract and parse the __NEXT_DATA__ JSON blob from a Next.js page."""
    m = re.search(
        r'<script\s+id=["\']__NEXT_DATA__["\'][^>]*>\s*(.*?)\s*</script>',
        html, re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def _walk_listings(obj: Any, out: list[dict], source: str, base_url: str,
                   year_fallback: str, depth: int = 0) -> None:
    """
    Recursively walk a JSON tree searching for objects that look like listings.
    Heuristic: an object qualifies if it has at least a price-like field.
    """
    if depth > 14 or len(out) >= 10:
        return

    if isinstance(obj, list):
        for item in obj:
            _walk_listings(item, out, source, base_url, year_fallback, depth + 1)
        return

    if not isinstance(obj, dict):
        return

    # ── Does this dict look like a listing? ──────────────────────────────────
    PRICE_KEYS  = {"price", "grossPrice", "amount", "priceAmount",
                   "finalPrice", "totalPrice", "formattedPrice"}
    TITLE_KEYS  = {"title", "vehicleTitle", "headline", "name",
                   "description", "vehicleName", "label"}
    LINK_KEYS   = {"url", "href", "link", "relativeUrl", "path",
                   "detailUrl", "vehicleUrl"}
    KM_KEYS     = {"mileage", "kilometrage", "km", "odometer",
                   "mileageValue", "mileageKm"}
    YEAR_KEYS   = {"year", "firstRegistration", "registrationYear",
                   "modelYear", "constructionYear"}

    price_val = next(
        (obj[k] for k in PRICE_KEYS if k in obj and obj[k] is not None), None
    )

    if price_val is not None:
        price = _parse_price(str(price_val))
        if price:
            title_raw = str(next((obj[k] for k in TITLE_KEYS if k in obj), ""))
            km_raw    = str(next((obj[k] for k in KM_KEYS    if k in obj), ""))
            year_raw  = str(next((obj[k] for k in YEAR_KEYS  if k in obj), ""))
            link_raw  = next((obj[k] for k in LINK_KEYS  if k in obj), None)

            full_text = f"{title_raw} {km_raw} {year_raw}"
            km   = _parse_km(km_raw or full_text)
            yr   = _parse_year(year_raw or full_text, year_fallback)
            href = str(link_raw) if link_raw else None
            if href and not href.startswith("http"):
                href = base_url + href

            out.append({
                "title":   (title_raw or "–")[:65],
                "price":   price,
                "mileage": km,
                "year":    yr,
                "source":  source,
                "url":     href,
            })
            return   # don't recurse into a listing object's sub-fields

    # Recurse into values
    for v in obj.values():
        _walk_listings(v, out, source, base_url, year_fallback, depth + 1)


def _regex_price_listings(html: str, source: str, year_fallback: str) -> list[dict]:
    """
    Last-resort HTML regex extraction.
    Finds price patterns and grabs text context around them.
    """
    listings = []
    strip_tags = re.compile(r'<[^>]+>')
    price_pat  = re.compile(r'\b(\d{1,3}(?:\.\d{3})+)\s*€')

    for m in price_pat.finditer(html):
        price = _parse_price(m.group(0))
        if not price:
            continue

        start   = max(0, m.start() - 400)
        snippet = strip_tags.sub(' ', html[start: m.end() + 80])
        snippet = re.sub(r'\s+', ' ', snippet).strip()

        km   = _parse_km(snippet)
        yr   = _parse_year(snippet, year_fallback)
        words = [w for w in snippet.split() if len(w) > 3 and not re.match(r'^\d', w)]
        title = " ".join(words[:8])[:65] or "–"

        listings.append({
            "title":   title,
            "price":   price,
            "mileage": km,
            "year":    yr,
            "source":  source,
            "url":     None,
        })
        if len(listings) >= 10:
            break

    return listings


# ─── Source 1: mobile.de ─────────────────────────────────────────────────────

async def _mobile_de(make: str, model: str, year: str) -> dict:
    search = " ".join(filter(None, [make, model]))
    url = (
        "https://suchen.mobile.de/fahrzeuge/search.html"
        f"?sText={quote(search)}&scopeId=C&isSearchRequest=true"
    )
    if year:
        url += f"&minFirstRegistrationDate={year}-01&maxFirstRegistrationDate={year}-12"

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        http2=True,
    ) as client:
        resp = await _fetch_with_retry(
            client, url,
            extra_headers={"Referer": "https://www.mobile.de/"},
        )

    if not resp:
        return {}

    html = resp.text
    listings: list[dict] = []

    # Strategy A – __NEXT_DATA__ JSON
    nd = _extract_next_data(html)
    if nd:
        _walk_listings(nd, listings, "mobile.de", "https://suchen.mobile.de", year)

    # Strategy B – HTML regex
    if not listings:
        listings = _regex_price_listings(html, "mobile.de", year)

    # Deduplicate by price
    seen: set[int] = set()
    unique = []
    for l in listings:
        if l["price"] not in seen:
            seen.add(l["price"])
            unique.append(l)

    return _aggregate(unique)


# ─── Source 2: autoscout24.de ─────────────────────────────────────────────────

def _as24_slug(s: str) -> str:
    """Convert make/model to autoscout24 path slug."""
    s = s.lower().strip()
    s = s.replace("mercedes-benz", "mercedes").replace("volkswagen", "vw")
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s


async def _autoscout24(make: str, model: str, year: str) -> dict:
    make_slug  = _as24_slug(make)
    model_slug = _as24_slug(model) if model else ""

    # Try path-based URL first (better indexed, less rate-limited)
    if model_slug:
        url = f"https://www.autoscout24.de/lst/{make_slug}/{model_slug}"
    else:
        url = f"https://www.autoscout24.de/lst/{make_slug}"

    if year:
        url += f"?fregfrom={year}&fregto={year}"

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        http2=True,
    ) as client:
        resp = await _fetch_with_retry(
            client, url,
            extra_headers={"Referer": "https://www.autoscout24.de/"},
        )

        # Fallback to query-based search
        if not resp:
            search = " ".join(filter(None, [make, model]))
            url2   = f"https://www.autoscout24.de/lst?q={quote(search)}"
            resp   = await _fetch_with_retry(
                client, url2,
                extra_headers={"Referer": "https://www.autoscout24.de/"},
            )

    if not resp:
        return {}

    html = resp.text
    listings: list[dict] = []

    # Strategy A – __NEXT_DATA__ JSON
    nd = _extract_next_data(html)
    if nd:
        _walk_listings(nd, listings, "autoscout24.de", "https://www.autoscout24.de", year)

    # Strategy B – HTML regex
    if not listings:
        listings = _regex_price_listings(html, "autoscout24.de", year)

    # Deduplicate
    seen: set[int] = set()
    unique = []
    for l in listings:
        if l["price"] not in seen:
            seen.add(l["price"])
            unique.append(l)

    return _aggregate(unique)
