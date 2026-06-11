const ALARMS_API_BASE = "http://127.0.0.1:8000";
const ALARMS_REFRESH_MS = 60000;

const alarmState = {
  windowMin: 30,
  severity: "",
  status: "open",
  region: "",
  cellId: "",
  selectedAlarmId: null,
};

function setAlarmText(selector, value) {
  const element = document.querySelector(selector);
  if (element) {
    element.textContent = value;
  }
}

function formatAlarmDate(value) {
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

function buildAlarmEmptyState(message) {
  return `<div class="critical-list-empty">${message}</div>`;
}

function normalizeResolvedFilter(status) {
  if (status === "open") return "false";
  if (status === "resolved") return "true";
  return "";
}

function readAlarmFilters() {
  alarmState.windowMin = Number(document.getElementById("alarmWindow")?.value || 30);
  alarmState.severity = document.getElementById("alarmSeverity")?.value || "";
  alarmState.status = document.getElementById("alarmStatus")?.value || "";
  alarmState.region = (document.getElementById("alarmRegion")?.value || "").trim();
  alarmState.cellId = (document.getElementById("alarmCell")?.value || "").trim().toUpperCase();
}

function buildFaultQueryParams(limit = 20) {
  const params = new URLSearchParams({
    window_min: String(alarmState.windowMin),
    limit: String(limit),
  });

  if (alarmState.severity) params.set("severity", alarmState.severity);
  const resolved = normalizeResolvedFilter(alarmState.status);
  if (resolved) params.set("resolved", resolved);
  if (alarmState.region) params.set("region", alarmState.region);
  if (alarmState.cellId) params.set("cell_id", alarmState.cellId);

  return params.toString();
}

function renderAlarmSummary(payload) {
  setAlarmText('[data-alarm-summary="open_total"]', String(payload.open_total ?? 0));
  setAlarmText('[data-alarm-summary="open_critical"]', String(payload.open_critical ?? 0));
  setAlarmText('[data-alarm-summary="open_major"]', String(payload.open_major ?? 0));
  setAlarmText('[data-alarm-summary="new_alarm_count"]', String(payload.new_alarm_count ?? 0));
  setAlarmText(
    '[data-alarm-summary="busiest_region"]',
    payload.busiest_region?.region || "No active region",
  );
  const lastUpdated = payload.last_updated_at ? `Last update ${formatAlarmDate(payload.last_updated_at)}` : "Last update --";
  setAlarmText("#alarmLastUpdated", lastUpdated);
}

function renderAlarmList(items) {
  const container = document.getElementById("alarmList");
  if (!container) return;

  setAlarmText("#alarmListCount", `${items.length} alarms`);

  if (!items.length) {
    container.innerHTML = buildAlarmEmptyState("No alarms match the current filters.");
    renderAlarmDetailEmpty();
    return;
  }

  if (!alarmState.selectedAlarmId || !items.some((item) => item.id === alarmState.selectedAlarmId)) {
    alarmState.selectedAlarmId = items[0].id;
  }

  container.innerHTML = items
    .map(
      (item) => `
        <button class="alarm-list-item ${alarmState.selectedAlarmId === item.id ? "active" : ""}" data-alarm-id="${item.id}">
          <div class="alarm-list-top">
            <div class="alarm-list-title-wrap">
              <span class="severity-dot severity-${String(item.severity || "").toLowerCase()}"></span>
              <strong class="alarm-list-cell">${item.cell_id || "N/A"}</strong>
              <span class="alarm-list-region">${item.region || "Unknown region"}</span>
            </div>
            <span class="alarm-severity-badge severity-${String(item.severity || "").toLowerCase()}">${item.severity || "UNKNOWN"}</span>
          </div>
          <div class="alarm-list-mid">
            <span>${item.fault_type || "Fault"}</span>
            <span>${item.resolved ? "Resolved" : "Open"}</span>
          </div>
          <div class="alarm-list-bottom">
            <span>${formatAlarmDate(item.created_at)}</span>
            <span>${item.message || "No message"}</span>
          </div>
        </button>
      `,
    )
    .join("");

  container.querySelectorAll("[data-alarm-id]").forEach((button) => {
    button.addEventListener("click", () => {
      alarmState.selectedAlarmId = Number(button.getAttribute("data-alarm-id"));
      renderAlarmList(items);
      loadAlarmDetail(alarmState.selectedAlarmId);
    });
  });
}

function renderAlarmContextList(targetId, items, formatter, emptyMessage) {
  const container = document.getElementById(targetId);
  if (!container) return;
  if (!items.length) {
    container.innerHTML = buildAlarmEmptyState(emptyMessage);
    return;
  }
  container.innerHTML = items.map(formatter).join("");
}

function renderAlarmDetailEmpty() {
  setAlarmText("#selectedAlarmTitle", "Select an alarm");
  setAlarmText("#selectedAlarmMeta", "Awaiting selection");
  setAlarmText('[data-alarm-detail="cell_id"]', "--");
  setAlarmText('[data-alarm-detail="region"]', "--");
  setAlarmText('[data-alarm-detail="severity"]', "--");
  setAlarmText('[data-alarm-detail="status"]', "--");
  setAlarmText("#selectedAlarmMessage", "Choose an alarm to inspect its message and context.");
  setAlarmText("#selectedAlarmStation", "No station context loaded yet.");
  ["relatedFaultsList", "relatedAnomaliesList", "relatedComplaintsList"].forEach((id) => {
    const container = document.getElementById(id);
    if (container) {
      container.innerHTML = buildAlarmEmptyState("No data loaded.");
    }
  });
}

function renderAlarmDetail(payload) {
  const alarm = payload.alarm || {};
  setAlarmText("#selectedAlarmTitle", `${alarm.cell_id || "Unknown cell"} alarm`);
  setAlarmText(
    "#selectedAlarmMeta",
    `${alarm.fault_type || "Fault"} • ${formatAlarmDate(alarm.created_at)}`,
  );
  setAlarmText('[data-alarm-detail="cell_id"]', alarm.cell_id || "--");
  setAlarmText('[data-alarm-detail="region"]', alarm.region || "--");
  setAlarmText('[data-alarm-detail="severity"]', alarm.severity || "--");
  setAlarmText('[data-alarm-detail="status"]', alarm.resolved ? "Resolved" : "Open");
  setAlarmText("#selectedAlarmMessage", alarm.message || "No message provided.");

  const station = payload.station;
  setAlarmText(
    "#selectedAlarmStation",
    station
      ? `${station.cell_id} • ${station.region} • ${station.status || "unknown"}`
      : "No station context available.",
  );

  renderAlarmContextList(
    "relatedFaultsList",
    payload.related_faults || [],
    (item) => `
      <div class="alarm-context-item">
        <div class="alarm-context-top">
          <strong>${item.fault_type || "Fault"}</strong>
          <span>${item.severity || "UNKNOWN"}</span>
        </div>
        <p>${item.message || "No message"}</p>
        <small>${formatAlarmDate(item.created_at)}</small>
      </div>
    `,
    "No related faults in this window.",
  );

  renderAlarmContextList(
    "relatedAnomaliesList",
    payload.related_anomalies || [],
    (item) => `
      <div class="alarm-context-item">
        <div class="alarm-context-top">
          <strong>${item.triggered_by || "Anomaly"}</strong>
          <span>${item.severity || "WARNING"}</span>
        </div>
        <p>${item.root_cause || "No root cause available"}</p>
        <small>${formatAlarmDate(item.metric_recorded_at)}</small>
      </div>
    `,
    "No related anomalies in this window.",
  );

  renderAlarmContextList(
    "relatedComplaintsList",
    payload.related_complaints || [],
    (item) => `
      <div class="alarm-context-item">
        <div class="alarm-context-top">
          <strong>${item.customer_id || "Customer"}</strong>
          <span>Complaint</span>
        </div>
        <p>${item.issue || "No complaint issue"}</p>
        <small>${formatAlarmDate(item.created_at)}</small>
      </div>
    `,
    "No related complaints in this window.",
  );
}

async function loadAlarmSummary() {
  const response = await fetch(
    `${ALARMS_API_BASE}/alarms/summary?window_min=${alarmState.windowMin}`,
  );
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Failed to load alarm summary");
  }
  renderAlarmSummary(payload);
}

async function loadAlarmList() {
  const response = await fetch(`${ALARMS_API_BASE}/faults?${buildFaultQueryParams(20)}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Failed to load alarms");
  }
  const items = payload.items || [];
  renderAlarmList(items);
  if (alarmState.selectedAlarmId) {
    await loadAlarmDetail(alarmState.selectedAlarmId);
  }
}

async function loadAlarmDetail(faultId) {
  if (!faultId) {
    renderAlarmDetailEmpty();
    return;
  }

  const response = await fetch(
    `${ALARMS_API_BASE}/alarms/detail/${faultId}?context_window_min=${alarmState.windowMin}&context_limit=6`,
  );
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.detail || "Failed to load alarm detail");
  }
  renderAlarmDetail(payload);
}

async function loadAlarmsDashboard() {
  try {
    await loadAlarmSummary();
    await loadAlarmList();
  } catch (error) {
    const list = document.getElementById("alarmList");
    if (list) list.innerHTML = buildAlarmEmptyState(`Error: ${error.message}`);
    renderAlarmDetailEmpty();
    setAlarmText("#alarmLastUpdated", `Error: ${error.message}`);
  }
}

function bindAlarmFilters() {
  ["alarmWindow", "alarmSeverity", "alarmStatus"].forEach((id) => {
    const element = document.getElementById(id);
    element?.addEventListener("change", async () => {
      readAlarmFilters();
      alarmState.selectedAlarmId = null;
      await loadAlarmsDashboard();
    });
  });

  ["alarmRegion", "alarmCell"].forEach((id) => {
    const element = document.getElementById(id);
    element?.addEventListener("change", async () => {
      readAlarmFilters();
      alarmState.selectedAlarmId = null;
      await loadAlarmsDashboard();
    });
  });
}

readAlarmFilters();
bindAlarmFilters();
loadAlarmsDashboard();
window.setInterval(loadAlarmsDashboard, ALARMS_REFRESH_MS);
