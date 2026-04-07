// AutoDossier – Frontend Logic
// Adjust BACKEND_URL to your Render.com deployment URL after deploy
const BACKEND_URL = window.BACKEND_URL || "https://autodossier-api.onrender.com";

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
  const vin_data = data.vehicle  || data.vin_data || {};  // Phase 2: "vehicle"
  const specs    = data.specs    || {};
  const costs    = data.costs    || {};
  const market   = data.market   || {};

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

  document.getElementById("statYear").textContent   = fmt(year);
  document.getElementById("statEngine").textContent  = fmt(engine);
  document.getElementById("statPower").textContent   = specs.power_ps ? specs.power_ps + " PS" : "–";
  document.getElementById("statFuel").textContent    = specs.fuel_consumption ? specs.fuel_consumption + " l/100km" : "–";

  // Ampel (from backend score)
  const score = data.score || {};
  const ampel = score.ampel || {};
  const cssClass = ampel.css || "ampel-green";
  const dot   = document.getElementById("ampelDot");
  dot.className = "w-12 h-12 rounded-full flex items-center justify-center text-xl font-bold shadow-lg " + cssClass;
  dot.textContent = ampel.icon || "?";
  const scoreEl = document.getElementById("ampelScore");
  if (scoreEl) {
    scoreEl.textContent = score.wert !== undefined ? score.wert + " / 100" : "";
    scoreEl.className = "text-sm font-bold tabular-nums " +
      (cssClass === "ampel-green" ? "text-green-400" : cssClass === "ampel-yellow" ? "text-yellow-400" : "text-red-400");
  }
  const lbl = document.getElementById("ampelLabel");
  lbl.className = "text-xs font-medium text-center leading-tight max-w-[6rem] " +
    (cssClass === "ampel-green" ? "text-green-400" : cssClass === "ampel-yellow" ? "text-yellow-400" : "text-red-400");
  lbl.textContent = ampel.label || "";

  // Equipment
  renderEquipment(data.equipment);
  renderScoreBreakdown(data.score);

  // Specs grid
  const specFields = [
    ["Kraftstoff",          vin_data.fuel_type  || specs.fuel_type],
    ["Getriebe",            vin_data.transmission || specs.transmission],
    ["Hubraum",             specs.engine_displacement],
    ["Zylinder",            specs.cylinders],
    ["CO₂ (g/km)",          specs.co2],
    ["Leergewicht (kg)",    specs.curb_weight],
    ["Höchstgeschw.",       specs.top_speed ? specs.top_speed + " km/h" : null],
    ["0–100 km/h",          specs.acceleration ? specs.acceleration + " s" : null],
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
  document.getElementById("avgPrice").textContent   = market.avg_price  ? fmtEuro(market.avg_price)  : "–";
  document.getElementById("minPrice").textContent   = market.min_price  ? fmtEuro(market.min_price)  : "–";
  document.getElementById("maxPrice").textContent   = market.max_price  ? fmtEuro(market.max_price)  : "–";

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

  // Show result
  document.getElementById("resultSection").classList.remove("hidden");
}

// ─── Main Analyze Function ────────────────────────────────────────────────────

async function analyzeVin() {
  const vinInput = document.getElementById("vinInput");
  const vin = vinInput.value.trim().toUpperCase().replace(/\s+/g, "");

  // Basic validation
  if (!/^[A-HJ-NPR-Z0-9]{17}$/.test(vin)) {
    document.getElementById("vinError").classList.remove("hidden");
    vinInput.focus();
    return;
  }
  document.getElementById("vinError").classList.add("hidden");

  // Reset UI
  document.getElementById("resultSection").classList.add("hidden");
  document.getElementById("errorCard").classList.add("hidden");
  document.getElementById("loadingCard").classList.remove("hidden");
  document.getElementById("analyzeBtn").disabled = true;

  // Animate steps
  setStep(1, "active");
  setStep(2, ""); setStep(3, ""); setStep(4, "");

  // Simulate progressive step feedback during fetch
  const stepTimer = (step, delay) =>
    setTimeout(() => setStep(step, "active"), delay);
  const t2 = stepTimer(2, 2000);
  const t3 = stepTimer(3, 5000);
  const t4 = stepTimer(4, 8000);

  try {
    const res = await fetch(`${BACKEND_URL}/api/vin/${vin}`, {
      method: "GET",
      headers: { "Accept": "application/json" },
    });

    clearTimeout(t2); clearTimeout(t3); clearTimeout(t4);
    setStep(1, "done"); setStep(2, "done"); setStep(3, "done"); setStep(4, "done");

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }

    const data = await res.json();

    document.getElementById("loadingCard").classList.add("hidden");
    renderResult(data);

  } catch (err) {
    clearTimeout(t2); clearTimeout(t3); clearTimeout(t4);
    document.getElementById("loadingCard").classList.add("hidden");
    document.getElementById("errorMsg").textContent = err.message;
    document.getElementById("errorCard").classList.remove("hidden");
  } finally {
    document.getElementById("analyzeBtn").disabled = false;
  }
}

function resetForm() {
  document.getElementById("errorCard").classList.add("hidden");
  document.getElementById("resultSection").classList.add("hidden");
  document.getElementById("vinInput").value = "";
  document.getElementById("vinInput").focus();
}

// Allow pressing Enter in input
document.getElementById("vinInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") analyzeVin();
});
