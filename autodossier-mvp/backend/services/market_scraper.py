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
    """Parse German-formatted price like '12.500 €', '12500', '9.990,-', '45000 EUR'."""
    # Strip currency labels and noise first
    t = re.sub(r"[\s\xa0\u202f]", "", str(text))
    t = re.sub(r"(?i)(eur|chf|gbp)", "", t)
    # German format: 12.500 (dot as thousands separator)
    m = re.search(r"(\d{1,3}(?:\.\d{3})+)", t)
    if m:
        val = int(m.group(1).replace(".", ""))
        return val if 500 < val < 500_000 else None
    # Plain 4-6 digit number (no thousands sep)
    m = re.search(r"(?<!\d)(\d{4,6})(?!\d)", t)
    if m:
        val = int(m.group(1))
        return val if 500 < val < 500_000 else None
    return None


def _parse_km(text: str) -> str:
    s = str(text).strip()
    # With explicit "km" unit: "150.000 km", "150,000 km", "150000km"
    m = re.search(r"([\d.,]+)\s*km", s, re.I)
    if m:
        return m.group(1).replace(".", "").replace(",", "")
    # Plain numeric from JSON – accept 3-6 digits (1 000 – 999 999 km)
    # Handles: "85000", "1.234" (DE thousands), "1,234" (US thousands)
    stripped = s.replace(".", "").replace(",", "")
    if re.fullmatch(r"\d{3,6}", stripped):
        return stripped
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


def _resolve_price(obj: dict) -> int | None:
    """
    Try to extract a price from a dict that may contain it directly or
    one level nested, e.g. {"price": {"amount": 22900}} or {"price": 22900}.
    """
    PRICE_KEYS = ("price", "grossPrice", "amount", "priceAmount",
                  "finalPrice", "totalPrice", "formattedPrice", "value")
    for k in PRICE_KEYS:
        v = obj.get(k)
        if v is None:
            continue
        if isinstance(v, (int, float)):
            p = _parse_price(str(v))
            if p:
                return p
        if isinstance(v, str):
            p = _parse_price(v)
            if p:
                return p
        if isinstance(v, dict):
            # one level deeper
            for kk in PRICE_KEYS:
                vv = v.get(kk)
                if vv is not None:
                    p = _parse_price(str(vv))
                    if p:
                        return p
    return None


def _walk_listings(obj: Any, out: list[dict], source: str, base_url: str,
                   year_fallback: str, depth: int = 0,
                   fallback_title: str = "") -> None:
    """
    Recursively walk a JSON tree searching for objects that look like listings.
    A listing dict must have a resolvable price AND at least one other
    listing-like field (title, mileage, year, …).
    """
    if depth > 14 or len(out) >= 10:
        return

    if isinstance(obj, list):
        for item in obj:
            _walk_listings(item, out, source, base_url, year_fallback, depth + 1, fallback_title)
        return

    if not isinstance(obj, dict):
        return

    TITLE_KEYS = ("title", "vehicleTitle", "headline", "name",
                  "description", "vehicleName", "label", "offerTitle")
    LINK_KEYS  = ("url", "href", "link", "relativeUrl", "path",
                  "detailUrl", "vehicleUrl", "listingUrl")
    KM_KEYS    = ("mileage", "kilometrage", "km", "odometer",
                  "mileageValue", "mileageKm", "kilometer")
    YEAR_KEYS  = ("year", "firstRegistration", "registrationYear",
                  "modelYear", "constructionYear", "firstRegYear")

    price = _resolve_price(obj)

    if price is not None:
        # Only treat as listing if there is at least one other relevant key
        has_meta = any(k in obj for k in (*TITLE_KEYS, *KM_KEYS, *YEAR_KEYS, *LINK_KEYS))
        if has_meta:
            title_raw = str(next((obj[k] for k in TITLE_KEYS if k in obj), ""))
            km_raw    = str(next((obj[k] for k in KM_KEYS    if k in obj), ""))
            year_raw  = str(next((obj[k] for k in YEAR_KEYS  if k in obj), ""))
            link_raw  = next((obj[k] for k in LINK_KEYS  if k in obj), None)

            # Build title from nested vehicle/car sub-object when no direct title
            if not title_raw.strip():
                for sub_key in ("vehicle", "car", "offer", "listing", "article"):
                    sub = obj.get(sub_key)
                    if isinstance(sub, dict):
                        mk = sub.get("make") or sub.get("brand") or sub.get("manufacturer") or ""
                        mo = sub.get("model") or ""
                        tr = sub.get("trim") or sub.get("version") or sub.get("variant") or ""
                        candidate = " ".join(filter(None, [str(mk), str(mo), str(tr)])).strip()
                        if candidate:
                            title_raw = candidate
                            # also grab km/year from same sub-obj if not found yet
                            if not km_raw:
                                km_raw = str(next((sub[k] for k in KM_KEYS if k in sub), ""))
                            if not year_raw:
                                year_raw = str(next((sub[k] for k in YEAR_KEYS if k in sub), ""))
                            break

            km = _parse_km(km_raw)
            yr = _parse_year(year_raw or f"{title_raw} {km_raw}", year_fallback)
            href = str(link_raw) if link_raw else None
            if href and not href.startswith("http"):
                href = base_url + href

            out.append({
                "title":   (title_raw.strip() or fallback_title or "–")[:65],
                "price":   price,
                "mileage": km,
                "year":    yr,
                "source":  source,
                "url":     href,
            })
            return  # don't recurse further into a confirmed listing object

    # Recurse into all values
    for v in obj.values():
        _walk_listings(v, out, source, base_url, year_fallback, depth + 1, fallback_title)


_BRAND_PAT = re.compile(
    r'\b(BMW|Mercedes|Audi|Volkswagen|VW|Porsche|Opel|Ford|Toyota|Honda|'
    r'Hyundai|Kia|Renault|Peugeot|Citro[eë]n|Seat|Skoda|Volvo|Nissan|'
    r'Mazda|Mitsubishi|Suzuki|Fiat|Alfa Romeo|Jeep|Land Rover|Jaguar)\b',
    re.I,
)


def _regex_price_listings(html: str, source: str, year_fallback: str,
                          make: str = "", model: str = "") -> list[dict]:
    """
    Last-resort HTML regex extraction.
    Finds German price patterns and builds a title from nearby brand names.
    """
    listings = []
    strip_tags = re.compile(r'<[^>]+>')
    price_pat  = re.compile(r'(\d{1,3}(?:\.\d{3})+)\s*[€]')

    for pm in price_pat.finditer(html):
        price = _parse_price(pm.group(0))
        if not price:
            continue

        # Context window: 600 chars before, 100 after
        start   = max(0, pm.start() - 600)
        snippet = strip_tags.sub(' ', html[start: pm.end() + 100])
        snippet = re.sub(r'\s+', ' ', snippet).strip()

        km  = _parse_km(snippet)
        yr  = _parse_year(snippet, year_fallback)

        # Try to extract a car brand + adjacent words as title
        brand_m = _BRAND_PAT.search(snippet)
        if brand_m:
            tail  = snippet[brand_m.start():brand_m.start() + 80]
            title = " ".join(tail.split()[:6])[:65]
        elif make:
            # Use the search term itself as title (at least informative)
            title = f"{make} {model} {yr}".strip()[:65]
        else:
            words = [w for w in snippet.split()
                     if len(w) > 3 and not re.match(r'^\d', w) and "€" not in w]
            title = " ".join(words[:6])[:65] or "–"

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
        _walk_listings(nd, listings, "mobile.de", "https://suchen.mobile.de", year,
                       fallback_title=f"{make} {model}".strip())

    # Strategy B – HTML regex
    if not listings:
        listings = _regex_price_listings(html, "mobile.de", year, make, model)

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
        _walk_listings(nd, listings, "autoscout24.de", "https://www.autoscout24.de", year,
                       fallback_title=f"{make} {model}".strip())

    # Strategy B – HTML regex
    if not listings:
        listings = _regex_price_listings(html, "autoscout24.de", year, make, model)

    # Deduplicate
    seen: set[int] = set()
    unique = []
    for l in listings:
        if l["price"] not in seen:
            seen.add(l["price"])
            unique.append(l)

    return _aggregate(unique)


# ─── Uniform Interface ────────────────────────────────────────────────────────

async def get_market(ctx: Any) -> dict[str, Any]:
    """Uniform interface: VehicleContext → market dict."""
    return await scrape_market(
        ctx.get("make", ""),
        ctx.get("model", ""),
        ctx.get("year", ""),
    )
