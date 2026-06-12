const API_BASE = "http://127.0.0.1:8000";

const chatBox = document.getElementById("chatBox");
const chatForm = document.getElementById("chatForm");
const messageInput = document.getElementById("messageInput");
const limitInput = document.getElementById("limitInput");

// Örnek sorgu butonları
document.querySelectorAll(".example-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    messageInput.value = btn.dataset.query;
    messageInput.focus();
  });
});

function addMessage(content, type) {
  const div = document.createElement("div");
  div.className = `msg ${type}`;

  if (typeof content === "string") {
    div.textContent = content;
  } else {
    div.appendChild(content);
  }

  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function formatAnomalyCard(item, metricType = null) {
  const severity = item.severity || "warning";
  const card = document.createElement("div");
  card.className = `anomaly-card ${severity.toLowerCase()}`;

  const triggeredMetrics = item.triggered_by ?
    (typeof item.triggered_by === "string" ? JSON.parse(item.triggered_by) : item.triggered_by) : {};

  // Metrik tipine göre vurgulama
  const highlightMetric = getHighlightMetric(metricType, triggeredMetrics);

  card.innerHTML = `
    <div class="anomaly-header">
      <div>
        <span class="cell-id">${item.cell_id || "N/A"}</span>
        ${item.region ? `<span class="region-tag">📍 ${item.region}</span>` : ""}
      </div>
      <span class="severity-badge ${severity.toLowerCase()}">${severity}</span>
    </div>
    <div class="anomaly-info">
      ${highlightMetric ? `
        <div class="metric-highlight">
          <div class="metric-highlight-label">${highlightMetric.label}</div>
          <div class="metric-highlight-value">${highlightMetric.value}</div>
        </div>
      ` : ""}
      <div class="info-row">
        <span class="info-label">Anomali Skoru:</span>
        <span class="info-value">${(item.anomaly_score || 0).toFixed(2)}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Tespit Zamanı:</span>
        <span class="info-value">${formatDate(item.metric_recorded_at)}</span>
      </div>
      ${Object.keys(triggeredMetrics).length > 0 ? `
        <div class="triggered-metrics">
          ${Object.entries(triggeredMetrics).map(([key, val]) =>
    `<span class="metric-tag ${isHighlightedMetric(key, metricType) ? 'highlighted' : ''}">${formatMetricName(key)}: ${formatMetricValue(key, val)}</span>`
  ).join("")}
        </div>
      ` : ""}
      ${item.root_cause ? `
        <div class="root-cause">
          <div class="root-cause-label"> Olası Neden:</div>
          <div>${item.root_cause}</div>
        </div>
      ` : ""}
    </div>
  `;

  return card;
}

function getHighlightMetric(metricType, triggeredMetrics) {
  if (!metricType || !triggeredMetrics) return null;

  const metricMap = {
    "packet_loss": "packet_loss_pct",
    "latency": "latency_ms",
    "signal": ["rsrp_dbm", "rsrq_db"],
    "load": "load_pct",
    "throughput": "throughput_mbps"
  };

  const keys = Array.isArray(metricMap[metricType]) ? metricMap[metricType] : [metricMap[metricType]];

  for (const key of keys) {
    if (triggeredMetrics[key] !== undefined) {
      return {
        label: formatMetricName(key),
        value: formatMetricValue(key, triggeredMetrics[key])
      };
    }
  }

  return null;
}

function isHighlightedMetric(metricKey, metricType) {
  if (!metricType) return false;

  const metricMap = {
    "packet_loss": ["packet_loss_pct"],
    "latency": ["latency_ms"],
    "signal": ["rsrp_dbm", "rsrq_db"],
    "load": ["load_pct"],
    "throughput": ["throughput_mbps"]
  };

  return metricMap[metricType]?.includes(metricKey) || false;
}

// ── Fault Kartı ──────────────────────────────────────────────
function formatFaultCard(item) {
  const severity = item.severity || "warning";
  const card = document.createElement("div");
  card.className = `anomaly-card ${severity.toLowerCase()}`;

  const faultTypeLabels = {
    "SLICE_CONGESTION": "Dilim Tıkanıklığı",
    "HARDWARE_FAILURE": "Donanım Arızası",
    "LINK_DOWN": "Bağlantı Koptu",
    "HIGH_INTERFERENCE": "Yüksek Girişim",
    "POWER_ISSUE": "Güç Sorunu",
    "SOFTWARE_FAULT": "Yazılım Hatası",
  };

  card.innerHTML = `
    <div class="anomaly-header">
      <div>
        <span class="cell-id">${item.cell_id}</span>
        ${item.region ? `<span class="region-tag">📍 ${item.region}</span>` : ""}
      </div>
      <span class="severity-badge ${severity.toLowerCase()}">${severity}</span>
    </div>
    <div class="anomaly-info">
      <div class="info-row">
        <span class="info-label">Arıza Tipi:</span>
        <span class="info-value">${faultTypeLabels[item.fault_type] || item.fault_type || "—"}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Durum:</span>
        <span class="info-value" style="color:${item.resolved ? '#10b981' : '#f87171'}">
          ${item.resolved ? "✅ Çözüldü" : "🔴 Açık"}
        </span>
      </div>
      <div class="info-row">
        <span class="info-label">Oluşma:</span>
        <span class="info-value">${formatDate(item.created_at)}</span>
      </div>
      ${item.message ? `
        <div class="root-cause">
          <div class="root-cause-label"> Mesaj:</div>
          <div>${item.message}</div>
        </div>
      ` : ""}
    </div>
  `;
  return card;
}

// ── Bölge Sıralaması ─────────────────────────────────────────
function formatRegionRanking(items, type) {
  const container = document.createElement("div");
  container.className = "region-ranking";

  const maxCount = items[0]?.fault_count || items[0]?.count || 1;

  items.forEach((item, index) => {
    const count = item.fault_count || item.count || 0;
    const pct = Math.round((count / maxCount) * 100);
    const medal = index === 0 ? "1" : index === 1 ? "2" : index === 2 ? "3" : `${index + 1}.`;

    const row = document.createElement("div");
    row.className = "rank-row";
    row.innerHTML = `
      <div class="rank-header">
        <span class="rank-medal">${medal}</span>
        <span class="rank-region">${item.region}</span>
        <span class="rank-count">${count} arıza</span>
      </div>
      <div class="rank-bar-bg">
        <div class="rank-bar" style="width:${pct}%"></div>
      </div>
      ${(item.critical || item.major || item.minor) ? `
        <div class="rank-breakdown">
          ${item.critical ? `<span class="rank-badge critical">🔴 ${item.critical} Critical</span>` : ""}
          ${item.major ? `<span class="rank-badge major">🟠 ${item.major} Major</span>` : ""}
          ${item.minor ? `<span class="rank-badge minor">🟡 ${item.minor} Minor</span>` : ""}
        </div>
      ` : ""}
    `;
    container.appendChild(row);
  });

  return container;
}

// ── Şikayet Kartı ─────────────────────────────────────────────
function formatComplaintCard(item) {
  const card = document.createElement("div");
  card.className = "complaint-card";
  card.innerHTML = `
    <div class="complaint-icon">💬</div>
    <div class="complaint-body">
      <div class="complaint-issue">${item.issue || "Belirtilmemiş"}</div>
      <div class="complaint-meta">
        ${item.cell_id ? `<span>📡 ${item.cell_id}</span>` : ""}
        ${item.region ? `<span>📍 ${item.region}</span>` : ""}
        <span>🕐 ${formatDate(item.created_at)}</span>
      </div>
    </div>
  `;
  return card;
}

// ── Şikayet Nedeni Sıralaması ─────────────────────────────────
function formatIssueRanking(items) {
  const container = document.createElement("div");
  container.className = "issue-ranking";

  const maxCount = items[0]?.complaint_count || 1;

  const issueIcons = {
    "NO_SIGNAL": "📵",
    "SLOW_INTERNET": "🐢",
    "CALL_DROP": "📞",
    "HIGH_LATENCY": "⏱️",
    "PACKET_LOSS": "📉",
    "BILLING": "💳",
    "COVERAGE": "📶",
  };

  items.forEach((item, index) => {
    const count = item.complaint_count || 0;
    const pct = Math.round((count / maxCount) * 100);
    const medal = index === 0 ? "1" : index === 1 ? "2" : index === 2 ? "3" : `${index + 1}.`;
    const icon = issueIcons[item.issue] || "⚠️";

    const row = document.createElement("div");
    row.className = "issue-row";
    row.innerHTML = `
      <div class="issue-header">
        <span class="rank-medal">${medal}</span>
        <span class="issue-icon">${icon}</span>
        <span class="issue-name">${item.issue || "Diğer"}</span>
        <span class="issue-count">${count} şikayet</span>
      </div>
      <div class="rank-bar-bg">
        <div class="issue-bar" style="width:${pct}%"></div>
      </div>
      <div class="issue-dates">
        İlk: ${formatDate(item.first_seen)} &nbsp;·&nbsp; Son: ${formatDate(item.last_seen)}
      </div>
    `;
    container.appendChild(row);
  });

  return container;
}

// ── İstasyon Kartı ────────────────────────────────────────────
function formatStationCard(item) {
  const status = (item.status || "unknown").toLowerCase();
  const statusColor = status === "active" ? "#10b981" : status === "offline" ? "#f87171" : "#f59e0b";
  const statusLabel = status === "active" ? "✅ Aktif" : status === "offline" ? "🔴 Çevrimdışı" : "⚠️ " + item.status;

  const card = document.createElement("div");
  card.className = "anomaly-card";
  card.style.borderLeftColor = statusColor;
  card.innerHTML = `
    <div class="anomaly-header">
      <span class="cell-id">${item.cell_id}</span>
      <span class="severity-badge" style="background:${statusColor}">${statusLabel}</span>
    </div>
    <div class="anomaly-info">
      <div class="info-row">
        <span class="info-label"> Bölge:</span>
        <span class="info-value">${item.region || "—"}</span>
      </div>
      <div class="info-row">
        <span class="info-label"> Konum:</span>
        <span class="info-value">${item.lat?.toFixed(4) || "—"}, ${item.lng?.toFixed(4) || "—"}</span>
      </div>
    </div>
  `;
  return card;
}

// ── Bölgeye Göre İstasyon Grupları ───────────────────────────
function formatStationsByRegion(byRegion, status) {
  const statusColor = status === "active" ? "#10b981" : status === "offline" ? "#f87171" : "#f59e0b";
  const statusLabel = status === "active" ? "✅ Aktif" : status === "offline" ? "🔴 Çevrimdışı" : "🔧 Bakımda";

  const container = document.createElement("div");
  container.className = "station-region-list";

  const entries = Object.entries(byRegion).sort((a, b) => b[1].length - a[1].length);

  entries.forEach(([region, stations]) => {
    const block = document.createElement("div");
    block.className = "station-region-block";
    block.innerHTML = `
      <div class="station-region-header">
        <span class="station-region-name">📍 ${region}</span>
        <span class="station-region-badge" style="background:${statusColor}20; border:1px solid ${statusColor}; color:${statusColor}">
          ${statusLabel} · ${stations.length} istasyon
        </span>
      </div>
      <div class="station-chips">
        ${stations.map(s => `<span class="station-chip">${s.cell_id}</span>`).join("")}
      </div>
    `;
    container.appendChild(block);
  });

  return container;
}

// Metrik tipi → hangi DB alanı
const METRIC_FIELD_MAP = {
  "packet_loss": "packet_loss_pct",
  "latency": "latency_ms",
  "load": "load_pct",
  "throughput": "throughput_mbps",
  "signal": "rsrp_dbm",
};

function formatMetricCard(item, metricType = null) {
  const card = document.createElement("div");
  card.className = "metric-card";

  // Sorulan metriği belirle
  const focusField = metricType ? METRIC_FIELD_MAP[metricType] : null;
  const focusValue = focusField ? item[focusField] : null;

  // Tüm metrik satırları
  const allMetrics = [
    { key: "throughput_mbps", label: "Throughput", icon: "🚀" },
    { key: "latency_ms", label: "Gecikme", icon: "⏱️" },
    { key: "packet_loss_pct", label: "Paket Kaybı", icon: "📉" },
    { key: "load_pct", label: "Yük", icon: "⚡" },
    { key: "rsrp_dbm", label: "Sinyal Gücü", icon: "📶" },
    { key: "rsrq_db", label: "Sinyal Kalitesi", icon: "📡" },
    { key: "connected_users", label: "Bağlı Kullanıcı", icon: "👥" },
  ];

  card.innerHTML = `
    <div class="metric-card-header">
      <span class="cell-id">${item.cell_id}</span>
      <span class="slice-badge">${item.slice_type || ""}</span>
      <span class="metric-time">${formatDate(item.recorded_at)}</span>
    </div>

    ${focusField && focusValue !== undefined ? `
      <div class="metric-highlight">
        <div class="metric-highlight-label">${allMetrics.find(m => m.key === focusField)?.icon || ""} ${allMetrics.find(m => m.key === focusField)?.label || focusField}</div>
        <div class="metric-highlight-value">${formatMetricValue(focusField, focusValue)}</div>
      </div>
    ` : ""}

    <div class="metric-rows">
      ${allMetrics.map(({ key, label, icon }) => {
    const val = item[key];
    if (val === undefined || val === null) return "";
    const isMain = key === focusField;
    return `
          <div class="metric-row ${isMain ? "metric-row-main" : ""}">
            <span class="metric-row-label">${icon} ${label}</span>
            <span class="metric-row-value">${formatMetricValue(key, val)}</span>
          </div>
        `;
  }).join("")}
    </div>
  `;

  return card;
}

function formatMetricName(key) {
  const names = {
    "latency_ms": "Gecikme",
    "packet_loss_pct": "Paket Kaybı",
    "load_pct": "Yük",
    "throughput_mbps": "Throughput",
    "rsrp_dbm": "Sinyal Gücü",
    "rsrq_db": "Sinyal Kalitesi"
  };
  return names[key] || key;
}

function formatMetricValue(key, value) {
  if (key.includes("_pct")) return `${value}%`;
  if (key.includes("_ms")) return `${value} ms`;
  if (key.includes("_mbps")) return `${value} Mbps`;
  if (key.includes("_dbm")) return `${value} dBm`;
  if (key.includes("_db")) return `${value} dB`;
  if (key === "connected_users") return `${value} kullanıcı`;
  return value;
}

function formatDate(dateStr) {
  if (!dateStr) return "N/A";
  const date = new Date(dateStr);
  return date.toLocaleString("tr-TR", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function renderResponse(data, route, metricType = null) {
  const container = document.createElement("div");

  // Özet bilgi
  const summary = document.createElement("div");
  summary.className = "summary";

  const count = data.count || 0;
  const filters = data.filters || {};

  let summaryText = "";
  let summaryIcon = "📊";

  if (route === "anomalies") {
    // Metrik tipine göre özel mesaj
    if (metricType === "packet_loss") {
      summaryIcon = "📉";
      summaryText = `${count} paket kaybı anomalisi bulundu`;
    } else if (metricType === "latency") {
      summaryIcon = "⏱️";
      summaryText = `${count} gecikme anomalisi bulundu`;
    } else if (metricType === "signal") {
      summaryIcon = "📶";
      summaryText = `${count} sinyal anomalisi bulundu`;
    } else if (metricType === "load") {
      summaryIcon = "⚡";
      summaryText = `${count} yük anomalisi bulundu`;
    } else if (metricType === "throughput") {
      summaryIcon = "🚀";
      summaryText = `${count} throughput anomalisi bulundu`;
    } else {
      summaryText = `${count} anomali kaydı bulundu`;
    }

    if (filters.cell_id) summaryText += ` (${filters.cell_id})`;
    if (filters.region) summaryText += ` (${filters.region})`;
  } else if (route === "faults") {
    summaryIcon = "⚠️";
    summaryText = `${count} arıza kaydı bulundu`;
  } else if (route === "complaints") {
    summaryIcon = "💬";
    summaryText = `${count} şikayet kaydı bulundu`;
  } else if (route === "stations") {
    summaryIcon = "🗼";
    const statusLabel = {
      "active": "aktif", "offline": "çevrimdışı", "maintenance": "bakımda"
    };
    const sf = data.filters?.status;
    summaryText = sf
      ? `${count} ${statusLabel[sf.toLowerCase()] || sf} istasyon bulundu`
      : `${count} istasyon kaydı bulundu`;
    if (data.filters?.region) summaryText += ` (${data.filters.region})`;
  } else {
    summaryText = `${count} metrik kaydı bulundu`;
    if (metricType) {
      const metricLabels = {
        "packet_loss": "📉 Paket Kaybı",
        "latency": "⏱️ Gecikme",
        "signal": "📶 Sinyal",
        "load": "⚡ Yük",
        "throughput": "🚀 Throughput"
      };
      summaryIcon = "";
      summaryText = `${data.cell_id || ""} için son ${count} ${metricLabels[metricType] || "metrik"} ölçümü`;
    } else {
      summaryText = `${data.cell_id || ""} için son ${count} metrik kaydı`;
    }
  }

  summary.innerHTML = `
    <div class="summary-title">${summaryIcon} Sonuç Özeti</div>
    <div class="summary-text">${summaryText}</div>
  `;
  container.appendChild(summary);

  // Veri kartları
  const items = data.items || [];

  if (items.length === 0) {
    const noData = document.createElement("div");
    noData.className = "no-data";
    noData.textContent = "Sonuç bulunamadı";
    container.appendChild(noData);
    return container;
  }

  if (route === "anomalies") {
    const grid = document.createElement("div");
    grid.className = "anomaly-grid";

    items.forEach((item) => {
      grid.appendChild(formatAnomalyCard(item, metricType));
    });

    container.appendChild(grid);
  } else if (route === "metrics") {
    const grid = document.createElement("div");
    grid.className = "anomaly-grid";
    items.forEach((item) => grid.appendChild(formatMetricCard(item, metricType)));
    container.appendChild(grid);

  } else if (route === "faults") {
    if (data.grouped) {
      container.appendChild(formatRegionRanking(items, "fault"));
    } else {
      const grid = document.createElement("div");
      grid.className = "anomaly-grid";
      items.forEach((item) => grid.appendChild(formatFaultCard(item)));
      container.appendChild(grid);
    }

  } else if (route === "complaints") {
    if (data.grouped) {
      container.appendChild(formatIssueRanking(items));
    } else {
      const grid = document.createElement("div");
      grid.className = "anomaly-grid";
      items.forEach((item) => grid.appendChild(formatComplaintCard(item)));
      container.appendChild(grid);
    }

  } else {
    // Stations — bölge bazlı gruplama varsa grupla, yoksa kart listesi
    if (data.filters?.status && !data.filters?.region) {
      // Bölgeye göre grupla (hangi bölgede offline gibi sorgular)
      const byRegion = {};
      items.forEach(item => {
        const r = item.region || "Bilinmiyor";
        if (!byRegion[r]) byRegion[r] = [];
        byRegion[r].push(item);
      });
      container.appendChild(formatStationsByRegion(byRegion, data.filters.status));
    } else {
      const grid = document.createElement("div");
      grid.className = "anomaly-grid";
      items.forEach((item) => grid.appendChild(formatStationCard(item)));
      container.appendChild(grid);
    }
  }

  return container;
}


function renderLlmResponse(payload) {
  const container = document.createElement("div");

  const summaryCard = document.createElement("div");
  summaryCard.className = "summary";
  summaryCard.innerHTML = `
    <div class="summary-title">Sonuç Özeti</div>
    <div class="summary-text">${payload.summary || "Sonuç oluşturulamadı."}</div>
  `;
  container.appendChild(summaryCard);

  const rootCause = document.createElement("div");
  rootCause.className = "summary";
  rootCause.innerHTML = `
    <div class="summary-title">Kök Neden</div>
    <div class="summary-text">${payload.root_cause || "Belirsiz"}</div>
  `;
  container.appendChild(rootCause);

  const actions = Array.isArray(payload.recommended_actions) ? payload.recommended_actions : [];
  const actionsCard = document.createElement("div");
  actionsCard.className = "summary";
  actionsCard.innerHTML = `
    <div class="summary-title">Önerilen Aksiyonlar</div>
    <div class="summary-text">
      ${actions.length ? actions.map((a) => `• ${a}`).join("<br>") : "Aksiyon bulunamadı."}
    </div>
  `;
  container.appendChild(actionsCard);

  const confidenceVal = Number(payload.confidence ?? 0);
  const confidence = Number.isFinite(confidenceVal) ? confidenceVal : 0;
  const confidenceScore = Math.max(0, Math.min(1, confidence)) * 100;

  const confidenceCard = document.createElement("div");
  confidenceCard.className = "summary";

  // Confidence seviyesine göre renk
  let confidenceColor = "#10b981"; // yeşil
  if (confidenceScore < 50) {
    confidenceColor = "#ef4444"; // kırmızı
  } else if (confidenceScore < 75) {
    confidenceColor = "#f59e0b"; // turuncu
  }

  confidenceCard.innerHTML = `
    <div class="summary-title">Güven Skoru</div>
    <div class="summary-text">
      <div style="display: flex; align-items: center; gap: 12px;">
        <div style="flex: 1; background: rgba(255,255,255,0.1); border-radius: 999px; height: 12px; overflow: hidden;">
          <div style="background: ${confidenceColor}; height: 100%; width: ${confidenceScore}%; transition: width 0.5s ease;"></div>
        </div>
        <strong style="color: ${confidenceColor}; font-size: 1.2rem;">${confidenceScore.toFixed(0)}%</strong>
      </div>
    </div>
  `;
  container.appendChild(confidenceCard);

  return container;
}
chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const message = messageInput.value.trim();
  const limit = Number(limitInput.value || 20);
  if (!message) return;

  addMessage(`${message}`, "user");
  messageInput.value = "";

  // Loading göster
  const loadingDiv = document.createElement("div");
  loadingDiv.className = "msg bot";
  loadingDiv.innerHTML = '<span class="loading"></span> Sorgunuz işleniyor...';
  chatBox.appendChild(loadingDiv);
  chatBox.scrollTop = chatBox.scrollHeight;

  try {
    const res = await fetch(`${API_BASE}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, limit }),
    });

    // Loading'i kaldır
    chatBox.removeChild(loadingDiv);

    const responseData = await res.json();
    if (!res.ok) {
      addMessage(`❌ Hata: ${responseData.detail || "Bilinmeyen hata"}`, "bot");
      return;
    }

    // Formatlanmış yanıt
    const formattedResponse = renderLlmResponse(responseData);
    addMessage(formattedResponse, "bot");

  } catch (err) {
    chatBox.removeChild(loadingDiv);
    addMessage(`❌ Bağlantı hatası: ${err.message}`, "bot");
  }
});

