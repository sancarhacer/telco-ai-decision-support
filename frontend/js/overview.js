const OVERVIEW_API_BASE = "http://127.0.0.1:8000";
const OVERVIEW_WINDOW_MIN = 30;
const EVENT_REFRESH_MS = 30000;
const OVERVIEW_REFRESH_MS = 60000;

function formatDateTime(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function setText(selector, value) {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = value;
  }
}

function renderOverviewSummary(payload) {
  setText('[data-kpi="critical_open_faults"]', String(payload.critical_open_faults ?? 0));
  setText('[data-kpi="anomaly_count"]', String(payload.anomaly_count ?? 0));
  setText('[data-kpi="complaint_count"]', String(payload.complaint_count ?? 0));
  setText('[data-kpi="affected_region_count"]', String(payload.affected_region_count ?? 0));

  const riskiestRegion = payload.riskiest_region;
  setText(
    '[data-kpi="riskiest_region_name"]',
    riskiestRegion?.region || "Bölge yok",
  );
  setText(
    '[data-kpi="riskiest_region_meta"]',
    riskiestRegion
      ? `Risk ${riskiestRegion.risk_score} - Fault ${riskiestRegion.faults} - Anomaly ${riskiestRegion.anomalies} - Sikayet ${riskiestRegion.complaints}`
      : "Risk skoru uretilemedi",
  );

  setText('[data-kpi="last_updated_at"]', formatDateTime(payload.last_updated_at));
  setText(
    '[data-kpi="summary_status"]',
    payload.last_updated_at ? "Gercek veriden uretildi" : "Henuz veri akisi yok",
  );
  setText('[data-kpi="overview_live_status"]', "Live");
}

async function loadOverviewSummary() {
  try {
    const response = await fetch(`${OVERVIEW_API_BASE}/overview/summary?window_min=${OVERVIEW_WINDOW_MIN}`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Özet verisi alınamadı");
    }
    renderOverviewSummary(payload);
  } catch (error) {
    setText('[data-kpi="summary_status"]', `Hata: ${error.message}`);
    setText('[data-kpi="overview_live_status"]', "Warning");
  }
}

function renderCriticalFaults(items) {
  const container = document.getElementById("criticalFaultList");
  if (!container) return;

  if (!Array.isArray(items) || items.length === 0) {
    container.innerHTML = '<div class="critical-list-empty">Açık kritik fault bulunamadı.</div>';
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <div class="critical-list-item">
          <div class="critical-list-main">
            <span class="critical-cell">${item.cell_id ?? "N/A"}</span>
            <span class="critical-region">${item.region ?? "Bilinmeyen bolge"}</span>
          </div>
          <div class="critical-list-sub">
            <span class="critical-fault-type">${item.fault_type ?? "FAULT"}</span>
            <span class="critical-time">${formatDateTime(item.created_at)}</span>
          </div>
        </div>
      `,
    )
    .join("");
}

async function loadCriticalFaults() {
  try {
    const response = await fetch(`${OVERVIEW_API_BASE}/faults?severity=CRITICAL&resolved=false&limit=5`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Kritik fault verisi alinamadi");
    }
    renderCriticalFaults(payload.items || []);
  } catch (error) {
    const container = document.getElementById("criticalFaultList");
    if (container) {
      container.innerHTML = `<div class="critical-list-empty">Hata: ${error.message}</div>`;
    }
  }
}

function renderRiskRegions(items) {
  const container = document.getElementById("riskRegionList");
  if (!container) return;

  if (!Array.isArray(items) || items.length === 0) {
    container.innerHTML = '<div class="critical-list-empty">Riskli bölge bulunamadı.</div>';
    return;
  }

  container.innerHTML = items
    .map(
      (item, index) => `
        <div class="risk-region-item">
          <div class="risk-region-main">
            <div>
              <div class="risk-region-rank">#${index + 1}</div>
              <div class="risk-region-name">${item.region}</div>
            </div>
            <div class="risk-region-score">Risk ${item.risk_score}</div>
          </div>
          <div class="risk-region-metrics">
            <span>Fault ${item.faults}</span>
            <span>Anomaly ${item.anomalies}</span>
            <span>Sikayet ${item.complaints}</span>
          </div>
        </div>
      `,
    )
    .join("");
}

async function loadRiskRegions() {
  try {
    const response = await fetch(`${OVERVIEW_API_BASE}/overview/regions?window_min=${OVERVIEW_WINDOW_MIN}&top_n=5`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Bolge riski alinamadi");
    }
    renderRiskRegions(payload.items || []);
  } catch (error) {
    const container = document.getElementById("riskRegionList");
    if (container) {
      container.innerHTML = `<div class="critical-list-empty">Hata: ${error.message}</div>`;
    }
  }
}

function eventBadgeClass(eventType) {
  if (eventType === "fault") return "event-badge-fault";
  if (eventType === "anomaly") return "event-badge-anomaly";
  return "event-badge-complaint";
}

function renderEventStream(items) {
  const container = document.getElementById("eventStreamList");
  if (!container) return;

  if (!Array.isArray(items) || items.length === 0) {
    container.innerHTML = '<div class="critical-list-empty">Son olay bulunamadı.</div>';
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <div class="event-stream-item">
          <div class="event-stream-top">
            <span class="event-badge ${eventBadgeClass(item.event_type)}">${item.event_type}</span>
            <span class="event-severity">${item.severity || "INFO"}</span>
            <span class="event-time">${formatDateTime(item.timestamp)}</span>
          </div>
          <div class="event-stream-body">
            <strong>${item.cell_id || "N/A"}</strong>
            <span>${item.region || "Bilinmeyen bolge"}</span>
            <p>${item.label || "Event"}</p>
          </div>
        </div>
      `,
    )
    .join("");
}

async function loadEventStream() {
  try {
    const response = await fetch(`${OVERVIEW_API_BASE}/overview/events?window_min=${OVERVIEW_WINDOW_MIN}&limit=12`);
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Olay akisi alinamadi");
    }
    renderEventStream(payload.items || []);
  } catch (error) {
    const container = document.getElementById("eventStreamList");
    if (container) {
      container.innerHTML = `<div class="critical-list-empty">Hata: ${error.message}</div>`;
    }
  }
}

loadOverviewSummary();
loadCriticalFaults();
loadRiskRegions();
loadEventStream();
window.setInterval(loadOverviewSummary, OVERVIEW_REFRESH_MS);
window.setInterval(loadCriticalFaults, OVERVIEW_REFRESH_MS);
window.setInterval(loadRiskRegions, OVERVIEW_REFRESH_MS);
window.setInterval(loadEventStream, EVENT_REFRESH_MS);
