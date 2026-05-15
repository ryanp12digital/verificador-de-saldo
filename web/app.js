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
  inId.className = "cell-id";
  inId.value = row.external_id || "";
  tdId.appendChild(inId);

  const tdName = document.createElement("td");
  const inName = document.createElement("input");
  inName.type = "text";
  inName.className = "cell-name";
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

function init() {
  const input = document.getElementById("apiToken");
  const saved = localStorage.getItem(TOKEN_KEY);
  if (saved) input.value = saved;

  document.getElementById("saveToken").addEventListener("click", () => {
    localStorage.setItem(TOKEN_KEY, input.value.trim());
    setAuthStatus("Token salvo neste navegador.", true);
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

  loadMeta().catch((e) => setAuthStatus(e.message, false));
  loadGoogle().catch(() => {});
}

document.addEventListener("DOMContentLoaded", init);
