#!/usr/bin/env bash
# AutoDossier MVP – Schnell-Setup
# Führe dieses Script im Root-Verzeichnis des Projekts aus.
set -e

echo "=== AutoDossier MVP Setup ==="

# 1. Python venv
if [ ! -d "backend/.venv" ]; then
  echo "→ Erstelle Python-Virtualenv..."
  python3 -m venv backend/.venv
fi
source backend/.venv/bin/activate

# 2. Dependencies
echo "→ Installiere Python-Pakete..."
pip install -q -r backend/requirements.txt

# 3. Playwright browsers
echo "→ Installiere Playwright-Browser (Chromium)..."
playwright install chromium
playwright install-deps chromium 2>/dev/null || true   # nur auf Linux nötig

# 4. ADAC PDFs versuchen herunterzuladen
echo "→ Versuche ADAC-PDFs zu laden..."
python scripts/download_adac_pdf.py || echo "  (PDF-Download fehlgeschlagen – Heuristik-Fallback aktiv)"

echo ""
echo "=== Setup abgeschlossen ==="
echo ""
echo "Backend starten:"
echo "  source backend/.venv/bin/activate"
echo "  cd backend && uvicorn main:app --reload --port 8000"
echo ""
echo "Frontend:"
echo "  cd frontend && python -m http.server 3000"
echo "  → http://localhost:3000"
