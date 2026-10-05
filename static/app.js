const uploadForm = document.getElementById("uploadForm");
const fileInput = document.getElementById("fileInput");
const dropzone = document.getElementById("dropzone");
const fileName = document.getElementById("fileName");
const status = document.getElementById("status");
const loadingState = document.getElementById("loadingState");
const emptyState = document.getElementById("emptyState");
const dashboard = document.getElementById("dashboard");
const themeToggle = document.getElementById("themeToggle");
const themeLabel = document.getElementById("themeLabel");
let latestPayload = null;

const savedTheme = localStorage.getItem("chronosops-theme");
applyTheme(savedTheme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"));
themeToggle.addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark");
  if (latestPayload && !dashboard.classList.contains("d-none")) renderDashboard(latestPayload);
});

fileInput.addEventListener("change", () => {
  fileName.textContent = fileInput.files?.[0]?.name || "Drop CSV here";
});

["dragenter", "dragover"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropzone.classList.add("dragging");
}));
["dragleave", "drop"].forEach((eventName) => dropzone.addEventListener(eventName, (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragging");
}));
dropzone.addEventListener("drop", (event) => {
  const file = event.dataTransfer.files?.[0];
  if (!file) return;
  const transfer = new DataTransfer();
  transfer.items.add(file);
  fileInput.files = transfer.files;
  fileName.textContent = file.name;
});

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = fileInput.files?.[0];
  const targetColumn = document.getElementById("targetColumn").value.trim();
  const forecastHorizon = document.getElementById("forecastHorizon").value || 12;

  if (!file) {
    setStatus("Choose a CSV file before running the brief.", true);
    return;
  }
  setStatus("Processing operational signal…");
  loadingState.classList.remove("d-none");
  emptyState.classList.add("d-none");
  dashboard.classList.add("d-none");

  const formData = new FormData();
  formData.append("file", file);
  if (targetColumn) formData.append("target_column", targetColumn);
  formData.append("forecast_horizon", forecastHorizon);

  try {
    const response = await fetch("/api/upload", { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "The dataset could not be analyzed.");
    renderDashboard(payload);
    setStatus("Intelligence brief ready.");
  } catch (error) {
    setStatus(error.message || "Unable to process the dataset.", true);
    emptyState.classList.remove("d-none");
  } finally {
    loadingState.classList.add("d-none");
  }
});

function setStatus(message, isError = false) {
  status.classList.toggle("error", isError);
  status.innerHTML = `<span class="status-icon">${isError ? "!" : "i"}</span> ${escapeHtml(message)}`;
}

function renderDashboard(payload) {
  latestPayload = payload;
  const profile = payload.dataset_profile || {};
  const forecast = payload.forecast || {};
  const anomalies = payload.anomalies || [];
  const rootCauses = payload.root_causes || [];
  const ts = forecast.time_series || {};

  document.getElementById("qualityScore").textContent = `${profile.quality_score ?? 0}/100`;
  document.getElementById("rowsCount").textContent = formatNumber(profile.rows);
  document.getElementById("targetName").textContent = forecast.target_column || "—";
  document.getElementById("bestModel").textContent = forecast.selected_model || "—";
  document.getElementById("analysisTimestamp").textContent = `// ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`;
  document.getElementById("anomalyCount").textContent = `${anomalies.length} flagged events`;

  document.getElementById("tsInsights").innerHTML = [
    ["Trend slope", ts.trend ?? 0],
    ["Seasonality index", ts.seasonality_score ?? 0],
    ["Stationarity p-value", ts.stationarity_p_value ?? 1],
    ["Autocorrelation", ts.autocorrelation ?? 0],
    ["Change points", Array.isArray(ts.change_points) ? ts.change_points.length : 0],
  ].map(([label, value]) => `<li><span>${label}</span><strong>${value}</strong></li>`).join("");

  const missingCount = Object.values(profile.missing_values || {}).reduce((sum, value) => sum + Number(value), 0);
  document.getElementById("datasetProfile").innerHTML = [
    ["Timestamp column", profile.timestamp_column || "None"],
    ["Numeric features", (profile.numeric_columns || []).length],
    ["Missing values", missingCount],
    ["Duplicate rows", profile.duplicate_rows ?? 0],
    ["Sampling variance", profile.irregular_sampling ?? 0],
  ].map(([label, value]) => `<div class="metric-row"><span>${label}</span><strong>${escapeHtml(String(value))}</strong></div>`).join("");

  const comparison = forecast.comparison || [];
  document.getElementById("modelTable").innerHTML = `<table class="model-table"><thead><tr><th>Model</th><th>MAE</th><th>RMSE</th><th>sMAPE</th></tr></thead><tbody>${comparison.map((entry) => {
    const metrics = entry.metrics || {};
    const isBest = entry.model === forecast.selected_model;
    return `<tr class="${isBest ? "is-best" : ""}"><td>${escapeHtml(entry.model)}</td><td>${metrics.MAE ?? "—"}</td><td>${metrics.RMSE ?? "—"}</td><td>${metrics.sMAPE ?? "—"}</td></tr>`;
  }).join("")}</tbody></table>`;

  document.getElementById("rootCauseList").innerHTML = rootCauses.length
    ? rootCauses.map((item) => `<li><span>${escapeHtml(item.feature)}</span><span class="cause-value">${item.contribution}% ${item.direction}</span></li>`).join("")
    : "<li><span>No dominant contributor detected.</span></li>";

  const actual = forecast.validation_actual || [];
  const predicted = forecast.validation_predicted || [];
  const horizon = forecast.forecast_values || [];
  const chartLayout = {
    margin: { t: 10, r: 10, b: 35, l: 42 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: document.documentElement.dataset.theme === "dark" ? "rgba(27,33,27,.72)" : "rgba(255,255,255,.22)",
    font: { family: "DM Mono, monospace", size: 10, color: getComputedStyle(document.documentElement).getPropertyValue("--muted").trim() },
    legend: { orientation: "h", y: 1.12, x: 0 },
    xaxis: { gridcolor: getComputedStyle(document.documentElement).getPropertyValue("--line").trim(), zeroline: false, title: "TIME STEP" },
    yaxis: { gridcolor: getComputedStyle(document.documentElement).getPropertyValue("--line").trim(), zeroline: false },
  };
  Plotly.newPlot("forecastChart", [
    { x: actual.map((_, i) => i + 1), y: actual, mode: "lines+markers", name: "Observed", line: { color: "#101310", width: 2 }, marker: { color: "#101310", size: 5 } },
    { x: predicted.map((_, i) => i + 1), y: predicted, mode: "lines", name: "Validation", line: { color: "#ff795f", width: 2, dash: "dot" } },
    { x: horizon.map((_, i) => actual.length + i + 1), y: horizon, mode: "lines+markers", name: "Forecast", line: { color: "#8dad17", width: 3 }, marker: { color: "#c9f34a", size: 5 } },
  ], chartLayout, { displayModeBar: false, responsive: true });

  const anomalyTraces = anomalies.map((item) => ({
    x: [item.timestamp], y: [item.observed_value], type: "scatter", mode: "markers", name: item.metric,
    text: [`${item.metric} · ${item.severity}`], hoverinfo: "text+y", marker: { color: item.severity === "CRITICAL" ? "#101310" : item.severity === "HIGH" ? "#ff795f" : "#8dad17", size: 11, line: { color: "#f1eee5", width: 2 } },
  }));
  Plotly.newPlot("anomalyChart", anomalyTraces.length ? anomalyTraces : [{ x: [], y: [], type: "scatter", mode: "markers" }], { ...chartLayout, annotations: anomalyTraces.length ? [] : [{ text: "NO MAJOR EXCEPTIONS", x: .5, y: .5, xref: "paper", yref: "paper", showarrow: false, font: { family: "DM Mono", size: 11, color: "#687067" } }] }, { displayModeBar: false, responsive: true });
  dashboard.classList.remove("d-none");
}

function formatNumber(value) { return new Intl.NumberFormat().format(Number(value || 0)); }
function escapeHtml(value) { return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" }[char])); }
function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("chronosops-theme", theme);
  const isDark = theme === "dark";
  themeLabel.textContent = isDark ? "Light mode" : "Dark mode";
  themeToggle.setAttribute("aria-label", isDark ? "Switch to light mode" : "Switch to dark mode");
  themeToggle.setAttribute("aria-pressed", String(isDark));
}
window.addEventListener("resize", () => {
  if (!dashboard.classList.contains("d-none")) {
    Plotly.Plots.resize(document.getElementById("forecastChart"));
    Plotly.Plots.resize(document.getElementById("anomalyChart"));
  }
});
