const TOKEN_KEY = "dashboard_api_token";

function getToken() {
  const input = document.getElementById("apiToken");
  return (input && input.value.trim()) || localStorage.getItem(TOKEN_KEY) || "";
}

function setAuthStatus(msg, ok) {
  const el = document.getElementById("authStatus");
  if (!el) return;
  el.textContent = msg || "";
  el.classList.remove("is-ok", "is-err");
  if (msg) el.classList.add(ok ? "is-ok" : "is-err");
}

function setEmptyVisible(panelPrefix, visible) {
  const el = document.getElementById(`${panelPrefix}Empty`);
  if (el) el.hidden = !visible;
}

async function api(path, options = {}) {
  const token = getToken();
  const headers = {
    Accept: "application/json",
    ...(options.headers || {}),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(path, { ...options, headers });
  const text = await res.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { raw: text };
  }
  if (!res.ok) {
    const err = new Error(data.error || res.statusText || "Erro HTTP");
    err.status = res.status;
    err.body = data;
    throw err;
  }
  return data;
}

function initTabs() {
  const tabs = document.querySelectorAll(".tab");
  const panels = document.querySelectorAll(".tab-panel");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const name = tab.dataset.tab;
      tabs.forEach((t) => {
        t.classList.toggle("active", t === tab);
        t.setAttribute("aria-selected", t === tab ? "true" : "false");
      });
      panels.forEach((p) => {
        p.classList.toggle("active", p.id === `panel-${name}`);
      });
    });
  });
}

function tbody(tableId) {
  const t = document.getElementById(tableId);
  return t.querySelector("tbody");
}

function addRow(tableId, row = {}) {
  const tb = tbody(tableId);
  const tr = document.createElement("tr");

  const tdId = document.createElement("td");
  const inId = document.createElement("input");
  inId.type = "text";
  inId.className = "cell-id input";
  inId.value = row.external_id || "";
  tdId.appendChild(inId);

  const tdName = document.createElement("td");
  const inName = document.createElement("input");
  inName.type = "text";
  inName.className = "cell-name input";
  inName.value = row.display_name || "";
  tdName.appendChild(inName);

  const tdEn = document.createElement("td");
  const ch = document.createElement("input");
  ch.type = "checkbox";
  ch.className = "cell-enabled";
  ch.checked = row.enabled !== false;
  tdEn.appendChild(ch);

  const tdRm = document.createElement("td");
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "btn danger row-remove";
  btn.textContent = "Remover";
  btn.addEventListener("click", () => tr.remove());
  tdRm.appendChild(btn);

  tr.appendChild(tdId);
  tr.appendChild(tdName);
  tr.appendChild(tdEn);
  tr.appendChild(tdRm);
  tb.appendChild(tr);
}

function readTable(tableId) {
  const rows = [];
  tbody(tableId).querySelectorAll("tr").forEach((tr) => {
    const external_id = tr.querySelector(".cell-id").value.trim();
    const display_name = tr.querySelector(".cell-name").value.trim();
    const enabled = tr.querySelector(".cell-enabled").checked;
    if (!external_id && !display_name) return;
    rows.push({ external_id, display_name, enabled });
  });
  return { accounts: rows };
}

async function loadMeta() {
  const data = await api("/api/accounts/meta");
  document.getElementById("metaSource").textContent = data.source ? `Fonte · ${data.source}` : "—";
  const tb = tbody("metaTable");
  tb.innerHTML = "";
  const list = data.accounts || [];
  list.forEach((r) => addRow("metaTable", r));
  if (list.length === 0) addRow("metaTable", {});
  setEmptyVisible("meta", list.length === 0);
}

async function loadGoogle() {
  const data = await api("/api/accounts/google");
  document.getElementById("googleSource").textContent = data.source ? `Fonte · ${data.source}` : "—";
  const tb = tbody("googleTable");
  tb.innerHTML = "";
  const list = data.accounts || [];
  list.forEach((r) => addRow("googleTable", r));
  if (list.length === 0) addRow("googleTable", {});
  setEmptyVisible("google", list.length === 0);
}

async function saveMeta() {
  const body = readTable("metaTable");
  const data = await api("/api/accounts/meta", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  setAuthStatus(`Salvo (${data.saved}, ${data.count ?? body.accounts.length} contas).`, true);
  await loadMeta();
}

async function saveGoogle() {
  const body = readTable("googleTable");
  const data = await api("/api/accounts/google", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  setAuthStatus(`Salvo (${data.saved}, ${data.count ?? body.accounts.length} contas).`, true);
  await loadGoogle();
}

async function refreshMetaBalances() {
  const out = document.getElementById("metaBalancesOut");
  out.textContent = "Carregando…";
  try {
    const data = await api("/api/balances/meta");
    out.textContent = JSON.stringify(data, null, 2);
    setAuthStatus("Saldos Meta atualizados.", true);
  } catch (e) {
    out.textContent = JSON.stringify(e.body || e.message, null, 2);
    setAuthStatus(e.message, false);
  }
}

async function refreshGoogleBalances() {
  const out = document.getElementById("googleBalancesOut");
  out.textContent = "Carregando…";
  try {
    const data = await api("/api/balances/google");
    out.textContent = JSON.stringify(data, null, 2);
    setAuthStatus("Saldos Google atualizados.", true);
  } catch (e) {
    out.textContent = JSON.stringify(e.body || e.message, null, 2);
    setAuthStatus(e.message, false);
  }
}

const STYLE_KEYS = ["title", "reference_line", "criterion_line", "account_line", "footer"];

let styleDefaults = null;
let scheduleTimezone = "America/Sao_Paulo";

function applyStyleToForm(provider, obj) {
  const block = obj && typeof obj === "object" ? obj : {};
  for (const k of STYLE_KEYS) {
    const el = document.getElementById(`style-${provider}-${k}`);
    if (el) el.value = block[k] != null ? String(block[k]) : "";
  }
}

function collectStyle(provider) {
  const o = {};
  for (const k of STYLE_KEYS) {
    const el = document.getElementById(`style-${provider}-${k}`);
    if (el) o[k] = el.value;
  }
  return o;
}

function renderStyleHelp(help) {
  const ul = document.getElementById("placeholderList");
  const note = document.getElementById("placeholderNote");
  if (!ul || !note) return;
  ul.innerHTML = "";
  const items = (help && help.placeholders) || [];
  items.forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    ul.appendChild(li);
  });
  note.textContent = (help && help.note) || "";
}

async function loadAlertStyle() {
  const data = await api("/api/alert-style");
  styleDefaults = data.defaults || null;
  applyStyleToForm("meta", data.meta);
  applyStyleToForm("google", data.google);
  renderStyleHelp(data.help);
  const pm = document.getElementById("stylePreviewMeta");
  const pg = document.getElementById("stylePreviewGoogle");
  if (pm) pm.textContent = data.preview_meta || "";
  if (pg) pg.textContent = data.preview_google || "";
}

async function saveAlertStyle() {
  const body = { meta: collectStyle("meta"), google: collectStyle("google") };
  const data = await api("/api/alert-style", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  setAuthStatus(`Mensagens salvas (${data.saved || "ok"}).`, true);
  await loadAlertStyle();
}

async function previewAlertStyle() {
  const body = { meta: collectStyle("meta"), google: collectStyle("google") };
  const data = await api("/api/alert-style/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const pm = document.getElementById("stylePreviewMeta");
  const pg = document.getElementById("stylePreviewGoogle");
  if (pm) pm.textContent = data.preview_meta || "";
  if (pg) pg.textContent = data.preview_google || "";
  setAuthStatus("Prévia atualizada (rascunho atual).", true);
}

function parseScheduleTimes(text) {
  return text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function applyScheduleToForm(data) {
  const timesEl = document.getElementById("scheduleTimes");
  const metaEl = document.getElementById("scheduleMetaEnabled");
  const googleEl = document.getElementById("scheduleGoogleEnabled");
  const hint = document.getElementById("scheduleCronHint");
  if (timesEl) timesEl.value = (data.times || []).join("\n");
  if (metaEl) metaEl.checked = data.meta_enabled !== false;
  if (googleEl) googleEl.checked = data.google_enabled !== false;
  if (hint) {
    hint.textContent = data.cron
      ? `CRON no container: ${data.cron} · fuso ${data.timezone || "TZ do servidor"}`
      : "";
  }
}

function collectSchedulePayload() {
  const timesEl = document.getElementById("scheduleTimes");
  const metaEl = document.getElementById("scheduleMetaEnabled");
  const googleEl = document.getElementById("scheduleGoogleEnabled");
  return {
    times: parseScheduleTimes(timesEl ? timesEl.value : ""),
    timezone: scheduleTimezone,
    meta_enabled: metaEl ? metaEl.checked : true,
    google_enabled: googleEl ? googleEl.checked : true,
  };
}

function applyThresholdsToForm(data) {
  const alertEl = document.getElementById("alertThreshold");
  const nearEl = document.getElementById("nearThreshold");
  if (alertEl && data.alert_threshold != null) alertEl.value = data.alert_threshold;
  if (nearEl && data.near_threshold != null) nearEl.value = data.near_threshold;
}

function collectThresholdsPayload() {
  const alertEl = document.getElementById("alertThreshold");
  const nearEl = document.getElementById("nearThreshold");
  return {
    alert_threshold: parseFloat(alertEl?.value || "200"),
    near_threshold: parseFloat(nearEl?.value || "120"),
  };
}

async function loadMonitorThresholds() {
  const data = await api("/api/monitor/thresholds");
  applyThresholdsToForm(data);
}

async function saveMonitorThresholds() {
  const body = collectThresholdsPayload();
  const data = await api("/api/monitor/thresholds", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  applyThresholdsToForm(data.thresholds || body);
  return data;
}

async function loadMonitorSchedule() {
  const data = await api("/api/monitor/schedule");
  if (data.timezone) scheduleTimezone = data.timezone;
  applyScheduleToForm(data);
  applyThresholdsToForm(data);
  if (data.alert_threshold == null) {
    await loadMonitorThresholds().catch(() => {});
  }
}

async function saveMonitorSchedule() {
  const schedBody = collectSchedulePayload();
  const schedData = await api("/api/monitor/schedule", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(schedBody),
  });
  applyScheduleToForm({ ...schedData.schedule, cron: schedData.cron });

  const thData = await saveMonitorThresholds();
  const msg = [
    schedData.note || "Agendamento salvo.",
    thData.note || `Limites: alerta R$ ${thData.thresholds?.alert_threshold}.`,
  ].join(" ");
  setAuthStatus(msg, true);
}

async function runMonitor(platform, force) {
  const out = document.getElementById("monitorRunOut");
  if (out) out.textContent = "Executando…";
  const data = await api("/api/monitor/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ platform, force }),
  });
  if (out) out.textContent = JSON.stringify(data, null, 2);
  const parts = [];
  if (data.meta) {
    parts.push(
      data.meta.sent
        ? "Meta: mensagem enviada."
        : `Meta: ${data.meta.summary?.motivo || data.meta.error || "sem envio"}`
    );
  }
  if (data.google) {
    parts.push(
      data.google.sent
        ? "Google: mensagem enviada."
        : `Google: ${data.google.summary?.motivo || data.google.error || "sem envio"}`
    );
  }
  setAuthStatus(parts.join(" ") || "Execução concluída.", data.meta?.sent || data.google?.sent);
}

function resetStylesToDefaults() {
  if (!styleDefaults) {
    setAuthStatus("Carregue os dados primeiro (token + recarregar).", false);
    return;
  }
  applyStyleToForm("meta", styleDefaults.meta || {});
  applyStyleToForm("google", styleDefaults.google || {});
  setAuthStatus("Campos restaurados para os padrões do sistema. Clique em Salvar para persistir.", true);
}

function init() {
  const input = document.getElementById("apiToken");
  const saved = localStorage.getItem(TOKEN_KEY);
  if (saved) input.value = saved;

  document.getElementById("saveToken").addEventListener("click", () => {
    localStorage.setItem(TOKEN_KEY, input.value.trim());
    setAuthStatus("Token salvo neste navegador.", true);
    loadMeta().catch((e) => setAuthStatus(e.message, false));
    loadGoogle().catch(() => {});
    loadAlertStyle().catch((e) => setAuthStatus(e.message, false));
    loadMonitorSchedule().catch(() => {});
  });

  initTabs();

  document.getElementById("metaReload").addEventListener("click", () => {
    loadMeta().catch((e) => setAuthStatus(e.message, false));
  });
  document.getElementById("metaAdd").addEventListener("click", () => addRow("metaTable", {}));
  document.getElementById("metaSave").addEventListener("click", () => {
    saveMeta().catch((e) => setAuthStatus(e.message, false));
  });
  document.getElementById("metaBalances").addEventListener("click", () => {
    refreshMetaBalances().catch((e) => setAuthStatus(e.message, false));
  });

  document.getElementById("googleReload").addEventListener("click", () => {
    loadGoogle().catch((e) => setAuthStatus(e.message, false));
  });
  document.getElementById("googleAdd").addEventListener("click", () => addRow("googleTable", {}));
  document.getElementById("googleSave").addEventListener("click", () => {
    saveGoogle().catch((e) => setAuthStatus(e.message, false));
  });
  document.getElementById("googleBalances").addEventListener("click", () => {
    refreshGoogleBalances().catch((e) => setAuthStatus(e.message, false));
  });

  const saveStyles = document.getElementById("saveStyles");
  const previewStyles = document.getElementById("previewStyles");
  const resetStyles = document.getElementById("resetStyles");
  if (saveStyles) {
    saveStyles.addEventListener("click", () => {
      saveAlertStyle().catch((e) => setAuthStatus(e.message, false));
    });
  }
  if (previewStyles) {
    previewStyles.addEventListener("click", () => {
      previewAlertStyle().catch((e) => setAuthStatus(e.message, false));
    });
  }
  if (resetStyles) {
    resetStyles.addEventListener("click", () => resetStylesToDefaults());
  }

  const saveSchedule = document.getElementById("saveSchedule");
  if (saveSchedule) {
    saveSchedule.addEventListener("click", () => {
      saveMonitorSchedule().catch((e) => setAuthStatus(e.message, false));
    });
  }

  document.querySelectorAll("[data-run]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const platform = btn.getAttribute("data-run") || "both";
      const force = btn.getAttribute("data-force") === "true";
      runMonitor(platform, force).catch((e) => setAuthStatus(e.message, false));
    });
  });

  loadMeta().catch((e) => setAuthStatus(e.message, false));
  loadGoogle().catch(() => {});
  loadAlertStyle().catch(() => {});
  loadMonitorSchedule().catch(() => {});
}

document.addEventListener("DOMContentLoaded", init);
