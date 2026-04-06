# AutoDossier MVP

Kostenloser Fahrzeug-Report per VIN – 100 % free, keine API-Keys.

## Architektur

```
Frontend (Netlify)  →  Backend API (Render.com)  →  Scraper Services
     HTML/JS/CSS           FastAPI + Playwright        freevindecoder.eu
                                                        auto-data.net
                                                        mobile.de / autoscout24.de
                                                        ADAC PDF (lokal)
```

## Schnellstart (lokal)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium   # Linux only (system deps)

uvicorn main:app --reload --port 8000
```

API läuft dann auf http://localhost:8000  
Docs: http://localhost:8000/docs

### Frontend

```bash
# In einem zweiten Terminal:
cd frontend
# BACKEND_URL anpassen in script.js → "http://localhost:8000"
python -m http.server 3000
# → http://localhost:3000
```

## Deployment

### 1. Backend → Render.com

1. Neues **Web Service** erstellen
2. GitHub-Repo verbinden
3. Root Directory: `autodossier-mvp/backend`
4. Render erkennt `render.yaml` automatisch
5. Build Command: `pip install -r requirements.txt && playwright install chromium && playwright install-deps chromium`
6. Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
7. Nach dem Deploy die URL notieren (z.B. `https://autodossier-api.onrender.com`)

### 2. Frontend → Netlify

1. `frontend/script.js` öffnen → `BACKEND_URL` auf deine Render-URL setzen
2. Netlify → "New site from Git" → `autodossier-mvp/frontend` als Publish-Directory
3. Build Command: *(leer lassen)*
4. Fertig!

### 3. ADAC-PDFs einrichten (optional, empfohlen)

1. ADAC Autokosten-PDF herunterladen:
   https://www.adac.de/rund-ums-fahrzeug/auto-kaufen-verkaufen/autokosten/
2. PDF in `adac_pdfs/` ablegen
3. Auf Render: im Disk-Mount unter `/opt/render/project/src/adac_pdfs` hochladen
4. Ohne PDF: automatischer Fallback auf Heuristik (ADAC-basierte Schätzwerte)

## Report-Felder (Free-Version)

| Feld | Quelle |
|------|--------|
| Make, Model, Year, Engine | freevindecoder.eu / driving-tests.org |
| Leistung, Verbrauch, CO₂ | auto-data.net |
| Monatliche Kosten | ADAC PDF oder Heuristik |
| Marktpreise + Vergleichsangebote | mobile.de / autoscout24.de |
| Ampel-Bewertung | Preis vs. Markt + Kosten (berechnet) |

## Ampel-Logik

| Farbe | Kriterium |
|-------|-----------|
| 🟢 Grün  | Preis ≤ 110 % des Marktdurchschnitts UND Kosten moderat (< 450 €/Monat) |
| 🟡 Gelb  | Preis 110–135 % oder Kosten erhöht (450–700 €/Monat) |
| 🔴 Rot   | Preis > 135 % des Marktdurchschnitts ODER Kosten hoch (> 700 €/Monat) |

## Projektstruktur

```
autodossier-mvp/
├── frontend/
│   ├── index.html          # Single-Page App
│   ├── style.css           # Custom styles (Tailwind ergänzt)
│   └── script.js           # Fetch + Render-Logik
├── backend/
│   ├── main.py             # FastAPI App + CORS
│   ├── routers/
│   │   └── vin.py          # GET /api/vin/{vin}
│   ├── services/
│   │   ├── vin_decoder.py  # freevindecoder.eu / driving-tests.org
│   │   ├── specs_scraper.py # auto-data.net
│   │   ├── market_scraper.py # mobile.de / autoscout24.de
│   │   └── adac_parser.py  # ADAC PDF + Heuristik-Fallback
│   ├── requirements.txt
│   └── render.yaml
└── adac_pdfs/              # ADAC PDFs hier ablegen (gitignore'd)
```

## Hinweise

- Playwright läuft headless mit realistischem User-Agent und Delays
- Alle Scrapers haben Timeouts und Exception-Handling → App bleibt stabil
- Ohne ADAC-PDF werden ADAC-basierte Schätzwerte verwendet (klar gekennzeichnet)
- Kein API-Key, kein Sign-up, keine kostenpflichtigen Dienste
