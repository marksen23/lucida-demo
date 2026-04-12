// AutoDossier – Frontend Logic
const BACKEND_URL = window.BACKEND_URL || "https://lucida-demo.onrender.com";

// ─── Backend Wakeup (Render.com Free Tier) ────────────────────────────────────
// Free-tier services sleep after 15 min inactivity (cold start ~30-60s).
// Pre-ping /health on page load so the backend is awake when the user submits.

let _backendReady = false;
let _wakeupPromise = null;

function _wakeupBackend() {
  _wakeupPromise = fetch(BACKEND_URL + "/health", {
    signal: AbortSignal.timeout(65_000),
  })
    .then(r => { if (r.ok) _backendReady = true; })
    .catch(() => {});
}

document.addEventListener("DOMContentLoaded", _wakeupBackend);

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(value, fallback = "–") {
  return value !== undefined && value !== null && value !== "" ? value : fallback;
}

function fmtEuro(value) {
  if (value === null || value === undefined || value === "") return "–";
  return new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR", maximumFractionDigits: 0 }).format(value);
}

function setStep(n, state) {
  const el = document.getElementById("step" + n);
  if (!el) return;
  el.className = "flex items-center gap-2 " + (state === "done" ? "step-done" : state === "active" ? "step-active" : "");
  const icon = el.querySelector(".step-icon");
  if (icon) {
    icon.textContent = state === "done" ? "✅" : state === "active" ? "🔄" : "⏳";
  }
}

function setLoadingMsg(text) {
  const el = document.getElementById("loadingMsg");
  if (el) el.textContent = text;
}

// ─── Equipment Renderer ───────────────────────────────────────────────────────

function renderEquipment(equipment) {
  const listEl     = document.getElementById("equipmentList");
  const optSection = document.getElementById("optionalEquipmentSection");
  const optList    = document.getElementById("optionalList");

  if (!equipment?.available) {
    listEl.innerHTML = '<p class="text-gray-500 text-sm">Keine Ausstattungsdaten verfügbar</p>';
    optSection.classList.add("hidden");
    return;
  }

  const standard = equipment.serienausstattung || [];
  if (standard.length === 0) {
    listEl.innerHTML = '<p class="text-gray-500 text-sm">Keine Ausstattungsdaten verfügbar</p>';
  } else {
    listEl.innerHTML = standard.map(item =>
      `<span class="bg-gray-800 text-gray-300 text-xs px-2 py-1 rounded-full">${item}</span>`
    ).join("");
  }

  const optional = equipment.typisch_optional || [];
  if (optional.length > 0) {
    optSection.classList.remove("hidden");
    optList.innerHTML = optional.map(item =>
      `<span class="bg-gray-900 border border-gray-700 text-gray-400 text-xs px-2 py-1 rounded-full">${item}</span>`
    ).join("");
  } else {
    optSection.classList.add("hidden");
  }
}

// ─── Score Breakdown Renderer ─────────────────────────────────────────────────

function renderScoreBreakdown(score) {
  const section = document.getElementById("scoreBreakdownSection");
  if (!score?.breakdown?.length) {
    section.classList.add("hidden");
    return;
  }
  section.classList.remove("hidden");

  const grid = document.getElementById("scoreBreakdownGrid");
  grid.innerHTML = score.breakdown.map(b => {
    const pct = b.max > 0 ? Math.round(((b.max - b.abzug) / b.max) * 100) : 0;
    const barColor = b.abzug === 0 ? "bg-green-500" : b.abzug < b.max * 0.5 ? "bg-yellow-500" : "bg-red-500";
    return `
      <div>
        <div class="flex justify-between text-xs text-gray-400 mb-1">
          <span>${b.dimension}</span>
          <span class="text-gray-300">${b.text}</span>
        </div>
        <div class="h-1.5 bg-gray-800 rounded-full overflow-hidden">
          <div class="h-full ${barColor} rounded-full transition-all" style="width:${pct}%"></div>
        </div>
      </div>`;
  }).join("");
}

// ─── Render Functions ─────────────────────────────────────────────────────────

function renderResult(data) {
  // Phase 2 returns "vehicle", legacy fallback to "vin_data"
  const vin_data = data.vehicle || data.vin_data || {};
  const specs    = data.specs   || {};
  const costs    = data.costs   || {};
  const market   = data.market  || {};
  const carfax   = data.carfax  || {};

  // Vehicle header
  const make  = fmt(vin_data.make  || specs.make);
  const model = fmt(vin_data.model || specs.model);
  const year  = fmt(vin_data.year  || specs.year);
  const trim  = fmt(vin_data.trim  || specs.trim);
  const engine = fmt(vin_data.engine || specs.engine_displacement);

  document.getElementById("vehicleTitle").textContent =
    [make, model].filter(Boolean).join(" ") || "Unbekanntes Fahrzeug";
  document.getElementById("vehicleSubtitle").textContent =
    [year, trim].filter(v => v !== "–").join(" • ");

  document.getElementById("statYear").textContent  = fmt(year);
  document.getElementById("statEngine").textContent = fmt(engine);
  document.getElementById("statPower").textContent  = specs.power_ps ? specs.power_ps + " PS" : "–";
  document.getElementById("statFuel").textContent   = specs.fuel_consumption ? specs.fuel_consumption + " l/100km" : "–";

  // Ampel – use backend-computed score when available
  const score   = data.score || {};
  const ampel   = score.ampel || {};
  const cssClass = ampel.css || "ampel-green";
  const dot = document.getElementById("ampelDot");
  dot.className = "w-12 h-12 rounded-full flex items-center justify-center text-xl font-bold shadow-lg " + cssClass;
  dot.textContent = ampel.icon || "?";
  const scoreEl = document.getElementById("ampelScore");
  if (scoreEl) {
    scoreEl.textContent = score.wert !== undefined ? score.wert + " / 100" : "–";
    scoreEl.className = "text-lg font-bold tabular-nums " +
      (cssClass === "ampel-green" ? "text-green-400" : cssClass === "ampel-yellow" ? "text-yellow-400" : "text-red-400");
  }
  const lbl = document.getElementById("ampelLabel");
  lbl.className = "text-xs font-medium text-center leading-tight max-w-[6rem] " +
    (cssClass === "ampel-green" ? "text-green-400" : cssClass === "ampel-yellow" ? "text-yellow-400" : "text-red-400");
  lbl.textContent = ampel.label || "";

  // Equipment + Score Breakdown
  renderEquipment(data.equipment);
  renderScoreBreakdown(score);

  // Specs grid
  const specFields = [
    ["Kraftstoff",       vin_data.fuel_type    || specs.fuel_type],
    ["Getriebe",         vin_data.transmission || specs.transmission],
    ["Hubraum",          specs.engine_displacement],
    ["Zylinder",         specs.cylinders],
    ["CO₂ (g/km)",       specs.co2],
    ["Leergewicht (kg)", specs.curb_weight],
    ["Höchstgeschw.",    specs.top_speed ? specs.top_speed + " km/h" : null],
    ["0–100 km/h",       specs.acceleration ? specs.acceleration + " s" : null],
  ];
  const sg = document.getElementById("specsGrid");
  sg.innerHTML = specFields
    .filter(([, v]) => v)
    .map(([label, value]) =>
      `<div class="spec-row"><span class="spec-label">${label}</span><span class="spec-value">${fmt(value)}</span></div>`
    ).join("") || `<p class="text-gray-500 text-sm col-span-2">Keine Specs verfügbar</p>`;

  // Costs
  const costItems = [
    ["Kraftstoff",   costs.fuel_monthly],
    ["Versicherung", costs.insurance_monthly],
    ["Steuer",       costs.tax_monthly],
    ["Wartung",      costs.maintenance_monthly],
    ["Wertverlust",  costs.depreciation_monthly],
  ];
  const cg = document.getElementById("costsGrid");
  cg.innerHTML = costItems
    .filter(([, v]) => v)
    .map(([label, value]) =>
      `<div class="cost-pill"><div class="cost-label">${label}</div><div class="cost-value">${fmtEuro(value)}</div></div>`
    ).join("") || `<p class="text-gray-500 text-sm">Keine Kostendaten verfügbar</p>`;
  document.getElementById("totalCost").textContent =
    costs.total_monthly ? fmtEuro(costs.total_monthly) + " / Monat" : "–";

  // Market prices
  document.getElementById("avgPrice").textContent = market.avg_price ? fmtEuro(market.avg_price) : "–";
  document.getElementById("minPrice").textContent = market.min_price ? fmtEuro(market.min_price) : "–";
  document.getElementById("maxPrice").textContent = market.max_price ? fmtEuro(market.max_price) : "–";

  const listings = market.listings || [];
  const ll = document.getElementById("listingsList");
  if (listings.length === 0) {
    ll.innerHTML = `<p class="text-gray-500 text-sm">Keine Angebote gefunden</p>`;
  } else {
    ll.innerHTML = listings.map(l => `
      <div class="listing-card">
        <div>
          <p class="font-medium text-gray-200">${fmt(l.title)}</p>
          <p class="text-xs text-gray-500 mt-0.5">${fmt(l.mileage)} km · ${fmt(l.year)} · ${fmt(l.source)}</p>
        </div>
        <div class="listing-price">
          ${l.url
            ? `<a href="${l.url}" target="_blank" rel="noopener">${fmtEuro(l.price)}</a>`
            : fmtEuro(l.price)
          }
        </div>
      </div>`).join("");
  }

  // Carfax / AutoCheck historie
  const carfaxCount    = carfax.carfax    ?? 0;
  const autocheckCount = carfax.autocheck ?? 0;
  document.getElementById("carfaxCount").textContent    = carfaxCount;
  document.getElementById("autocheckCount").textContent = autocheckCount;

  if (carfaxCount > 0 || autocheckCount > 0) {
    document.getElementById("reportAction").classList.remove("hidden");
  } else {
    document.getElementById("reportAction").classList.add("hidden");
  }
  document.getElementById("buyReportBtn").disabled = false;
  document.getElementById("buyReportBtn").textContent = "Vollständigen Report abrufen (Kostenpflichtig)";
  document.getElementById("reportStatus").innerHTML = "";

  document.getElementById("resultSection").classList.remove("hidden");
}

// ─── API Helper – VIN fetch mit 504-Retry ─────────────────────────────────────

async function _fetchReport(vin) {
  const url = `${BACKEND_URL}/api/vin/${vin}`;

  for (let attempt = 0; attempt < 2; attempt++) {
    const res = await fetch(url, { headers: { "Accept": "application/json" } });

    if (res.status === 504 && attempt === 0) {
      setLoadingMsg("Server gestartet, Analyse läuft erneut …");
      setStep(1, "active"); setStep(2, ""); setStep(3, ""); setStep(4, ""); setStep(5, "");
      await new Promise(r => setTimeout(r, 3_000));
      continue;
    }

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `HTTP ${res.status}`);
    }

    return res.json();
  }
  throw new Error("Server antwortet nicht – bitte erneut versuchen.");
}

// ─── Main Analyze Function ────────────────────────────────────────────────────

async function analyzeVin() {
  const vinInput = document.getElementById("vinInput");
  const vin = vinInput.value.trim().toUpperCase().replace(/\s+/g, "");

  if (!/^[A-HJ-NPR-Z0-9]{17}$/.test(vin)) {
    document.getElementById("vinError").classList.remove("hidden");
    vinInput.focus();
    return;
  }
  document.getElementById("vinError").classList.add("hidden");

  window.currentVin = vin;

  // Reset UI
  document.getElementById("resultSection").classList.add("hidden");
  document.getElementById("errorCard").classList.add("hidden");
  document.getElementById("loadingCard").classList.remove("hidden");
  document.getElementById("analyzeBtn").disabled = true;

  setStep(1, "active");
  setStep(2, ""); setStep(3, ""); setStep(4, ""); setStep(5, "");
  setLoadingMsg("");

  // If the backend isn't warm yet, wait and show a hint
  if (_wakeupPromise && !_backendReady) {
    setLoadingMsg("Server wird gestartet (kostenloser Server, ~30 Sek. warten) …");
    await Promise.race([
      _wakeupPromise,
      new Promise(r => setTimeout(r, 65_000)),
    ]);
    setLoadingMsg("");
  }

  // Progressive step animation
  const t2 = setTimeout(() => setStep(2, "active"), 2_000);
  const t3 = setTimeout(() => setStep(3, "active"), 4_000);
  const t4 = setTimeout(() => setStep(4, "active"), 6_000);
  const t5 = setTimeout(() => setStep(5, "active"), 8_000);

  try {
    // Parallel: VIN report + Carfax records (carfax is fire-and-forget, never blocks)
    const [data, carfaxData] = await Promise.all([
      _fetchReport(vin),
      fetch(`${BACKEND_URL}/api/carfax/records/${vin}`, { headers: { "Accept": "application/json" } })
        .then(r => r.ok ? r.json() : { carfax: 0, autocheck: 0 })
        .catch(() => ({ carfax: 0, autocheck: 0 })),
    ]);

    clearTimeout(t2); clearTimeout(t3); clearTimeout(t4); clearTimeout(t5);
    setStep(1, "done"); setStep(2, "done"); setStep(3, "done"); setStep(4, "done"); setStep(5, "done");

    data.carfax = carfaxData;

    document.getElementById("loadingCard").classList.add("hidden");
    renderResult(data);

  } catch (err) {
    clearTimeout(t2); clearTimeout(t3); clearTimeout(t4); clearTimeout(t5);

    let msg = err.message || "Unbekannter Fehler";
    if (!navigator.onLine) {
      msg = "Keine Internetverbindung – bitte Verbindung prüfen und erneut versuchen.";
    } else if (/Failed to fetch|NetworkError|ERR_/i.test(msg)) {
      msg = "Verbindungsfehler – Backend nicht erreichbar. Bitte später erneut versuchen.";
    } else if (/504|Timeout|timeout/i.test(msg)) {
      msg = "Analyse-Timeout – der Server startet nach Inaktivität, bitte erneut versuchen.";
    }

    document.getElementById("loadingCard").classList.add("hidden");
    document.getElementById("errorMsg").textContent = msg;
    document.getElementById("errorCard").classList.remove("hidden");
  } finally {
    document.getElementById("analyzeBtn").disabled = false;
  }
}

// ─── Carfax Report kaufen ─────────────────────────────────────────────────────

async function buyCarfaxReport() {
  if (!window.currentVin) return;
  const btn    = document.getElementById("buyReportBtn");
  const status = document.getElementById("reportStatus");

  btn.disabled = true;
  btn.textContent = "Report wird generiert …";
  status.textContent = "Bitte warten, Report wird verarbeitet …";

  try {
    const res = await fetch(
      `${BACKEND_URL}/api/carfax/report/${window.currentVin}/carfax`,
      { method: "POST", headers: { "Accept": "application/json" } }
    );

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.detail || `Fehler beim Erstellen des Reports (HTTP ${res.status})`);
    }

    const reportData = await res.json();

    if (reportData.link) {
      status.innerHTML =
        `<a href="${reportData.link}" target="_blank" rel="noopener"
            class="text-blue-400 font-bold underline hover:text-blue-300 text-base">
           Hier klicken, um deinen Report zu öffnen
         </a>`;
      btn.textContent = "Report erfolgreich generiert!";
    } else {
      throw new Error("API hat keinen Link zurückgegeben.");
    }
  } catch (e) {
    status.textContent = e.message;
    btn.textContent = "Fehler – Erneut versuchen";
    btn.disabled = false;
  }
}

// ─── Utils ────────────────────────────────────────────────────────────────────

function resetForm() {
  document.getElementById("errorCard").classList.add("hidden");
  document.getElementById("resultSection").classList.add("hidden");
  document.getElementById("vinInput").value = "";
  document.getElementById("vinInput").focus();
}

document.getElementById("vinInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") analyzeVin();
});
