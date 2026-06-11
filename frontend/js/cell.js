const CELL_API_BASE = "http://127.0.0.1:8000";

const cellState = {
  cellId: "CELL_001",
  sliceType: "",
  limit: 20,
};

function setCellText(selector, value) {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = value;
  }
}

function formatCellDate(value) {
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

function formatNumber(value, digits = 1) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return number.toFixed(digits);
}

function readCellFilters() {
  const rawCell = document.getElementById("cellIdInput")?.value || "CELL_001";
  cellState.cellId = rawCell.trim().toUpperCase() || "CELL_001";
  cellState.sliceType = document.getElementById("cellSliceSelect")?.value || "";
  cellState.limit = Number(document.getElementById("cellLimitSelect")?.value || 20);
}

function buildEmptyCellState(message) {
  return `<div class="critical-list-empty">${message}</div>`;
}

async function fetchJson(path) {
  const response = await fetch(`${CELL_API_BASE}${path}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Request failed");
  }
  return payload;
}

function renderStation(payload) {
  const station = payload.items?.[0];
  setCellText('[data-cell-summary="cell_id"]', cellState.cellId);
  setCellText('[data-cell-summary="region"]', station?.region || "--");
  setCellText('[data-cell-summary="status"]', station?.status || "--");
}

function renderMetricSummary(items) {
  const latest = items[0];
  setCellText("#metricListCount", `${items.length} samples`);

  if (!latest) {
    setCellText('[data-cell-summary="slice_type"]', "--");
    setCellText('[data-cell-kpi="latency_ms"]', "--");
    setCellText('[data-cell-kpi="packet_loss_pct"]', "--");
    setCellText('[data-cell-kpi="throughput_mbps"]', "--");
    setCellText('[data-cell-kpi="load_pct"]', "--");
    setCellText("#cellLastUpdated", "No metric data");
    return;
  }

  setCellText('[data-cell-summary="slice_type"]', latest.slice_type || "--");
  setCellText('[data-cell-kpi="latency_ms"]', `${formatNumber(latest.latency_ms)} ms`);
  setCellText('[data-cell-kpi="packet_loss_pct"]', `${formatNumber(latest.packet_loss_pct, 2)}%`);
  setCellText('[data-cell-kpi="throughput_mbps"]', `${formatNumber(latest.throughput_mbps)} Mbps`);
  setCellText('[data-cell-kpi="load_pct"]', `${formatNumber(latest.load_pct)}%`);
  setCellText("#cellLastUpdated", `Updated ${formatCellDate(latest.recorded_at)}`);
}

function renderMetrics(items) {
  const container = document.getElementById("cellMetricList");
  if (!container) return;
  renderMetricSummary(items);

  if (!items.length) {
    container.innerHTML = buildEmptyCellState("No metric samples found for this cell.");
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <div class="cell-metric-row">
          <div class="cell-metric-row-head">
            <strong>${item.slice_type || "slice"}</strong>
            <span>${formatCellDate(item.recorded_at)}</span>
          </div>
          <div class="cell-metric-grid">
            <span>Latency <strong>${formatNumber(item.latency_ms)} ms</strong></span>
            <span>Packet loss <strong>${formatNumber(item.packet_loss_pct, 2)}%</strong></span>
            <span>Throughput <strong>${formatNumber(item.throughput_mbps)} Mbps</strong></span>
            <span>Load <strong>${formatNumber(item.load_pct)}%</strong></span>
            <span>RSRP <strong>${formatNumber(item.rsrp_dbm)} dBm</strong></span>
            <span>Users <strong>${item.connected_users ?? "--"}</strong></span>
          </div>
        </div>
      `,
    )
    .join("");
}

function renderAnomalies(items) {
  const container = document.getElementById("cellAnomalyList");
  if (!container) return;
  const cutoff = Date.now() - 24 * 60 * 60 * 1000;
  const liveItems = items.filter((item) => {
    const time = new Date(item.metric_recorded_at).getTime();
    return Number.isFinite(time) && time >= cutoff;
  });
  setCellText("#anomalyListCount", `${liveItems.length} live anomalies`);

  if (!liveItems.length) {
    container.innerHTML = buildEmptyCellState("No live anomalies found for this cell in the last 24 hours.");
    return;
  }

  container.innerHTML = liveItems
    .map(
      (item) => `
        <div class="alarm-context-item">
          <div class="alarm-context-top">
            <strong>${item.severity || "INFO"}</strong>
            <span>${formatCellDate(item.metric_recorded_at)}</span>
          </div>
          <p>${item.root_cause || "Anomaly result without root cause."}</p>
          <small>Score ${formatNumber(item.anomaly_score, 2)}</small>
        </div>
      `,
    )
    .join("");
}

function renderFaults(items) {
  const container = document.getElementById("cellFaultList");
  if (!container) return;
  setCellText("#faultListCount", `${items.length} faults`);

  if (!items.length) {
    container.innerHTML = buildEmptyCellState("No recent faults found for this cell.");
    return;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <div class="alarm-context-item">
          <div class="alarm-context-top">
            <strong>${item.fault_type || "Fault"}</strong>
            <span>${item.severity || "UNKNOWN"}</span>
          </div>
          <p>${item.message || "No fault message."}</p>
          <small>${item.resolved ? "Resolved" : "Open"} - ${formatCellDate(item.created_at)}</small>
        </div>
      `,
    )
    .join("");
}

async function loadCellDashboard() {
  readCellFilters();
  setCellText("#cellResultMeta", `Loading ${cellState.cellId}`);

  const metricParams = new URLSearchParams({
    cell_id: cellState.cellId,
    limit: String(cellState.limit),
  });
  if (cellState.sliceType) metricParams.set("slice_type", cellState.sliceType);

  try {
    const [stationPayload, metricPayload, anomalyPayload, faultPayload] = await Promise.all([
      fetchJson(`/stations?cell_id=${encodeURIComponent(cellState.cellId)}&limit=1`),
      fetchJson(`/metrics?${metricParams.toString()}`),
      fetchJson(`/anomalies?cell_id=${encodeURIComponent(cellState.cellId)}&only_anomalies=true&limit=50`),
      fetchJson(`/faults?cell_id=${encodeURIComponent(cellState.cellId)}&window_min=1440&limit=10`),
    ]);

    renderStation(stationPayload);
    renderMetrics(metricPayload.items || []);
    renderAnomalies(anomalyPayload.items || []);
    renderFaults(faultPayload.items || []);
    setCellText("#cellResultMeta", `${cellState.cellId} loaded`);
  } catch (error) {
    setCellText("#cellResultMeta", `Error: ${error.message}`);
    const targets = ["cellMetricList", "cellAnomalyList", "cellFaultList"];
    targets.forEach((id) => {
      const container = document.getElementById(id);
      if (container) container.innerHTML = buildEmptyCellState(`Error: ${error.message}`);
    });
  }
}

document.getElementById("loadCellButton")?.addEventListener("click", loadCellDashboard);
["cellSliceSelect", "cellLimitSelect"].forEach((id) => {
  document.getElementById(id)?.addEventListener("change", loadCellDashboard);
});
document.getElementById("cellIdInput")?.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    loadCellDashboard();
  }
});

loadCellDashboard();
