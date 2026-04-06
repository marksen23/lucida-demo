#!/usr/bin/env python3
"""
ADAC PDF Downloader
===================
Sucht auf adac.de nach dem aktuellen Autokosten-PDF und lädt es herunter.

Verwendung:
    python scripts/download_adac_pdf.py

Das PDF wird in autodossier-mvp/adac_pdfs/ gespeichert.
Playwright muss installiert sein:
    pip install playwright && playwright install chromium
"""

import asyncio
import re
import sys
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent.parent / "adac_pdfs"

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: Playwright nicht installiert.")
    print("Bitte ausführen: pip install playwright && playwright install chromium")
    sys.exit(1)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# ADAC page where PDF links are available
_SEARCH_PAGES = [
    "https://www.adac.de/rund-ums-fahrzeug/auto-kaufen-verkaufen/autokosten/",
    "https://www.adac.de/rund-ums-fahrzeug/auto-kaufen-verkaufen/autokosten/autokosten-vergleich/",
]


async def find_and_download():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            user_agent=_USER_AGENT,
            viewport={"width": 1440, "height": 900},
        )
        page = await ctx.new_page()

        pdf_urls: list[str] = []

        for search_url in _SEARCH_PAGES:
            print(f"Suche auf: {search_url}")
            try:
                await page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
                await asyncio.sleep(2)

                # Accept cookies
                for sel in ["button#consentAcceptAll", "button[data-tracking*='Accept']", "button.accept-all"]:
                    try:
                        btn = await page.query_selector(sel)
                        if btn:
                            await btn.click()
                            await asyncio.sleep(1)
                            break
                    except Exception:
                        pass

                # Find all PDF links
                links = await page.query_selector_all("a[href*='.pdf'], a[href*='download']")
                for link in links:
                    href = await link.get_attribute("href") or ""
                    text = (await link.inner_text()).strip().lower()
                    if ".pdf" in href.lower() or "autokosten" in text:
                        if not href.startswith("http"):
                            href = "https://www.adac.de" + href
                        if href not in pdf_urls:
                            pdf_urls.append(href)
                            print(f"  → PDF gefunden: {href}")

            except Exception as e:
                print(f"  Fehler bei {search_url}: {e}")

        if not pdf_urls:
            print("\nKein PDF-Link auf der ADAC-Seite gefunden.")
            print("Das PDF muss manuell heruntergeladen werden:")
            print("  1. Öffne: https://www.adac.de/rund-ums-fahrzeug/auto-kaufen-verkaufen/autokosten/")
            print("  2. Suche nach 'PDF herunterladen' oder 'Autokosten-Tabelle'")
            print(f"  3. Speichere die Datei in: {OUTPUT_DIR}/")
            await browser.close()
            return

        # Download found PDFs
        import httpx

        async with httpx.AsyncClient(
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
            timeout=30,
        ) as client:
            for url in pdf_urls[:3]:  # max 3 PDFs
                try:
                    print(f"\nLade herunter: {url}")
                    resp = await client.get(url)
                    if resp.status_code == 200 and b"%PDF" in resp.content[:10]:
                        filename = re.sub(r"[^\w\-.]", "_", url.split("/")[-1])
                        if not filename.endswith(".pdf"):
                            filename += ".pdf"
                        out_path = OUTPUT_DIR / filename
                        out_path.write_bytes(resp.content)
                        print(f"  ✓ Gespeichert: {out_path} ({len(resp.content) // 1024} KB)")
                    else:
                        print(f"  ✗ Kein gültiges PDF (Status {resp.status_code})")
                except Exception as e:
                    print(f"  ✗ Download fehlgeschlagen: {e}")

        await browser.close()

    # List results
    pdfs = list(OUTPUT_DIR.glob("*.pdf"))
    if pdfs:
        print(f"\n✅ {len(pdfs)} PDF(s) in {OUTPUT_DIR}:")
        for p in pdfs:
            print(f"   {p.name} ({p.stat().st_size // 1024} KB)")
    else:
        print(f"\n⚠ Keine PDFs in {OUTPUT_DIR} gefunden.")
        _print_manual_instructions()


def _print_manual_instructions():
    print("""
Manuelle Alternative:
─────────────────────
1. https://www.adac.de/rund-ums-fahrzeug/auto-kaufen-verkaufen/autokosten/ aufrufen
2. Seite nach PDF-Links durchsuchen (Strg+F → ".pdf")
3. Alternativ direkt suchen: 'ADAC Autokosten Tabelle PDF 2024 site:adac.de'
4. Heruntergeladene Datei in autodossier-mvp/adac_pdfs/ ablegen

Der Backend-Service erkennt PDFs automatisch beim nächsten Start.
Ohne PDF läuft der Service mit dem ADAC-basierten Heuristik-Fallback weiter.
""")


if __name__ == "__main__":
    asyncio.run(find_and_download())
