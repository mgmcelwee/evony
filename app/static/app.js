let TOKEN = null;
let NEXT_BEFORE_ID = null;
let AUTO_REFRESH = false;
let AUTO_TIMER = null;

function el(id) { return document.getElementById(id); }

function normalizeBaseUrl(raw) {
  let b = (raw || "").trim();

  // Default: same origin as the UI page (best for LAN usage, avoids CORS)
  if (!b) return window.location.origin;

  // allow user to paste host:port without scheme
  if (!/^https?:\/\//i.test(b)) b = "http://" + b;

  // trim trailing slashes
  b = b.replace(/\/+$/, "");
  return b;
}

function getBase() {
  return normalizeBaseUrl(el("baseUrl").value);
}

function setStatus(id, msg) { el(id).textContent = msg || ""; }

function fmtTime(iso) {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

async function api(path, opts = {}) {
  const base = getBase();
  const url = base + path;

  const headers = opts.headers ? { ...opts.headers } : {};
  if (TOKEN) headers["Authorization"] = `Bearer ${TOKEN}`;
  if (opts.json) headers["Content-Type"] = "application/json";

  let res;
  try {
    res = await fetch(url, { ...opts, headers });
  } catch (e) {
    // network / DNS / mixed-content / CORS preflight failures often show as TypeError: Failed to fetch
    throw new Error(`Failed to fetch (${url}). Check Base URL / CORS / server reachability.`);
  }

  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* ignore */ }

  if (!res.ok) {
    const detail = data?.detail ?? data ?? text;
    const msg = typeof detail === "string" ? detail : JSON.stringify(detail, null, 2);
    throw new Error(`HTTP ${res.status}: ${msg}`);
  }
  return data;
}

function saveToken() {
  try {
    if (TOKEN) localStorage.setItem("evony_token", TOKEN);
    else localStorage.removeItem("evony_token");
  } catch {}
}

function loadToken() {
  try {
    const t = localStorage.getItem("evony_token");
    if (t && typeof t === "string") TOKEN = t;
  } catch {}
}

async function ping() {
  try {
    const data = await api("/health", { method: "GET", headers: {} });
    setStatus("apiStatus", `API: ok (${data.status}) | Base: ${getBase()}`);
  } catch (e) {
    setStatus("apiStatus", `API: ❌ ${e.message}`);
  }
}

async function login() {
  setStatus("loginStatus", "Logging in...");
  TOKEN = null;
  saveToken();

  const username = el("username").value.trim();
  const password = el("password").value;

  const data = await api("/auth/login", {
    method: "POST",
    json: true,
    body: JSON.stringify({ username, password }),
    headers: {}
  });

  TOKEN = data.token;
  saveToken();
  setStatus("loginStatus", `✅ Logged in`);
  await refreshAll(true);
}

function logout() {
  TOKEN = null;
  saveToken();
  setStatus("loginStatus", "Logged out.");
  setStatus("enqueueStatus", "");
  setStatus("cityStatus", "");
  el("resourcesBox").textContent = "{}";
  el("troopsBox").textContent = "[]";
  el("queueList").innerHTML = "";
  el("slotsLine").textContent = "Slots: ? / ?";
  el("barracksLine").textContent = "Barracks: ?";
}

async function refreshCity() {
  const cityId = parseInt(el("cityId").value, 10);
  const city = await api(`/cities/${cityId}`);
  const troops = await api(`/cities/${cityId}/troops`);

  // Your API previously returned resources either at top-level or under "resources"
  const resources = city.resources ?? {
    food: city.food, wood: city.wood, stone: city.stone, iron: city.iron
  };

  el("resourcesBox").textContent = JSON.stringify(resources, null, 2);
  el("troopsBox").textContent = JSON.stringify(troops.troops ?? troops, null, 2);
}

function renderQueue(queueResp, append = false) {
  const list = el("queueList");
  if (!append) list.innerHTML = "";

  // Slots + barracks info come from queue endpoint response
  const slots = queueResp.slots || null;
  const rules = queueResp.rules || null;

  if (slots) {
    el("slotsLine").textContent = `Slots: ${slots.used} / ${slots.total} (free ${slots.free})`;
    el("enqueueBtn").disabled = (slots.free <= 0);
  } else {
    el("slotsLine").textContent = "Slots: ? / ?";
    el("enqueueBtn").disabled = false;
  }

  if (rules) {
    el("barracksLine").textContent = `Barracks: L${rules.barracks_level} (max_batch ${rules.max_batch})`;
  } else {
    el("barracksLine").textContent = "Barracks: ?";
  }

  for (const item of (queueResp.queue || [])) {
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = `
      <div class="itemTop">
        <div>
          <div><b>#${item.id}</b> ${item.name} <span class="small">(${item.code})</span></div>
          <div class="small">count=${item.count} | status=${item.status} | finishes=${fmtTime(item.finishes_at)}</div>
        </div>
        <div>
          ${item.status === "training" ? `<button data-cancel="${item.id}">Cancel</button>` : ``}
        </div>
      </div>
      <div class="small">cost: food=${item.cost.food} wood=${item.cost.wood} stone=${item.cost.stone} iron=${item.cost.iron}</div>
    `;
    list.appendChild(div);
  }

  // wire cancel buttons
  list.querySelectorAll("button[data-cancel]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const cityId = parseInt(el("cityId").value, 10);
      const qid = btn.getAttribute("data-cancel");
      setStatus("enqueueStatus", `Cancelling #${qid}...`);
      try {
        await api(`/cities/${cityId}/train/queue/${qid}/cancel`, { method: "POST" });
        setStatus("enqueueStatus", `✅ Cancelled #${qid}`);
        await refreshAll(true);
      } catch (e) {
        setStatus("enqueueStatus", `❌ ${e.message}`);
      }
    });
  });

  NEXT_BEFORE_ID = queueResp.next_before_id ?? null;
  el("loadMoreBtn").disabled = !NEXT_BEFORE_ID;
}

async function refreshQueue(resetPaging = true) {
  const cityId = parseInt(el("cityId").value, 10);
  if (resetPaging) NEXT_BEFORE_ID = null;

  const q = new URLSearchParams();
  q.set("limit", "50");
  if (!resetPaging && NEXT_BEFORE_ID) q.set("before_id", String(NEXT_BEFORE_ID));

  const queueResp = await api(`/cities/${cityId}/train/queue?${q.toString()}`);
  renderQueue(queueResp, !resetPaging);
}

async function refreshAll(resetPaging = true) {
  setStatus("cityStatus", "Refreshing...");
  try {
    await refreshCity();
    await refreshQueue(true);
    setStatus("cityStatus", "✅");
  } catch (e) {
    setStatus("cityStatus", `❌ ${e.message}`);
  }
}

async function enqueue() {
  const cityId = parseInt(el("cityId").value, 10);
  const code = el("trainCode").value.trim();
  const count = parseInt(el("trainCount").value, 10);

  setStatus("enqueueStatus", "Enqueueing...");
  try {
    const resp = await api(`/cities/${cityId}/train/queue`, {
      method: "POST",
      json: true,
      body: JSON.stringify({ troops: [{ code, count }] })
    });

    // Optional: reflect slots returned from POST (if you added it there)
    if (resp && resp.slots) {
      el("slotsLine").textContent = `Slots: ${resp.slots.used} / ${resp.slots.total} (free ${resp.slots.free})`;
    }

    setStatus("enqueueStatus", "✅ Enqueued");
    await refreshAll(true);
  } catch (e) {
    setStatus("enqueueStatus", `❌ ${e.message}`);
  }
}

function setAutoRefresh(on) {
  AUTO_REFRESH = !!on;
  el("toggleAutoBtn").textContent = `Auto-refresh: ${AUTO_REFRESH ? "on" : "off"}`;

  if (AUTO_TIMER) {
    clearInterval(AUTO_TIMER);
    AUTO_TIMER = null;
  }
  if (AUTO_REFRESH) {
    AUTO_TIMER = setInterval(() => {
      if (TOKEN) refreshAll(true).catch(() => {});
    }, 5000);
  }
}

function wire() {
  // auto-fill Base URL to the server that served /ui/
  el("baseUrl").value = window.location.origin;

  loadToken();
  if (TOKEN) setStatus("loginStatus", "Token loaded from localStorage (try Refresh).");

  el("loginBtn").addEventListener("click", () =>
    login().catch(e => setStatus("loginStatus", `❌ ${e.message}`))
  );
  el("logoutBtn").addEventListener("click", () => logout());
  el("refreshBtn").addEventListener("click", () => refreshAll(true));

  el("enqueueBtn").addEventListener("click", () => enqueue());

  el("toggleAutoBtn").addEventListener("click", () => setAutoRefresh(!AUTO_REFRESH));

  el("loadMoreBtn").addEventListener("click", async () => {
    if (!NEXT_BEFORE_ID) return;
    try {
      await refreshQueue(false);
    } catch (e) {
      setStatus("enqueueStatus", `❌ ${e.message}`);
    }
  });

  // initial ping
  ping().catch(() => {});
}

wire();

