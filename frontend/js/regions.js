const REGIONS_API_BASE = "http://127.0.0.1:8000";
const REGIONS_WINDOW_MIN = 30;
const REGIONS_REFRESH_MS = 60000;

let currentRegion = null;

function setRegionText(selector, value) {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = value;
  }
}

function formatRegionDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString("en-GB", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function buildEmptyState(message) {
  return `<div class="critical-list-empty">${message}</div>`;
}

function renderRegionSummary(items) {
  setRegionText('[data-region-summary="region_count"]', String(items.length));

  if (!items.length) {
    setRegionText('[data-region-summary="top_region"]', "No region");
    setRegionText('[data-region-summary="top_complaint_region"]', "No region");
    setRegionText('[data-region-summary="top_anomaly_region"]', "No region");
    return;
  }

  const topRisk = items[0];
  const topComplaint = [...items].sort((a, b) => b.complaints - a.complaints)[0];
  const topAnomaly = [...items].sort((a, b) => b.anomalies - a.anomalies)[0];

  setRegionText('[data-region-summary="top_region"]', topRisk.region);
  setRegionText('[data-region-summary="top_complaint_region"]', topComplaint?.region || "No region");
  setRegionText('[data-region-summary="top_anomaly_region"]', topAnomaly?.region || "No region");
}

function renderRegionRanking(items) {
  const container = document.getElementById("regionRankingList");
  if (!container) return;

  if (!items.length) {
    container.innerHTML = buildEmptyState("No high-risk regions found.");
    return;
  }

  container.innerHTML = items
    .map(
      (item, index) => `
        <button class="region-rank-card ${currentRegion === item.region ? "active" : ""}" data-region-name="${item.region}">
          <div class="region-rank-top">
            <div>
              <span class="region-rank-index">#${index + 1}</span>
              <strong class="region-rank-name">${item.region}</strong>
            </div>
            <span class="region-rank-score">Risk ${item.risk_score}</span>
          </div>
          <div class="region-rank-bars">
            <span>Fault ${item.faults}</span>
            <span>Anomaly ${item.anomalies}</span>
            <span>Complaint ${item.complaints}</span>
          </div>
        </button>
      `,
    )
    .join("");

  container.querySelectorAll("[data-region-name]").forEach((button) => {
    button.addEventListener("click", () => {
      currentRegion = button.getAttribute("data-region-name");
      renderRegionRanking(items);
      loadRegionDetail(currentRegion);
    });
  });
}

function renderSeverityMix(summary) {
  const container = document.getElementById("severityMix");
  if (!container) return;
  const mix = summary?.severity_mix || {};
  container.innerHTML = `
    <span class="severity-pill">CRITICAL ${mix.CRITICAL ?? 0}</span>
    <span class="severity-pill">MAJOR ${mix.MAJOR ?? 0}</span>
    <span class="severity-pill">MINOR ${mix.MINOR ?? 0}</span>
    <span class="severity-pill">WARNING ${mix.WARNING ?? 0}</span>
  `;
}

function renderGenericRegionList(targetId, items, formatter, emptyMessage) {
  const container = document.getElementById(targetId);
  if (!container) return;
  if (!items.length) {
    container.innerHTML = buildEmptyState(emptyMessage);
    return;
  }
  container.innerHTML = items.map(formatter).join("");
}

function renderRegionDetail(payload) {
  setRegionText("#selectedRegionTitle", payload.region);
  setRegionText("#selectedRegionWindow", `${payload.window_min} min window`);

  const summary = payload.summary || {};
  setRegionText('[data-region-detail="fault_count"]', String(summary.fault_count ?? 0));
  setRegionText('[data-region-detail="anomaly_count"]', String(summary.anomaly_count ?? 0));
  setRegionText('[data-region-detail="complaint_count"]', String(summary.complaint_count ?? 0));
  setRegionText(
    '[data-region-detail="station_count"]',
    `${summary.active_station_count ?? 0}/${summary.station_count ?? 0}`,
  );

  renderSeverityMix(summary);

  renderGenericRegionList(
    "regionFaultList",
    payload.faults || [],
    (item) => `
      <div class="region-detail-item">
        <div class="region-detail-top">
          <strong>${item.cell_id || "N/A"}</strong>
          <span>${item.severity || "UNKNOWN"}</span>
        </div>
        <p>${item.fault_type || "Fault"}</p>
        <small>${formatRegionDate(item.created_at)}</small>
      </div>
    `,
    "No fault records in this window.",
  );

  renderGenericRegionList(
    "regionComplaintList",
    payload.complaints || [],
    (item) => `
      <div class="region-detail-item">
        <div class="region-detail-top">
          <strong>${item.cell_id || "N/A"}</strong>
          <span>Complaint</span>
        </div>
        <p>${item.issue || "Complaint"}</p>
        <small>${formatRegionDate(item.created_at)}</small>
      </div>
    `,
    "No complaint records in this window.",
  );

  renderGenericRegionList(
    "regionAnomalyList",
    payload.anomalies || [],
    (item) => `
      <div class="region-detail-item">
        <div class="region-detail-top">
          <strong>${item.cell_id || "N/A"}</strong>
          <span>${item.severity || "WARNING"}</span>
        </div>
        <p>${item.root_cause || "Anomaly detected"}</p>
        <small>${formatRegionDate(item.metric_recorded_at)}</small>
      </div>
    `,
    "No anomaly records in this window.",
  );

  const stationContainer = document.getElementById("regionStationList");
  if (stationContainer) {
    const stations = payload.stations || [];
    stationContainer.innerHTML = stations.length
      ? stations
          .map(
            (item) => `
              <span class="station-chip ${String(item.status || "").toLowerCase()}">
                ${item.cell_id}
              </span>
            `,
          )
          .join("")
      : buildEmptyState("No station records found.");
  }
}

async function loadRegionDetail(regionName) {
  try {
    const response = await fetch(
      `${REGIONS_API_BASE}/regions/detail?region=${encodeURIComponent(regionName)}&window_min=${REGIONS_WINDOW_MIN}&limit=8`,
    );
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to load region detail");
    }
    renderRegionDetail(payload);
  } catch (error) {
    setRegionText("#selectedRegionTitle", "Region detail unavailable");
    const targets = ["regionFaultList", "regionComplaintList", "regionAnomalyList", "regionStationList"];
    targets.forEach((id) => {
      const container = document.getElementById(id);
      if (container) container.innerHTML = buildEmptyState(`Error: ${error.message}`);
    });
  }
}

async function loadRegionsDashboard() {
  try {
    const response = await fetch(
      `${REGIONS_API_BASE}/overview/regions?window_min=${REGIONS_WINDOW_MIN}&top_n=10`,
    );
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to load region ranking");
    }
    const items = payload.items || [];
    renderRegionSummary(items);
    if (!currentRegion && items.length) {
      currentRegion = items[0].region;
    }
    renderRegionRanking(items);
    if (currentRegion) {
      await loadRegionDetail(currentRegion);
    }
  } catch (error) {
    const container = document.getElementById("regionRankingList");
    if (container) container.innerHTML = buildEmptyState(`Error: ${error.message}`);
  }
}

loadRegionsDashboard();
window.setInterval(loadRegionsDashboard, REGIONS_REFRESH_MS);
