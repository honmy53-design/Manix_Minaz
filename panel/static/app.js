"use strict";
const $ = (s, root = document) => root.querySelector(s);
const $$ = (s, root = document) => [...root.querySelectorAll(s)];
const shapes = {
  cube: '<path d="m12 3 9 5v8l-9 5-9-5V8z"/><path d="m3 8 9 5 9-5M12 13v8m-4-15 9 5"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  terminal:
    '<rect x="3" y="4" width="18" height="16" rx="3"/><path d="m7 8 4 4-4 4m7 0h3"/>',
  folder:
    '<path d="M3 7V5a2 2 0 0 1 2-2h4l3 4h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/>',
  "folder-plus":
    '<path d="M3 7V5a2 2 0 0 1 2-2h4l3 4h7a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7zM12 11v6m-3-3h6"/>',
  layers: '<path d="m12 3 10 5-10 5L2 8zm-9 9 9 5 9-5M3 16l9 5 9-5"/>',
  box: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18m-9 0v11M8 5V3h8v2"/>',
  users:
    '<circle cx="9" cy="8" r="3"/><path d="M3 20v-2a6 6 0 0 1 12 0v2m1-14a3 3 0 0 1 0 6m5 8v-2a6 6 0 0 0-3-5"/>',
  archive:
    '<rect x="3" y="3" width="18" height="5" rx="1"/><path d="M5 8v12h14V8m-10 5h6"/>',
  settings:
    '<path d="m9 3-1 3-3 1-2 3 2 3-1 3 3 2 3-1 2 3 3-1 1-3 3-1 2-3-2-3 1-3-3-2-3 1-2-3z"/><circle cx="12" cy="12" r="3"/>',
  sliders:
    '<path d="M4 21v-7m0-4V3m8 18v-4m0-4V3m8 18V11m0-4V3M1 10h6m2 7h6m2-10h6"/>',
  book: '<path d="M3 4h6a3 3 0 0 1 3 3v14a3 3 0 0 0-3-3H3zm18 0h-6a3 3 0 0 0-3 3v14a3 3 0 0 1 3-3h6z"/>',
  server:
    '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6h.1M7 17h.1m4-11h6m-6 11h6"/>',
  lock: '<rect x="5" y="10" width="14" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 4v3"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10h.01"/>',
  shield:
    '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
  logout: '<path d="M9 3H5v18h4m7-14 5 5-5 5m-7-5h12"/>',
  "arrow-left": '<path d="M20 12H4m6-6-6 6 6 6"/>',
  external: '<path d="M14 3h7v7m-11 4L21 3M10 3H3v18h18v-7"/>',
  menu: '<path d="M3 6h18M3 12h18M3 18h18"/>',
  wifi: '<path d="M3 8a15 15 0 0 1 18 0M6 12a10 10 0 0 1 12 0m-9 4a5 5 0 0 1 6 0m-3 4h.01"/>',
  globe:
    '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V3H3v13h5"/>',
  play: '<path d="m7 3 14 9L7 21z"/>',
  power: '<path d="M12 2v10m-6-7a9 9 0 1 0 12 0"/>',
  refresh:
    '<path d="M20 7a9 9 0 0 0-16 2m0 0V3m0 6h6m-6 8a9 9 0 0 0 16-2m0 0v6m0-6h-6"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 1v5m6-5v5M9 18v5m6-5v5M1 9h5m-5 6h5m12-6h5m-5 6h5M9 9h6v6H9z"/>',
  memory:
    '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10v4m4-4v4m4-4v4m4-4v4M6 18v3m4-3v3m4-3v3m4-3v3"/>',
  disk: '<path d="m6 3-4 12v6h20v-6L18 3zM2 15h20m-5 3h1m-5 0h1"/>',
  download: '<path d="M12 3v12m-5-5 5 5 5-5M3 15v6h18v-6"/>',
  upload: '<path d="M12 16V3m-5 5 5-5 5 5M3 16v5h18v-5"/>',
  send: '<path d="m22 2-7 20-4-9-9-4zM11 13 22 2"/>',
  trash: '<path d="M3 6h18m-13 0V3h8v3M5 6l1 15h12l1-15M10 10v7m4-7v7"/>',
  search: '<circle cx="10" cy="10" r="7"/><path d="m15 15 7 7"/>',
  check: '<path d="m4 12 5 5L20 6"/>',
  x: '<path d="m5 5 14 14M5 19 19 5"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
  file: '<path d="M14 2H4v20h16V8zM14 2v6h6m-12 5h8m-8 4h6"/>',
  "file-plus": '<path d="M14 2H4v20h16V8zM14 2v6h6m-9 4v6m-3-3h6"/>',
  edit: '<path d="m3 21 4-1L21 6l-4-4L3 16zm12-17 4 4M3 21h18"/>',
  save: '<path d="M3 3h15l3 3v15H3zM7 3v6h10V3M7 21v-8h10v8"/>',
  sparkles:
    '<path d="m12 3 2 6 6 3-6 2-2 7-2-7-6-2 6-3zm7-1v4m-2-2h4M3 17v4m-2-2h4"/>',
};
function iconMarkup(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${shapes[name] || shapes.box}</svg>`;
}
function icons(root = document) {
  $$("[data-icon]", root).forEach((x) => {
    x.innerHTML = iconMarkup(x.dataset.icon);
  });
}
function el(tag, cls = "", text = "") {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;
  return n;
}
function ico(name) {
  const n = el("i");
  n.dataset.icon = name;
  n.innerHTML = iconMarkup(name);
  return n;
}
function text(id, value) {
  const n = $(id);
  if (n) n.textContent = value;
}
function number(n, digits = 0) {
  return Number(n || 0).toLocaleString("fa-IR", {
    maximumFractionDigits: digits,
  });
}
function bytes(n) {
  if (n >= 1024 ** 3) return `${number(n / 1024 ** 3, 2)} GB`;
  if (n >= 1024 ** 2) return `${number(n / 1024 ** 2, 1)} MB`;
  if (n >= 1024) return `${number(n / 1024, 1)} KB`;
  return `${number(n)} B`;
}
function when(t) {
  return new Date(t * 1000).toLocaleString("fa-IR", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
const pages = {
  overview: "نمای کلی",
  console: "کنسول زنده",
  files: "مدیریت فایل‌ها",
  versions: "نسخه و هسته",
  addons: "مود و پلاگین",
  players: "بازیکن‌ها",
  backups: "بکاپ و سیو",
  settings: "تنظیمات و دامنه",
  guide: "راهنمای اتصال",
  worlds: "دنیاها",
  packs: "ریسورس‌پک",
  schedules: "زمان‌بندی",
  account: "حساب و امنیت",
};
const loaders = {
  vanilla: {
    name: "Vanilla",
    label: "بازی اصلی",
    help: "سرور اصلی Mojang، بدون مود یا پلاگین.",
    icon: "cube",
  },
  paper: {
    name: "Paper",
    label: "پلاگین",
    help: "بهینه‌شده برای سرورهای معمولی؛ با پشتیبانی از پلاگین‌های Paper و Bukkit.",
    icon: "layers",
  },
  purpur: {
    name: "Purpur",
    label: "پلاگین + تنظیمات",
    help: "مبتنی بر Paper، با تنظیمات بیشتر برای گیم‌پلی.",
    icon: "sliders",
  },
  fabric: {
    name: "Fabric",
    label: "مود",
    help: "لودر سبک برای مودهای Fabric. وابستگی‌هایی مثل Fabric API ممکن است لازم باشند.",
    icon: "box",
  },
  forge: {
    name: "Forge",
    label: "مود",
    help: "لودر Forge برای مودهای Forge؛ بیلد Recommended در صورت وجود انتخاب می‌شود.",
    icon: "settings",
  },
  neoforge: {
    name: "NeoForge",
    label: "مود",
    help: "مودهای مخصوص NeoForge؛ فقط بیلدهای پایدار نصاب در نصب خودکار نمایش داده می‌شوند.",
    icon: "sparkles",
  },
};
let csrf = "",
  account = "",
  currentPage = "overview",
  server = null,
  config = null,
  currentPath = "",
  selectedKind = "paper",
  versionList = [],
  versionRequest = 0,
  logCursor = 0,
  localBusy = false,
  authenticated = false,
  pollTimer = null,
  polling = false,
  settingsLoading = false,
  editorPath = "",
  editorOriginal = "",
  searchOffset = 0,
  searchTotal = 0,
  currentAddonContext = {};
const memorySamples = [],
  seenJobs = new Set(),
  dismissedJobs = new Set();
const startedAt = Date.now() / 1000;

function toast(message, error = false) {
  const n = el("div", `toast${error ? " error" : ""}`);
  n.append(ico(error ? "info" : "check"), el("p", "", message));
  $("#toasts").append(n);
  setTimeout(() => n.remove(), error ? 8500 : 5500);
}
async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
    options.body = JSON.stringify(options.body);
  }
  if (options.method && options.method !== "GET")
    headers.set("X-CSRF-Token", csrf);
  let response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      headers,
      signal: AbortSignal.timeout(65000),
    });
  } catch {
    throw new Error(
      "ارتباط با پنل برقرار نشد. صفحه را تازه کن یا لاگ Railway را بررسی کن.",
    );
  }
  let data = {};
  try {
    data = await response.json();
  } catch {}
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/login") showLogin();
    const err = new Error(
      typeof data.detail === "string"
        ? data.detail
        : `درخواست ناموفق بود (${response.status})`,
    );
    err.status = response.status;
    throw err;
  }
  return data;
}
async function action(fn) {
  if (localBusy) {
    toast("یک درخواست دیگر در حال اجراست.");
    return;
  }
  localBusy = true;
  updateButtons();
  try {
    await fn();
    if (authenticated) await refreshStatus();
  } catch (e) {
    toast(e.message, true);
  } finally {
    localBusy = false;
    updateButtons();
  }
}
function safe(fn) {
  return (...args) =>
    Promise.resolve(fn(...args)).catch((e) => toast(e.message, true));
}
function showLogin() {
  authenticated = false;
  csrf = "";
  server = null;
  clearTimeout(pollTimer);
  $("#boot").hidden = true;
  $("#app").hidden = true;
  $("#loginScreen").hidden = false;
  $("#loginPassword").value = "";
  $("#loginOtp").value = "";
  if (typeof clearAccountSecrets === "function") clearAccountSecrets();
}
async function enter(data) {
  csrf = data.csrf;
  account = data.username;
  authenticated = true;
  text("#accountName", account);
  text("#appVersion", "v" + data.version);
  const initialSettings = await api("/api/settings");
  config = initialSettings.config;
  selectedKind = loaders[config.engine?.kind] ? config.engine.kind : "paper";
  text(
    "#uploadLimit",
    "سقف آپلود " + number(initialSettings.upload_mb) + " MB",
  );
  $("#boot").hidden = true;
  $("#loginScreen").hidden = true;
  $("#app").hidden = false;
  try {
    await refreshStatus();
  } catch (e) {
    $("#connectionWarning").hidden = false;
    toast(e.message, true);
  }
  await goPage(location.hash.slice(1) || "overview", false);
  schedulePoll();
}
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const button = $("button[type=submit]", e.currentTarget);
  button.disabled = true;
  $("#loginError").hidden = true;
  try {
    const data = await api("/api/login", {
      method: "POST",
      body: {
        username: $("#loginUser").value,
        password: $("#loginPassword").value,
        otp: $("#loginOtp").value.trim(),
      },
    });
    $("#loginPassword").value = "";
    $("#loginOtp").value = "";
    await enter(data);
    toast("ورود امن به مانیکس انجام شد.");
  } catch (err) {
    text("#loginError", err.message);
    $("#loginError").hidden = false;
  } finally {
    button.disabled = false;
  }
});
$("#logout").addEventListener(
  "click",
  safe(async () => {
    await api("/api/logout", { method: "POST" });
    showLogin();
  }),
);
async function goPage(name, changeHash = true) {
  if (!pages[name]) name = "overview";
  currentPage = name;
  if (changeHash && location.hash !== "#" + name)
    history.replaceState(null, "", "#" + name);
  $$("[data-section]").forEach((n) => (n.hidden = n.dataset.section !== name));
  $$("[data-page]").forEach((n) => {
    n.classList.toggle("active", n.dataset.page === name);
    if (n.dataset.page === name) n.setAttribute("aria-current", "page");
    else n.removeAttribute("aria-current");
  });
  text("#pageTitle", pages[name]);
  $("#sidebar").classList.remove("open");
  $("#menuToggle").setAttribute("aria-expanded", "false");
  try {
    await loadPage(name);
  } catch (e) {
    toast(e.message, true);
  }
  updateButtons();
}
async function loadPage(name) {
  if (name === "files") await loadFiles();
  else if (name === "versions") await loadVersions(selectedKind);
  else if (name === "addons") await loadAddons();
  else if (name === "players") await loadPlayers();
  else if (name === "backups") await loadBackups();
  else if (name === "settings") await loadSettings();
  else if (["worlds", "packs", "schedules", "account"].includes(name))
    await loadManixPage(name);
}
$("#navigation").addEventListener(
  "click",
  safe(async (e) => {
    const a = e.target.closest("[data-page]");
    if (a) {
      e.preventDefault();
      await goPage(a.dataset.page);
    }
  }),
);
$$("[data-goto]").forEach((n) =>
  n.addEventListener("click", () => goPage(n.dataset.goto)),
);
window.addEventListener("hashchange", () => {
  if (authenticated) goPage(location.hash.slice(1), false);
});
$("#menuToggle").addEventListener("click", () => {
  const opened = $("#sidebar").classList.toggle("open");
  $("#menuToggle").setAttribute("aria-expanded", String(opened));
});
$(".main-content").addEventListener("click", () => {
  $("#sidebar").classList.remove("open");
  $("#menuToggle").setAttribute("aria-expanded", "false");
});

function updateButtons() {
  const busy = localBusy || server?.busy,
    running = server?.running || false,
    installed = !!server?.engine;
  $$("[data-power]").forEach(
    (n) =>
      (n.disabled =
        busy ||
        !installed ||
        (n.dataset.power === "start" ? running : !running)),
  );
  $$(
    "[data-command-form] button, [data-command-form] input, [data-command]",
  ).forEach(
    (n) => (n.disabled = busy || !running || server?.phase === "stopping"),
  );
  $$("[data-mutate]").forEach((n) => (n.disabled = busy || running));
  [
    "#newFolder",
    "#newFile",
    "#uploadFiles",
    "#editorSave",
    "#installVersion",
  ].forEach(
    (s) =>
      ($(s).disabled =
        busy ||
        running ||
        (s === "#installVersion" && !$("#versionSelect").value)),
  );
  $$("[data-world-export]").forEach((n) => (n.disabled = busy || !installed));
  $("#createBackup").disabled = busy;
  $("#importBackup").disabled = busy;
  $$(
    "#configForm button[type=submit], #domainForm button[type=submit]",
  ).forEach((n) => (n.disabled = busy || settingsLoading));
  $("#propertiesForm button[type=submit]").disabled =
    busy || running || settingsLoading;
  $$("#configForm [name], #domainForm [name]").forEach(
    (n) => (n.disabled = localBusy || settingsLoading),
  );
  $("#playerActionForm button").disabled = busy || !running;
  $("#addonSearchForm button").disabled =
    !!currentAddonContext.message || localBusy;
  $("#manualAddon").disabled = busy || running;
  if (typeof updateManixButtons === "function")
    updateManixButtons(busy, running);
}
function renderStatus(data) {
  server = data;
  const phases = {
    not_installed: "نصب نشده",
    stopped: "خاموش",
    starting: "در حال شروع",
    running: "روشن",
    stopping: "در حال ذخیره و توقف",
  };
  text("#serverName", data.name);
  text("#serverStatus", phases[data.phase] || data.phase);
  $("#serverStatus").className = "state-tag " + data.phase;
  text(
    "#engineName",
    data.engine
      ? loaders[data.engine.kind]?.name || data.engine.kind
      : "هسته نصب نشده",
  );
  text("#engineVersion", data.engine ? data.engine.version : "Java Edition");
  text(
    "#engineJava",
    data.engine ? "Java " + (config?.java_override || data.engine.java) : "—",
  );
  text("#serverAddress", data.address || "TCP Proxy را در Railway فعال کن");
  $("#setupNotice").hidden = !!data.engine;
  const m = data.metrics;
  text("#statCpu", number(m.cpu_percent, 1));
  text("#statRam", number(m.memory_mb));
  text("#statPlayers", number(m.players_online));
  text("#statPlayersMax", "/ " + number(m.players_max));
  text("#statDisk", m.disk_total_mb ? number(m.disk_used_mb / 1024, 1) : "—");
  $("#cpuProgress").value = Math.min(m.cpu_percent, 100);
  $("#ramProgress").max =
    data.memory_limit_mb || Math.max(data.heap_mb * 1.5, m.memory_mb + 1);
  $("#ramProgress").value = m.memory_mb;
  $("#diskProgress").value = m.disk_total_mb
    ? (m.disk_used_mb / m.disk_total_mb) * 100
    : 0;
  text(
    "#ramCaption",
    `Heap: ${number(data.heap_mb)} MB${data.memory_limit_mb ? " · سهمیه: " + number(data.memory_limit_mb) + " MB" : ""}`,
  );
  text(
    "#diskCaption",
    m.disk_total_mb
      ? `از ${number(m.disk_total_mb / 1024, 1)} GB فایل‌سیستم محل داده‌ها`
      : "در حال اندازه‌گیری فایل‌سیستم…",
  );
  let uptime = "بازی خاموش است";
  if (data.running) {
    const h = Math.floor(data.uptime / 3600),
      mins = Math.floor((data.uptime % 3600) / 60);
    uptime = `زمان روشن: ${number(h)} ساعت و ${number(mins)} دقیقه`;
  }
  text("#uptime", uptime);
  memorySamples.push(m.memory_mb);
  if (memorySamples.length > 30) memorySamples.shift();
  drawChart();
  if (typeof renderManixStatus === "function") renderManixStatus(data);
  renderJob(data);
  updateButtons();
}
async function refreshStatus() {
  if (!authenticated) return;
  const data = await api("/api/status");
  $("#connectionWarning").hidden = true;
  renderStatus(data);
}
function schedulePoll() {
  clearTimeout(pollTimer);
  if (authenticated) pollTimer = setTimeout(poll, 2000);
}
async function poll() {
  if (!authenticated || polling) return;
  polling = true;
  try {
    await refreshStatus();
    const logs = await api("/api/console?after=" + logCursor);
    if (logs.reset) {
      $("#miniConsole").replaceChildren();
      $("#fullConsole").replaceChildren();
    }
    logs.lines.forEach(addLog);
    logCursor = logs.cursor;
    await liveManixTables();
  } catch {
    if (authenticated) $("#connectionWarning").hidden = false;
  } finally {
    polling = false;
    schedulePoll();
  }
}
function addLog(line) {
  ["#miniConsole", "#fullConsole"].forEach((id) => {
    const box = $(id);
    const empty = $(".console-empty", box);
    if (empty) empty.remove();
    const n = el(
      "div",
      "console-line " +
        (["panel", "installer", "command"].includes(line.source)
          ? line.source
          : "server"),
    );
    const stamp = el(
      "span",
      "log-time",
      new Date(line.time * 1000).toLocaleTimeString("en-GB"),
    );
    n.append(stamp, document.createTextNode(line.text));
    box.append(n);
    while (box.childElementCount > (id === "#miniConsole" ? 250 : 1200))
      box.firstElementChild.remove();
    if (id === "#miniConsole" || $("#autoScroll").checked)
      box.scrollTop = box.scrollHeight;
  });
}
$("#clearConsole").addEventListener("click", () => {
  $("#fullConsole").replaceChildren(
    el("div", "console-empty", "نمایش پاک شد؛ لاگ روی دیسک محفوظ است."),
  );
});
function drawChart() {
  const canvas = $("#memoryChart");
  if (!canvas || currentPage !== "overview") return;
  const width = canvas.clientWidth || 300,
    height = 115,
    dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  const max = Math.max(server?.heap_mb || 1024, ...memorySamples, 1);
  text("#chartMax", number(max) + " MB");
  ctx.strokeStyle = getComputedStyle(document.documentElement)
    .getPropertyValue("--border-light")
    .trim();
  ctx.setLineDash([3, 4]);
  ctx.lineWidth = 1;
  [25, 55, 85].forEach((y) => {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(width, y);
    ctx.stroke();
  });
  ctx.setLineDash([]);
  const points = memorySamples.map((v, i) => [
    (i * width) / Math.max(memorySamples.length - 1, 1),
    100 - (v / max) * 85,
  ]);
  if (points.length < 2) return;
  ctx.beginPath();
  ctx.moveTo(points[0][0], 110);
  points.forEach((p) => ctx.lineTo(...p));
  ctx.lineTo(points.at(-1)[0], 110);
  ctx.closePath();
  const gradient = ctx.createLinearGradient(0, 15, 0, 110);
  gradient.addColorStop(
    0,
    document.documentElement.dataset.theme === "light"
      ? "#36754127"
      : "#b0ef8d27",
  );
  gradient.addColorStop(1, "#b0ef8d00");
  ctx.fillStyle = gradient;
  ctx.fill();
  ctx.beginPath();
  points.forEach((p, i) => (i ? ctx.lineTo(...p) : ctx.moveTo(...p)));
  ctx.strokeStyle = getComputedStyle(document.documentElement)
    .getPropertyValue("--green")
    .trim();
  ctx.lineWidth = 1.5;
  ctx.stroke();
}
window.addEventListener("resize", drawChart);
function renderJob(data) {
  const job =
    data.job ||
    data.jobs.find(
      (j) => j.finished > startedAt - 3600 && !dismissedJobs.has(j.id),
    );
  if (!job) {
    $("#jobBanner").hidden = true;
    return;
  }
  $("#jobBanner").hidden = false;
  $("#jobBanner").classList.toggle("error", job.state === "failed");
  text("#jobTitle", job.title);
  text("#jobMessage", job.message);
  const working = ["queued", "running"].includes(job.state);
  $("#jobSpinner").hidden = !working;
  $("#jobCheck").hidden = working;
  $("#jobDismiss").hidden = working;
  $("#jobDownload").hidden = !job.download || job.state !== "done";
  if (job.download) $("#jobDownload").href = job.download;
  $("#jobBanner").dataset.job = job.id;
  if (!working && !seenJobs.has(job.id)) {
    seenJobs.add(job.id);
    if (job.finished > startedAt) {
      toast(job.message, job.state === "failed");
      if (
        [
          "files",
          "addons",
          "backups",
          "players",
          "worlds",
          "packs",
          "schedules",
          "versions",
        ].includes(currentPage)
      )
        loadPage(currentPage).catch((e) => toast(e.message, true));
    }
  }
}
$("#jobDismiss").addEventListener("click", () => {
  dismissedJobs.add($("#jobBanner").dataset.job);
  $("#jobBanner").hidden = true;
});

let promptResolve = null;
function ask({
  title,
  description = "",
  fields = [],
  confirm = "تأیید",
  danger = false,
  link = null,
}) {
  if ($("#promptDialog").open) return Promise.resolve(null);
  text("#promptTitle", title);
  text("#promptDescription", description);
  $("#promptFields").replaceChildren();
  if (link) {
    const a = el("a", "text-link", link.label);
    a.href = link.url;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    $("#promptFields").append(a);
  }
  fields.forEach((f) => {
    const label = el("label", "", f.label);
    const input = el("input");
    input.name = f.name;
    input.value = f.value || "";
    input.required = !!f.required;
    input.maxLength = f.max || 2048;
    input.dir = f.dir || "auto";
    input.type = f.type || "text";
    input.autocomplete = f.autocomplete || "off";
    if (f.placeholder) input.placeholder = f.placeholder;
    label.append(input);
    $("#promptFields").append(label);
  });
  text("#promptSubmit", confirm);
  $("#promptSubmit").className =
    "btn " + (danger ? "btn-danger" : "btn-primary");
  $("#promptDialog").showModal();
  return new Promise((resolve) => {
    promptResolve = resolve;
  });
}
function endPrompt(value) {
  const resolve = promptResolve;
  promptResolve = null;
  $("#promptDialog").close();
  $("#promptFields").replaceChildren();
  if (resolve) resolve(value);
}
$("#promptForm").addEventListener("submit", (e) => {
  e.preventDefault();
  endPrompt(Object.fromEntries(new FormData(e.currentTarget)));
});
$("#promptCancel").addEventListener("click", () => endPrompt(null));
$("#promptClose").addEventListener("click", () => endPrompt(null));
$("#promptDialog").addEventListener("cancel", (e) => {
  e.preventDefault();
  endPrompt(null);
});
async function ensureEula() {
  if (!config) config = (await api("/api/settings")).config;
  if (config.eula_accepted) return true;
  const ok = await ask({
    title: "پذیرش Minecraft EULA",
    description:
      "برای اجرای سرور باید توافق‌نامهٔ رسمی Minecraft را خودت بخوانی و بپذیری. این تأیید از طرف مالک سرور ذخیره می‌شود.",
    confirm: "خوانده‌ام و می‌پذیرم",
    link: {
      label: "باز کردن توافق‌نامهٔ رسمی ↗",
      url: "https://aka.ms/MinecraftEULA",
    },
  });
  if (!ok) return false;
  await api("/api/settings", {
    method: "PATCH",
    body: { eula_accepted: true },
  });
  config.eula_accepted = true;
  return true;
}
$$("[data-power]").forEach((n) =>
  n.addEventListener("click", () =>
    action(async () => {
      if (n.dataset.power === "start" && !(await ensureEula())) return;
      if (
        n.dataset.power === "kill" &&
        !(await ask({
          title: "Kill اجباری بازی؟",
          description:
            "این کار فرایند Java را فوراً با SIGKILL می‌بندد. آخرین تغییرات ذخیره‌نشدهٔ دنیا ممکن است از دست برود؛ ابتدا توقف امن را امتحان کن.",
          confirm: "Kill؛ خطر را می‌پذیرم",
          danger: true,
        }))
      )
        return;
      if (
        n.dataset.power === "stop" &&
        !(await ask({
          title: "سرور خاموش شود؟",
          description:
            "ابتدا دنیا ذخیره می‌شود و بعد فقط بازی متوقف می‌شود. خود پنل Railway روشن می‌ماند.",
          confirm: "ذخیره و خاموش کردن",
        }))
      )
        return;
      await api("/api/power", {
        method: "POST",
        body: { action: n.dataset.power },
      });
    }),
  ),
);
$$("[data-command-form]").forEach((form) =>
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("[name=command]", form);
    action(async () => {
      await api("/api/console", {
        method: "POST",
        body: { command: input.value },
      });
      input.value = "";
    });
  }),
);
$$("[data-command]").forEach((n) =>
  n.addEventListener("click", () =>
    action(async () => {
      await api("/api/console", {
        method: "POST",
        body: { command: n.dataset.command },
      });
    }),
  ),
);
$("#copyAddress").addEventListener(
  "click",
  safe(async () => {
    if (!server?.address) {
      await goPage("settings");
      return;
    }
    try {
      await navigator.clipboard.writeText(server.address);
      toast("آدرس اتصال کپی شد.");
    } catch {
      await ask({
        title: "آدرس اتصال سرور",
        fields: [
          {
            name: "address",
            label: "این آدرس را کپی کن",
            value: server.address,
            dir: "ltr",
          },
        ],
        confirm: "باشه",
      });
    }
  }),
);
$$("[data-world-export]").forEach((n) =>
  n.addEventListener("click", () =>
    action(async () => {
      if (
        server?.running &&
        !(await ask({
          title: "سیو دنیا را دانلود کنیم؟",
          description:
            "برای جلوگیری از خروجی ناقص، بازی موقتاً متوقف و پس از آماده‌سازی ZIP دوباره اجرا می‌شود. بازیکن‌ها قطع می‌شوند.",
          confirm: "ساخت خروجی سالم",
        }))
      )
        return;
      await api("/api/world/export", { method: "POST" });
    }),
  ),
);

function smallButton(icon, title, fn, mutate = false, danger = false) {
  const b = el("button", "icon-btn" + (danger ? " danger" : ""));
  b.title = title;
  b.setAttribute("aria-label", title);
  b.append(ico(icon));
  if (mutate) b.dataset.mutate = "true";
  b.addEventListener("click", safe(fn));
  return b;
}
function emptyTable(body, colspan, message) {
  const tr = el("tr"),
    td = el("td", "empty-table", message);
  td.colSpan = colspan;
  tr.append(td);
  body.append(tr);
}
async function loadFiles() {
  const request = ++fileRequest;
  const data = await api(manixFileUrl());
  if (request !== fileRequest) return;
  currentPath = data.path;
  data.files = paginateManixFiles(data.files);
  text(
    "#fileSearchLimit",
    data.limited ? "نتایج محدود شده‌اند؛ مسیر یا عبارت را دقیق‌تر کن." : "",
  );
  const crumbs = $("#fileBreadcrumb");
  crumbs.replaceChildren();
  const root = el("button", "", "/ server");
  root.addEventListener(
    "click",
    safe(async () => {
      currentPath = "";
      await loadFiles();
    }),
  );
  crumbs.append(root);
  let part = "";
  currentPath
    .split("/")
    .filter(Boolean)
    .forEach((name) => {
      part += (part ? "/" : "") + name;
      const path = part,
        b = el("button", "", name);
      b.addEventListener(
        "click",
        safe(async () => {
          currentPath = path;
          await loadFiles();
        }),
      );
      crumbs.append(el("span", "", "/"), b);
    });
  const rows = $("#fileRows");
  rows.replaceChildren();
  if (!data.files.length)
    emptyTable(rows, 5, "این پوشه خالی است؛ فایل آپلود کن یا پوشه بساز.");
  data.files.forEach((file) => {
    const tr = el("tr"),
      td = el("td"),
      name = el("button", "file-name" + (file.dir ? "" : " file"));
    name.append(ico(file.dir ? "folder" : "file"), el("span", "", file.name));
    name.dir = "auto";
    name.disabled = file.symlink;
    name.addEventListener(
      "click",
      safe(async () => {
        if (file.dir) {
          currentPath = file.path;
          await loadFiles();
        } else await openEditor(file.path);
      }),
    );
    td.append(name);
    tr.append(
      td,
      el("td", "", file.dir ? "—" : bytes(file.size)),
      el("td", "", when(file.modified)),
    );
    const actions = el("td"),
      box = el("div", "row-actions");
    if (!file.symlink) {
      if (file.dir)
        box.append(
          smallButton(
            "archive",
            "دانلود پوشه به صورت ZIP",
            () =>
              action(async () => {
                await api("/api/files/archive", {
                  method: "POST",
                  body: { path: file.path },
                });
              }),
            true,
          ),
        );
      else {
        const a = el("a", "icon-btn");
        a.href = "/api/files/download?path=" + encodeURIComponent(file.path);
        a.title = "دانلود فایل";
        a.setAttribute("aria-label", "دانلود " + file.name);
        a.append(ico("download"));
        box.append(a);
        if (file.name.toLowerCase().endsWith(".zip"))
          box.append(
            smallButton(
              "box",
              "باز کردن ZIP",
              () => extractFile(file.path),
              true,
            ),
          );
        else if (!file.name.toLowerCase().endsWith(".jar"))
          box.append(
            smallButton("edit", "ویرایش فایل", () => openEditor(file.path)),
          );
      }
      box.append(
        smallButton("edit", "تغییر نام", () => renameFile(file.path), true),
        smallButton(
          "trash",
          "حذف",
          () => deleteFile(file.path, file.dir),
          true,
          true,
        ),
      );
    } else box.append(el("span", "small-note", "symlink — دسترسی مسدود"));
    actions.append(box);
    tr.append(actions);
    enhanceFileRow(tr, file);
    rows.append(tr);
  });
  updateFileSelection();
  updateButtons();
}
async function openEditor(path, isNew = false) {
  let content = "";
  if (!isNew)
    content = (await api("/api/files/text?path=" + encodeURIComponent(path)))
      .content;
  editorPath = path;
  editorOriginal = content;
  text("#editorName", path);
  $("#editorText").value = content;
  $("#editorDialog").showModal();
  updateButtons();
}
async function saveEditor() {
  await api("/api/files/text", {
    method: "PUT",
    body: { path: editorPath, content: $("#editorText").value },
  });
  editorOriginal = $("#editorText").value;
  toast("فایل ذخیره شد.");
  await loadFiles();
}
$("#editorSave").addEventListener("click", () => action(saveEditor));
async function closeEditor() {
  if (
    $("#editorText").value !== editorOriginal &&
    !(await ask({
      title: "تغییرات ذخیره نشده‌اند",
      description: "بدون ذخیره از ویرایشگر خارج شوی؟",
      confirm: "خروج بدون ذخیره",
      danger: true,
    }))
  )
    return;
  $("#editorDialog").close();
}
$("#editorClose").addEventListener("click", safe(closeEditor));
$("#editorDialog").addEventListener("cancel", (e) => {
  e.preventDefault();
  safe(closeEditor)();
});
$("#editorText").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    action(saveEditor);
  }
});
function joinFile(name) {
  return (currentPath ? currentPath + "/" : "") + name;
}
$("#newFolder").addEventListener("click", () =>
  action(async () => {
    const data = await ask({
      title: "پوشه جدید",
      fields: [{ name: "name", label: "نام پوشه", required: true, dir: "ltr" }],
      confirm: "ساخت پوشه",
    });
    if (!data) return;
    await api("/api/files/mkdir", {
      method: "POST",
      body: { path: joinFile(data.name) },
    });
    await loadFiles();
  }),
);
$("#newFile").addEventListener(
  "click",
  safe(async () => {
    const data = await ask({
      title: "فایل متنی جدید",
      fields: [
        {
          name: "name",
          label: "نام فایل",
          required: true,
          dir: "ltr",
          placeholder: "config.yml",
        },
      ],
      confirm: "باز کردن ویرایشگر",
    });
    if (data) await openEditor(joinFile(data.name), true);
  }),
);
async function renameFile(path) {
  await action(async () => {
    const data = await ask({
      title: "تغییر نام یا مسیر",
      fields: [
        {
          name: "path",
          label: "مسیر جدید نسبت به ریشهٔ server",
          value: path,
          required: true,
          dir: "ltr",
        },
      ],
      confirm: "تغییر نام",
    });
    if (!data) return;
    await api("/api/files/rename", {
      method: "POST",
      body: { source: path, target: data.path },
    });
    await loadFiles();
  });
}
async function deleteFile(path, isDir = false) {
  await action(async () => {
    if (
      !(await ask({
        title: "حذف " + (isDir ? "پوشه" : "فایل"),
        description: `${path}\nحذف ${isDir ? "پوشه و همهٔ محتویاتش" : "فایل"} برگشت‌پذیر نیست، مگر بکاپ داشته باشی.`,
        confirm: "حذف",
        danger: true,
      }))
    )
      return;
    await api("/api/files", { method: "DELETE", body: { path } });
    toast("حذف شد.");
    await loadFiles();
  });
}
async function extractFile(path) {
  await action(async () => {
    const data = await ask({
      title: "باز کردن ZIP",
      description:
        "فایل‌های هم‌نام جایگزین می‌شوند؛ ابتدا بکاپ گرفته می‌شود. پوشهٔ مقصد باید از قبل موجود باشد.",
      fields: [
        {
          name: "target",
          label: "مسیر مقصد (خالی = ریشهٔ server)",
          value: currentPath,
          dir: "ltr",
        },
      ],
      confirm: "بکاپ و Extract",
    });
    if (data)
      await api("/api/files/extract", {
        method: "POST",
        body: { path, target: data.target },
      });
  });
}
$("#refreshFiles").addEventListener("click", safe(loadFiles));
$("#uploadFiles").addEventListener("click", () =>
  $("#fileUploadInput").click(),
);
async function uploadFiles(files) {
  await action(async () => {
    if (server?.running) throw new Error("اول سرور بازی را خاموش کن.");
    for (const file of files) {
      const data = new FormData();
      data.append("file", file);
      const path = "/api/files/upload?path=" + encodeURIComponent(currentPath);
      try {
        await api(path, { method: "POST", body: data });
      } catch (err) {
        if (err.status !== 409) throw err;
        if (
          !(await ask({
            title: "جایگزین کردن فایل؟",
            description: `${file.name} از قبل وجود دارد. جایگزینی را تأیید می‌کنی؟`,
            confirm: "جایگزین کن",
            danger: true,
          }))
        )
          continue;
        await api(path + "&overwrite=true", { method: "POST", body: data });
      }
      toast("آپلود شد: " + file.name);
    }
    await loadFiles();
  });
}
$("#fileUploadInput").addEventListener(
  "change",
  safe(async (e) => {
    await uploadFiles([...e.target.files]);
    e.target.value = "";
  }),
);
$("#fileDropZone").addEventListener("dragover", (e) => {
  e.preventDefault();
  e.currentTarget.classList.add("file-drop-active");
});
$("#fileDropZone").addEventListener("dragleave", (e) =>
  e.currentTarget.classList.remove("file-drop-active"),
);
$("#fileDropZone").addEventListener(
  "drop",
  safe(async (e) => {
    e.preventDefault();
    e.currentTarget.classList.remove("file-drop-active");
    await uploadFiles([...e.dataTransfer.files]);
  }),
);

function renderLoaders() {
  const box = $("#loaderGrid");
  box.replaceChildren();
  Object.entries(loaders).forEach(([kind, info]) => {
    const button = el(
      "button",
      "loader-card" + (kind === selectedKind ? " active" : ""),
    );
    button.dataset.kind = kind;
    button.append(
      ico(info.icon),
      el("strong", "", info.name),
      el("span", "", info.label),
    );
    button.addEventListener(
      "click",
      safe(() => loadVersions(kind)),
    );
    box.append(button);
  });
}
function renderVersionOptions() {
  const select = $("#versionSelect"),
    previous = select.value,
    filter = $("#versionFilter").value.trim();
  select.replaceChildren();
  const choices = versionList.filter((v) =>
    v.id.toLowerCase().includes(filter.toLowerCase()),
  );
  choices.forEach((v) => {
    const option = el("option", "", v.id);
    option.value = v.id;
    select.append(option);
  });
  if (choices.some((v) => v.id === previous)) select.value = previous;
  else if (
    server?.engine?.kind === selectedKind &&
    choices.some((v) => v.id === server.engine.version)
  )
    select.value = server.engine.version;
  else if (choices.some((v) => v.id === "1.21.1")) select.value = "1.21.1";
  if (!choices.length) {
    const option = el("option", "", "نسخه‌ای پیدا نشد");
    option.value = "";
    select.append(option);
  }
  updateButtons();
}
async function loadVersions(kind) {
  selectedKind = kind;
  renderLoaders();
  text("#selectedKind", loaders[kind].name);
  text("#loaderHelp", loaders[kind].help);
  $("#versionError").hidden = true;
  const request = ++versionRequest;
  const select = $("#versionSelect");
  select.replaceChildren(el("option", "", "در حال دریافت نسخه‌ها…"));
  select.firstElementChild.value = "";
  updateButtons();
  try {
    const data = await api("/api/versions?kind=" + kind);
    if (request !== versionRequest) return;
    versionList = data.versions;
    renderVersionOptions();
  } catch (e) {
    if (request === versionRequest) {
      versionList = [];
      renderVersionOptions();
      text("#versionError", e.message);
      $("#versionError").hidden = false;
    }
  }
  await loadRuntimeEngines();
}
$("#versionFilter").addEventListener("input", renderVersionOptions);
$("#versionSelect").addEventListener("change", updateButtons);
$("#versionForm").addEventListener("submit", (e) => {
  e.preventDefault();
  action(async () => {
    const version = $("#versionSelect").value;
    if (!version) throw new Error("یک نسخه انتخاب کن.");
    if (
      !(await ask({
        title: `نصب ${loaders[selectedKind].name} ${version}`,
        description:
          "فایل‌های دنیا حفظ می‌شوند و قبل از تغییر بکاپ ساخته می‌شود. JARهای احتمالاً ناسازگار به disabled-addons منتقل می‌شوند. دانلود به اینترنت و فضای کافی نیاز دارد.",
        confirm: "شروع نصب",
      }))
    )
      return;
    await api("/api/versions/install", {
      method: "POST",
      body: {
        kind: selectedKind,
        version,
        allow_downgrade: $("#allowDowngrade").checked,
      },
    });
  });
});

async function loadAddons() {
  const data = await api("/api/addons");
  currentAddonContext = data.context;
  const span = $("#addonContext span");
  span.textContent =
    data.context.message ||
    `${data.context.kind === "mod" ? "مود" : "پلاگین"} · Minecraft ${data.context.version} · ${data.context.loaders.join(" / ")} · برای نصب یا تغییر، بازی را خاموش کن.`;
  const body = $("#installedAddons");
  body.replaceChildren();
  if (!data.addons.length)
    emptyTable(body, 4, "هنوز مود یا پلاگینی نصب نشده است.");
  data.addons.forEach((r) => {
    const tr = el("tr"),
      name = el("td"),
      title = el("div", "", r.title || r.file);
    title.dir = "auto";
    name.append(title);
    if (r.title) {
      const file = el("div", "small-note", r.folder + "/" + r.file);
      file.dir = "ltr";
      name.append(file);
    }
    const status = el("td");
    status.append(
      el(
        "span",
        r.enabled ? "tag-enabled" : "tag-disabled",
        r.enabled ? "فعال" : "غیرفعال",
      ),
    );
    const actions = el("td"),
      box = el("div", "row-actions");
    box.append(
      smallButton(
        "power",
        r.enabled ? "غیرفعال کردن" : "فعال کردن",
        () =>
          action(async () => {
            await api("/api/addons/toggle", {
              method: "POST",
              body: { folder: r.folder, file: r.file, enabled: !r.enabled },
            });
            await loadAddons();
          }),
        true,
      ),
    );
    if (r.project_id && r.enabled)
      box.append(
        smallButton(
          "refresh",
          "نصب آخرین نسخهٔ سازگار",
          () =>
            action(async () => {
              if (
                !(await ask({
                  title: "به‌روزرسانی " + (r.title || r.file),
                  description:
                    "آخرین Release سازگار و وابستگی‌ها از Modrinth دریافت می‌شود؛ نسخهٔ قبلی بعد از موفقیت دانلود جایگزین می‌شود. بکاپ مهمت را نگه دار.",
                  confirm: "نصب آخرین نسخه",
                }))
              )
                return;
              await api("/api/addons/install", {
                method: "POST",
                body: { project_id: r.project_id },
              });
            }),
          true,
        ),
      );
    box.append(
      smallButton(
        "trash",
        "حذف JAR",
        () =>
          action(async () => {
            if (
              !(await ask({
                title: "حذف افزونه",
                description:
                  "حذف وابستگی یک مود ممکن است مودهای دیگر را از کار بیندازد. فقط فایل JAR پاک می‌شود، نه تنظیمات افزونه.",
                confirm: "حذف JAR",
                danger: true,
              }))
            )
              return;
            await api("/api/files", {
              method: "DELETE",
              body: { path: r.folder + "/" + r.file },
            });
            await loadAddons();
          }),
        true,
        true,
      ),
    );
    actions.append(box);
    tr.append(name, el("td", "", r.version || "دستی"), status, actions);
    body.append(tr);
  });
  updateButtons();
}
async function searchAddons() {
  const box = $("#addonSearchResults");
  box.replaceChildren(el("div", "empty-state", "در حال جستجو…"));
  try {
    const data = await api(
      "/api/addons/search?q=" +
        encodeURIComponent($("#addonQuery").value) +
        "&offset=" +
        searchOffset,
    );
    searchTotal = data.total;
    box.replaceChildren();
    if (!data.hits.length)
      box.append(
        el(
          "div",
          "empty-state",
          "نسخهٔ سازگاری پیدا نشد. نام دیگری را امتحان کن یا دستی JAR نصب کن.",
        ),
      );
    data.hits.forEach((hit) => {
      const card = el("article", "addon-result"),
        logo = el(
          "div",
          "addon-logo",
          (hit.title || "M").slice(0, 1).toUpperCase(),
        ),
        title = el("h4", "", hit.title),
        desc = el("p", "", hit.description),
        info = el(
          "small",
          "",
          `${hit.author || ""} · ${Number(hit.downloads).toLocaleString("en-US")} downloads`,
        ),
        button = el("button", "btn btn-small", "نصب و وابستگی‌ها");
      button.dataset.mutate = "true";
      button.prepend(ico("download"));
      button.addEventListener("click", () =>
        action(async () => {
          if (
            !(await ask({
              title: "نصب " + hit.title,
              description:
                "نسخهٔ سازگار با سرور و وابستگی‌های ضروریِ قابل‌تشخیص دانلود می‌شوند. مود یا پلاگین کد اجرایی است؛ فقط اگر به سازنده اعتماد داری نصب کن.",
              confirm: "نصب از Modrinth",
            }))
          )
            return;
          await api("/api/addons/install", {
            method: "POST",
            body: { project_id: hit.project_id },
          });
        }),
      );
      card.append(logo, title, desc, info, button);
      box.append(card);
    });
    $("#addonPagination").hidden = searchTotal <= 12;
    $("#addonsPrev").disabled = searchOffset === 0;
    $("#addonsNext").disabled = searchOffset + 12 >= searchTotal;
    text(
      "#addonsResultCount",
      `${number(searchOffset + 1)} تا ${number(Math.min(searchOffset + 12, searchTotal))} از ${number(searchTotal)}`,
    );
    updateButtons();
  } catch (e) {
    box.replaceChildren(el("div", "empty-state", e.message));
    throw e;
  }
}
$("#addonSearchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  searchOffset = 0;
  safe(searchAddons)();
});
$("#addonsPrev").addEventListener(
  "click",
  safe(async () => {
    searchOffset = Math.max(0, searchOffset - 12);
    await searchAddons();
  }),
);
$("#addonsNext").addEventListener(
  "click",
  safe(async () => {
    searchOffset += 12;
    await searchAddons();
  }),
);
$("#refreshAddons").addEventListener("click", safe(loadAddons));
$("#manualAddon").addEventListener("click", () =>
  action(async () => {
    const data = await api("/api/addons");
    if (!data.context.folder) throw new Error(data.context.message);
    currentPath = data.context.folder;
    try {
      await api("/api/files?path=" + currentPath);
    } catch (e) {
      if (e.status !== 404) throw e;
      await api("/api/files/mkdir", {
        method: "POST",
        body: { path: currentPath },
      });
    }
    await goPage("files");
    toast("فایل JAR را با دکمهٔ آپلود در این پوشه قرار بده.");
  }),
);

async function loadPlayers() {
  playerData = await api("/api/players");
  renderManixPlayers();
}
$("#refreshPlayers").addEventListener("click", safe(loadPlayers));
$("#playerActionForm").addEventListener("submit", (e) => {
  e.preventDefault();
  action(sendPlayerAction);
});

async function loadBackups() {
  const data = await api("/api/backups"),
    body = $("#backupRows");
  body.replaceChildren();
  if (!data.backups.length)
    emptyTable(body, 4, "هنوز بکاپی ساخته نشده. اولین بکاپ را بساز.");
  data.backups.forEach((r) => {
    const tr = el("tr"),
      name = el("td"),
      title = el("div", "", r.name);
    title.dir = "ltr";
    name.append(title);
    if (r.automatic) name.append(el("span", "mini-tag", "خودکار"));
    const actions = el("td"),
      box = el("div", "row-actions"),
      link = el("a", "icon-btn");
    link.title = "دانلود بکاپ";
    link.setAttribute("aria-label", "دانلود بکاپ");
    link.href = "/api/backups/download?name=" + encodeURIComponent(r.name);
    link.append(ico("download"));
    box.append(link);
    box.append(
      smallButton(
        "refresh",
        "بازیابی بکاپ",
        () =>
          action(async () => {
            if (
              !(await ask({
                title: "بازیابی بکاپ",
                description:
                  "فایل‌های بازی با این بکاپ جایگزین می‌شوند. پیش از بازیابی یک بکاپ ایمنی ساخته می‌شود. بازی باید خاموش باشد؛ موتور قدیمی در صورت وجود روی Volume برمی‌گردد.",
                confirm: "بازیابی",
                danger: true,
              }))
            )
              return;
            await api("/api/backups/restore", {
              method: "POST",
              body: { name: r.name },
            });
          }),
        true,
      ),
    );
    box.append(
      smallButton(
        "trash",
        "حذف بکاپ",
        () =>
          action(async () => {
            if (
              !(await ask({
                title: "حذف بکاپ",
                description: r.name,
                confirm: "حذف",
                danger: true,
              }))
            )
              return;
            await api("/api/backups", {
              method: "DELETE",
              body: { name: r.name },
            });
            await loadBackups();
          }),
        false,
        true,
      ),
    );
    actions.append(box);
    tr.append(
      name,
      el("td", "", when(r.created)),
      el("td", "", bytes(r.size)),
      actions,
    );
    body.append(tr);
  });
  updateButtons();
}
$("#refreshBackups").addEventListener("click", safe(loadBackups));
$("#createBackup").addEventListener("click", () =>
  action(async () => {
    if (
      server?.running &&
      !(await ask({
        title: "ساخت بکاپ کامل",
        description:
          "بازی برای گرفتن بکاپ سالم موقتاً متوقف و پس از ساخت دوباره روشن می‌شود. بازیکن‌ها قطع می‌شوند.",
        confirm: "ساخت بکاپ",
      }))
    )
      return;
    await api("/api/backups", { method: "POST" });
  }),
);

$("#importBackup").addEventListener("click", () =>
  $("#backupUploadInput").click(),
);
$("#backupUploadInput").addEventListener(
  "change",
  safe(async (e) => {
    const input = e.currentTarget;
    const file = input.files[0];
    if (!file) return;
    await action(async () => {
      const form = new FormData();
      form.append("file", file);
      await api("/api/backups/import", { method: "POST", body: form });
      toast(
        "بکاپ وارد شد. برای بازیابی روی Volume جدید، اول هسته و نسخهٔ مشابه نصب کن.",
      );
      await loadBackups();
    });
    input.value = "";
  }),
);

const propertySpecs = [
  ["motd", "پیام سرور (MOTD)", "text"],
  ["level-name", "نام پوشهٔ دنیا", "text"],
  ["max-players", "حداکثر بازیکن", "number", 1, 500],
  [
    "gamemode",
    "حالت بازی",
    "select",
    ["survival", "creative", "adventure", "spectator"],
  ],
  ["difficulty", "درجه سختی", "select", ["peaceful", "easy", "normal", "hard"]],
  ["view-distance", "فاصله دید", "number", 2, 32],
  ["simulation-distance", "فاصله شبیه‌سازی", "number", 2, 32],
  ["spawn-protection", "محافظت Spawn", "number", 0, 128],
  ["online-mode", "تأیید حساب رسمی", "boolean"],
  ["white-list", "وایت‌لیست", "boolean"],
  ["enforce-whitelist", "اعمال سخت‌گیرانه وایت‌لیست", "boolean"],
  ["pvp", "نبرد بازیکن‌ها (PVP)", "boolean"],
  ["allow-flight", "اجازه پرواز", "boolean"],
  ["hardcore", "هاردکور", "boolean"],
  ["allow-nether", "فعال بودن Nether", "boolean"],
];
function populateForm(form, values) {
  $$("[name]", form).forEach((input) => {
    if (values[input.name] !== undefined) {
      if (input.type === "checkbox") input.checked = !!values[input.name];
      else
        input.value = Array.isArray(values[input.name])
          ? values[input.name].join(" ")
          : values[input.name];
    }
  });
}
async function loadSettings() {
  settingsLoading = true;
  updateButtons();
  try {
    const [data, properties] = await Promise.all([
      api("/api/settings"),
      api("/api/properties"),
    ]);
    config = data.config;
    populateForm($("#configForm"), config);
    populateForm($("#domainForm"), config);
    text("#uploadLimit", "سقف آپلود " + number(data.upload_mb) + " MB");
    text(
      "#memoryHelp",
      server?.memory_limit_mb
        ? `سهمیه سرویس: ${number(server.memory_limit_mb)} MB · heap پیشنهادی تا ${number(server.recommended_heap_mb)} MB. تغییر رم یا Java نیاز به بازیِ خاموش دارد.`
        : "Heap همهٔ حافظهٔ JVM نیست؛ رم پنل و حافظهٔ native بازی را هم در سهمیه Railway حساب کن.",
    );
    const box = $("#propertiesFields");
    box.replaceChildren();
    propertySpecs.forEach(([key, title, type, min, max]) => {
      const label = el(
          "label",
          type === "boolean" ? "check-block" : "",
          type === "boolean" ? "" : title,
        ),
        input = el(type === "select" ? "select" : "input");
      input.name = key;
      if (type === "select") {
        min.forEach((v) => {
          const option = el("option", "", v);
          option.value = v;
          input.append(option);
        });
        input.value = properties.values[key];
      } else if (type === "boolean") {
        input.type = "checkbox";
        input.checked = properties.values[key] === "true";
      } else {
        input.type = type;
        input.value = properties.values[key];
        if (type === "number") {
          input.min = min;
          input.max = max;
          input.required = true;
        } else input.maxLength = 512;
      }
      if (type !== "boolean") input.dir = "auto";
      label.append(input);
      if (type === "boolean") label.append(el("span", "", title));
      box.append(label);
    });
    renderDNS();
    await loadAudit();
    await loadManixStartup();
  } finally {
    settingsLoading = false;
    updateButtons();
  }
}
function formValues(form, numeric, booleans = []) {
  const result = {};
  $$("[name]", form).forEach((input) => {
    result[input.name] = booleans.includes(input.name)
      ? input.checked
      : numeric.includes(input.name)
        ? Number(input.value)
        : input.value;
  });
  return result;
}
$("#configForm").addEventListener("submit", (e) => {
  e.preventDefault();
  action(async () => {
    const values = formValues(
      e.currentTarget,
      [
        "memory_mb",
        "java_override",
        "backup_hours",
        "restart_hours",
        "backup_keep",
        "game_port",
      ],
      ["autostart", "auto_restart", "eula_accepted"],
    );
    values.jvm_args = values.jvm_args.trim().split(/\s+/).filter(Boolean);
    const diff = Object.fromEntries(
      Object.entries(values).filter(
        ([k, v]) => JSON.stringify(config?.[k]) !== JSON.stringify(v),
      ),
    );
    if (Object.keys(diff).length)
      await api("/api/settings", { method: "PATCH", body: diff });
    toast("تنظیمات ذخیره شد.");
    config = (await api("/api/settings")).config;
    populateForm($("#configForm"), config);
    renderDNS();
    await loadAudit();
    await loadManixStartup();
  });
});
$("#domainForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    await api("/api/settings", {
      method: "PATCH",
      body: formValues(form, ["proxy_port"]),
    });
    toast("آدرس‌ها ذخیره شد. حالا رکوردها را در DNS و Railway تنظیم کن.");
    config = (await api("/api/settings")).config;
    populateForm($("#domainForm"), config);
    renderDNS();
    await loadAudit();
  });
});
$("#propertiesForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    const values = {};
    $$("[name]", form).forEach((n) => {
      values[n.name] = n.type === "checkbox" ? String(n.checked) : n.value;
    });
    await api("/api/properties", { method: "PATCH", body: { values } });
    toast("تنظیمات بازی ذخیره شد.");
  });
});
function renderDNS() {
  const box = $("#dnsRecords");
  box.replaceChildren();
  if (!config) return;
  if (config.game_domain && config.proxy_host && config.proxy_port) {
    const c = el("div", "dns-record"),
      s = el("div", "dns-record");
    c.append(
      el("strong", "", "CNAME · DNS only"),
      el("div", "", `${config.game_domain} → ${config.proxy_host}`),
    );
    s.append(
      el("strong", "", "SRV · Minecraft Java"),
      el("div", "", `_minecraft._tcp.${config.game_domain}`),
      el("div", "", `0 5 ${config.proxy_port} ${config.proxy_host}.`),
    );
    box.append(c, s);
  } else
    box.append(
      el(
        "p",
        "small-note",
        "برای ساخت راهنمای DNS، دامنهٔ بازی، آدرس Proxy و پورت عمومی را کامل کن.",
      ),
    );
  if (config.panel_domain)
    box.append(
      el(
        "p",
        "small-note",
        `برای ${config.panel_domain} در Railway → Networking → Custom Domain دامنه را اضافه و رکوردهای نمایش‌داده‌شدهٔ Railway را ثبت کن.`,
      ),
    );
}
async function loadAudit() {
  const data = await api("/api/audit"),
    box = $("#auditRows");
  box.replaceChildren();
  data.events.forEach((row) => {
    const n = el("div", "audit-row"),
      stamp = el("time", "", when(row.time)),
      content = el("div");
    content.append(el("strong", "", row.action), el("p", "", row.detail));
    n.append(stamp, content);
    box.append(n);
  });
}
$("#refreshAudit").addEventListener("click", safe(loadAudit));

icons();
renderLoaders();
text(
  "#topDate",
  new Date().toLocaleDateString("fa-IR", { day: "numeric", month: "long" }),
);
(async () => {
  try {
    const data = await api("/api/session");
    await enter(data);
  } catch {
    showLogin();
  }
})();
