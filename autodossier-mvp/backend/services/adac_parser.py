"""
ADAC Cost Estimator
Primary: Parses ADAC Autokosten PDFs from the adac_pdfs/ directory (pdfplumber).
Fallback: Heuristic cost model based on vehicle class / engine size.

PDF files should be placed in:   ../../adac_pdfs/  (relative to this file)
or in an absolute path defined by env var ADAC_PDF_DIR.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Where to look for ADAC PDFs
_PDF_DIR = Path(
    os.environ.get("ADAC_PDF_DIR", str(Path(__file__).parent.parent.parent / "adac_pdfs"))
)

# ─── Public API ───────────────────────────────────────────────────────────────

def estimate_monthly_costs(make: str, model: str, year: str = "") -> dict[str, Any]:
    """
    Return a dict with monthly cost categories.
    Tries PDF first, then falls back to heuristic model.
    """
    pdf_result = _try_pdf(make, model)
    if pdf_result:
        return pdf_result
    return _heuristic(make, model, year)


# ─── PDF Parser ───────────────────────────────────────────────────────────────

def _try_pdf(make: str, model: str) -> dict | None:
    try:
        import pdfplumber
    except ImportError:
        logger.info("pdfplumber not installed – skipping PDF parse")
        return None

    if not _PDF_DIR.exists():
        return None

    pdfs = list(_PDF_DIR.glob("*.pdf"))
    if not pdfs:
        logger.info("No PDFs found in %s", _PDF_DIR)
        return None

    search_terms = [t.lower() for t in [make, model] if t]

    for pdf_path in sorted(pdfs):
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text() or ""
                    text_lower = text.lower()

                    # Check if this page/table is about our vehicle
                    if not any(term in text_lower for term in search_terms):
                        continue

                    costs = _parse_adac_text(text)
                    if costs:
                        logger.info("ADAC PDF match: %s – %s in %s", make, model, pdf_path.name)
                        return costs

                    # Also try tables
                    for table in page.extract_tables():
                        costs = _parse_adac_table(table, search_terms)
                        if costs:
                            return costs
        except Exception as exc:
            logger.warning("PDF parse error %s: %s", pdf_path.name, exc)

    return None


def _parse_adac_text(text: str) -> dict | None:
    """Extract ADAC cost fields from free text (regex-based)."""
    data = {}

    patterns = {
        "fuel_monthly": [
            r"kraftstoff[^\d]*(\d+[.,]\d+|\d+)\s*€",
            r"fuel[^\d]*(\d+[.,]\d+|\d+)\s*€",
            r"benzin[^\d]*(\d+[.,]\d+|\d+)\s*€",
        ],
        "insurance_monthly": [
            r"versicherung[^\d]*(\d+[.,]\d+|\d+)\s*€",
            r"insurance[^\d]*(\d+[.,]\d+|\d+)\s*€",
        ],
        "tax_monthly": [
            r"steuer[^\d]*(\d+[.,]\d+|\d+)\s*€",
            r"kfz-steuer[^\d]*(\d+[.,]\d+|\d+)\s*€",
        ],
        "maintenance_monthly": [
            r"wartung[^\d]*(\d+[.,]\d+|\d+)\s*€",
            r"inspection[^\d]*(\d+[.,]\d+|\d+)\s*€",
            r"reparatur[^\d]*(\d+[.,]\d+|\d+)\s*€",
        ],
        "depreciation_monthly": [
            r"wertverlust[^\d]*(\d+[.,]\d+|\d+)\s*€",
            r"depreciation[^\d]*(\d+[.,]\d+|\d+)\s*€",
        ],
    }

    for field, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, text, re.I)
            if m:
                try:
                    data[field] = float(m.group(1).replace(",", "."))
                    break
                except ValueError:
                    pass

    if len(data) >= 2:
        data["total_monthly"] = round(sum(data.values()), 2)
        return data
    return None


def _parse_adac_table(table: list, search_terms: list) -> dict | None:
    """Parse ADAC cost table (list of rows, each row is a list of cells)."""
    if not table:
        return None

    # Check if any cell contains our search terms
    flat = " ".join(str(cell or "").lower() for row in table for cell in row)
    if not any(t in flat for t in search_terms):
        return None

    data = {}
    cost_keywords = {
        "fuel_monthly":        ["kraftstoff", "fuel", "benzin", "diesel"],
        "insurance_monthly":   ["versicherung", "insurance", "haftpflicht"],
        "tax_monthly":         ["steuer", "tax", "kfz-steuer"],
        "maintenance_monthly": ["wartung", "maintenance", "reparatur", "inspection"],
        "depreciation_monthly":["wertverlust", "depreciation"],
    }

    for row in table:
        if not row:
            continue
        label = str(row[0] or "").lower()
        value_cell = next((c for c in row[1:] if c and str(c).strip()), None)
        if not value_cell:
            continue
        try:
            val = float(str(value_cell).replace(",", ".").replace("€", "").strip())
        except ValueError:
            continue

        for field, keywords in cost_keywords.items():
            if any(k in label for k in keywords):
                data[field] = val
                break

    if len(data) >= 2:
        data["total_monthly"] = round(sum(data.values()), 2)
        return data
    return None


# ─── Heuristic Fallback ───────────────────────────────────────────────────────
# Based on ADAC 2023/2024 average ranges for different vehicle classes

_COST_TABLE = {
    # (make patterns, base_monthly_costs)
    # Format: { fuel, insurance, tax, maintenance, depreciation }
    "luxury": {
        "makes": ["bmw", "mercedes", "audi", "porsche", "lexus", "tesla"],
        "fuel_monthly": 195,
        "insurance_monthly": 130,
        "tax_monthly": 55,
        "maintenance_monthly": 120,
        "depreciation_monthly": 400,
    },
    "mid": {
        "makes": ["volkswagen", "ford", "opel", "skoda", "seat", "toyota", "honda",
                  "mazda", "hyundai", "kia", "volvo", "peugeot", "renault", "citroën"],
        "fuel_monthly": 145,
        "insurance_monthly": 85,
        "tax_monthly": 28,
        "maintenance_monthly": 70,
        "depreciation_monthly": 200,
    },
    "economy": {
        "makes": ["dacia", "fiat", "mitsubishi", "suzuki", "smart", "mini"],
        "fuel_monthly": 110,
        "insurance_monthly": 60,
        "tax_monthly": 18,
        "maintenance_monthly": 50,
        "depreciation_monthly": 110,
    },
}

_DEFAULT_CLASS = "mid"


def _heuristic(make: str, model: str, year: str) -> dict:
    make_lower = (make or "").lower()

    matched_class = _DEFAULT_CLASS
    for cls, info in _COST_TABLE.items():
        if any(m in make_lower for m in info["makes"]):
            matched_class = cls
            break

    base = _COST_TABLE[matched_class]
    result = {k: v for k, v in base.items() if k != "makes"}

    # Year-based depreciation adjustment (older cars depreciate less but cost more in maintenance)
    try:
        age = 2024 - int(year)
        if age > 5:
            result["depreciation_monthly"] = round(result["depreciation_monthly"] * 0.6)
            result["maintenance_monthly"]  = round(result["maintenance_monthly"]  * 1.3)
    except (TypeError, ValueError):
        pass

    result["total_monthly"] = round(sum(v for k, v in result.items() if k != "makes"))
    result["source"] = "heuristic (ADAC-based estimate)"
    return result


# ─── __init__ stub ────────────────────────────────────────────────────────────

def _init():
    if _PDF_DIR.exists():
        pdfs = list(_PDF_DIR.glob("*.pdf"))
        logger.info("ADAC PDF dir: %s (%d PDFs found)", _PDF_DIR, len(pdfs))
    else:
        logger.info("ADAC PDF dir not found (%s) – will use heuristic fallback", _PDF_DIR)


_init()
