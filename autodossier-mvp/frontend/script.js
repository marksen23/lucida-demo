// AutoDossier – Frontend Logic
// Adjust BACKEND_URL to your Render.com deployment URL after deploy
const BACKEND_URL = window.BACKEND_URL || "https://auto-dossier.onrender.com";

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

// ─── Ampel Logic ──────────────────────────────────────────────────────────────
// Green  = price ≤ 110% of avg market  AND monthly costs reasonable
// Yellow = price between 110–135% of avg market  OR costs elevated
// Red    = price > 135% of avg market  OR costs very high

function computeAmpel(data) {
  const avgMarket = data.market?.avg_price;
  const totalMonthly = data.costs?.total_monthly;
  let score = 0; // 0=green, 1=yellow, 2=red

  if (avgMarket && data.market?.listings?.length > 0) {
    // Compare listing[0] price (the car being looked at) to avg
    const firstPrice = data.market.listings[0]?.price;
    if (firstPrice && avgMarket) {
      const ratio = firstPrice / avgMarket;
      if (ratio > 1.35) score = Math.max(score, 2);
      else if (ratio > 1.10) score = Math.max(score, 1);
    }
  }

  if (totalMonthly) {
    if (totalMonthly > 700) score = Math.max(score, 2);
    else if (totalMonthly > 450) score = Math.max(score, 1);
  }

  const map = [
    { cls: "ampel-green", icon: "✓", label: "Guter Deal", textCls: "text-green-400" },
    { cls: "ampel-yellow", icon: "!", label: "Mit Vorsicht", textCls: "text-yellow-400" },
    { cls: "ampel-red",   icon: "✕", label: "Teuer",        textCls: "text-red-400" },
  ];
  return map[score];
}

// ─── Render Functions ─────────────────────────────────────────────────────────

function renderResult(data) {
  const vin_data = data.vin_data || {};
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

  // Ampel
  const ampel = computeAmpel(data);
  const dot   = document.getElementById("ampelDot");
  dot.className = "w-12 h-12 rounded-full flex items-center justify-center text-xl font-bold shadow-lg " + ampel.cls;
  dot.textContent = ampel.icon;
  const lbl = document.getElementById("ampelLabel");
  lbl.className = "text-xs font-medium " + ampel.textCls;
  lbl.textContent = ampel.label;

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
