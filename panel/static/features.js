"use strict";
// مانیکس / Manix: extensions reuse the original API, job gate and UI helpers.
let fileRequest = 0,
  filePage = 0,
  fileStateKey = "",
  fileRowsVisible = [],
  fileTotal = 0;
let playerData = null,
  previousPhase = null,
  tablePolls = 0;
const selectedFiles = new Set(),
  cpuSamples = [],
  diskSamples = [],
  warningSeen = new Set(),
  warningLastAt = new Map(),
  startedBackupJobs = new Set();
const taskNames = {
  start: "روشن کردن",
  stop: "توقف امن",
  restart: "ری‌استارت",
  backup: "بکاپ",
  command: "دستور",
};
const scopeLabels = {
  status: "وضعیت",
  "console.read": "خواندن کنسول",
  "console.write": "دستور کنسول",
  power: "روشن/خاموش/Kill",
  "files.read": "خواندن فایل و دنیا",
  "files.write": "تغییر فایل و دنیا",
  "backups.read": "دانلود بکاپ",
  "backups.write": "ساخت/حذف/Restore بکاپ",
  "players.read": "فهرست بازیکن",
  "players.write": "مدیریت بازیکن",
  "settings.read": "خواندن تنظیمات",
  "settings.write": "تغییر تنظیمات",
};

function initTheme() {
  let saved;
  try {
    saved = localStorage.getItem("manix-theme");
  } catch {}
  document.documentElement.dataset.theme =
    saved ||
    (matchMedia("(prefers-color-scheme:light)").matches ? "light" : "dark");
  setThemeLabel();
}
function setThemeLabel() {
  const light = document.documentElement.dataset.theme === "light";
  $("#themeToggle").setAttribute(
    "aria-label",
    light ? "فعال کردن حالت تاریک" : "فعال کردن حالت روشن",
  );
  $("#themeToggle").title = light ? "حالت تاریک" : "حالت روشن";
}
$("#themeToggle").addEventListener("click", () => {
  const root = document.documentElement;
  root.dataset.theme = root.dataset.theme === "light" ? "dark" : "light";
  try {
    localStorage.setItem("manix-theme", root.dataset.theme);
  } catch {}
  setThemeLabel();
  drawChart();
  drawExtraCharts();
});
initTheme();

async function loadManixPage(name) {
  const fn = {
    worlds: loadWorlds,
    packs: loadPacks,
    schedules: loadSchedules,
    account: loadAccount,
  }[name];
  if (fn) await fn();
}
function updateManixButtons(busy, running) {
  ["#copySelected", "#moveSelected", "#deleteSelected"].forEach(
    (id) => ($(id).disabled = busy || running || !selectedFiles.size),
  );
  $("#packActivateForm button[type=submit]").disabled = busy || running;
  $$("#worldRows [data-export]").forEach((n) => (n.disabled = busy));
  $$(
    "#taskForm button[type=submit],#keyForm button[type=submit],#profileForm button[type=submit],#passwordForm button[type=submit]",
  ).forEach((n) => (n.disabled = localBusy));
}
function renderManixStatus(data) {
  const m = data.metrics,
    node = data.node || {};
  text("#nodeName", node.name || "نود مانیکس");
  text(
    "#nodeInfo",
    `${node.status === "ready" ? "آماده" : "در حال اندازه‌گیری"} · ${node.region || "local"} · CPU: ${number(node.cpu_percent, 1)}٪ · سهمیه: ${node.cpus_quota ? number(node.cpus_quota) + " هسته" : "نامشخص"}`,
  );
  text(
    "#nodeMemory",
    `${number(node.memory_mb, 1)} MB${data.memory_limit_mb ? " / " + number(data.memory_limit_mb) + " MB" : ""}`,
  );
  text(
    "#nodeUptime",
    `پنل: ${number(Math.floor((node.uptime || 0) / 3600))} ساعت و ${number(Math.floor(((node.uptime || 0) % 3600) / 60))} دقیقه · ${node.memory_source === "cgroup" ? "cgroup" : "برآورد پنل + بازی"}`,
  );
  text(
    "#networkRate",
    `↓ ${number(m.network_rx_kbps, 1)} KB/s · ↑ ${number(m.network_tx_kbps, 1)} KB/s`,
  );
  text(
    "#networkTotal",
    `دریافت ${bytes(m.network_rx_bytes || 0)} · ارسال ${bytes(m.network_tx_bytes || 0)} · کل سرویس`,
  );
  const messages = data.warnings || [];
  $("#resourceWarning").hidden = !messages.length;
  $("#resourceWarning span").textContent = messages.join(" ");
  for (const message of messages) {
    if (!warningSeen.has(message)) {
      warningSeen.add(message);
      if (Date.now() - (warningLastAt.get(message) || 0) > 60000) {
        warningLastAt.set(message, Date.now());
        toast(message, true);
      }
    }
  }
  for (const old of warningSeen) {
    if (!messages.includes(old)) warningSeen.delete(old);
  }
  cpuSamples.push(m.cpu_percent || 0);
  diskSamples.push((m.disk_used_mb || 0) / 1024);
  if (cpuSamples.length > 30) cpuSamples.shift();
  if (diskSamples.length > 30) diskSamples.shift();
  drawExtraCharts();
  if (previousPhase !== null && previousPhase !== data.phase) {
    if (data.phase === "running") toast("سرور مانیکس روشن شد.");
    if (data.phase === "stopped") {
      const crash =
        data.last_exit_expected === false &&
        data.last_exit !== null &&
        data.last_exit !== 0;
      toast(
        crash
          ? "بازی با خطا/Crash متوقف شد؛ کنسول را بررسی کن."
          : "سرور بازی متوقف شد.",
        crash,
      );
    }
  }
  previousPhase = data.phase;
  const job = data.job;
  if (
    job &&
    job.title.includes("بکاپ") &&
    ["queued", "running"].includes(job.state) &&
    !startedBackupJobs.has(job.id)
  ) {
    startedBackupJobs.add(job.id);
    if (startedBackupJobs.size > 200) startedBackupJobs.clear();
    toast("بکاپ مانیکس در حال آماده‌سازی است.");
  }
}
function lineChart(id, values, max, unit) {
  const canvas = $(id);
  if (!canvas || currentPage !== "overview") return;
  const w = canvas.clientWidth || 260,
    h = 115,
    dpr = devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  const style = getComputedStyle(document.documentElement);
  ctx.strokeStyle = style.getPropertyValue("--border-light").trim();
  ctx.setLineDash([3, 4]);
  for (const y of [25, 55, 85]) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  const points = values.map((v, i) => [
    (i * w) / Math.max(1, values.length - 1),
    100 - (v / Math.max(max, 0.01)) * 85,
  ]);
  if (points.length > 1) {
    ctx.beginPath();
    points.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)));
    ctx.strokeStyle = style.getPropertyValue("--green").trim();
    ctx.lineWidth = 1.7;
    ctx.stroke();
  }
  text(id + "Max", number(max, unit === "GB" ? 1 : 0) + " " + unit);
}
function drawExtraCharts() {
  lineChart("#cpuChart", cpuSamples, Math.max(100, ...cpuSamples), "%");
  lineChart("#diskChart", diskSamples, Math.max(0.1, ...diskSamples), "GB");
}
window.addEventListener("resize", drawExtraCharts);
async function liveManixTables() {
  tablePolls++;
  if (tablePolls % 5 !== 0) return;
  if (currentPage === "players") await loadPlayers();
  if (currentPage === "schedules") await loadSchedules();
}

function manixFileUrl() {
  const q = $("#fileSearch").value.trim(),
    params = new URLSearchParams({ path: currentPath });
  if (q) {
    params.set("q", q);
    params.set("recursive", String($("#fileRecursive").checked));
  }
  return (q ? "/api/files/search?" : "/api/files?") + params;
}
function paginateManixFiles(files) {
  const type = $("#fileTypeFilter").value,
    key = [
      currentPath,
      $("#fileSearch").value,
      $("#fileRecursive").checked,
      type,
    ].join("|");
  if (key !== fileStateKey) {
    filePage = 0;
    selectedFiles.clear();
    fileStateKey = key;
  }
  const matches = files.filter(
    (f) => type === "all" || (type === "dirs" ? f.dir : !f.dir),
  );
  fileTotal = matches.length;
  filePage = Math.min(filePage, Math.max(0, Math.ceil(fileTotal / 50) - 1));
  fileRowsVisible = matches.slice(filePage * 50, filePage * 50 + 50);
  text("#fileCount", number(fileTotal) + " مورد");
  text(
    "#filesPageInfo",
    `${number(filePage + 1)} / ${number(Math.max(1, Math.ceil(fileTotal / 50)))}`,
  );
  $("#filesPrev").disabled = filePage === 0;
  $("#filesNext").disabled = (filePage + 1) * 50 >= fileTotal;
  return fileRowsVisible;
}
function enhanceFileRow(tr, file) {
  tr.dataset.path = file.path;
  const td = el("td", "select-col"),
    input = el("input");
  input.type = "checkbox";
  input.disabled = !!file.symlink;
  input.checked = selectedFiles.has(file.path);
  input.setAttribute("aria-label", "انتخاب " + file.name);
  input.addEventListener("change", () => {
    if (input.checked) selectedFiles.add(file.path);
    else selectedFiles.delete(file.path);
    updateFileSelection();
    updateButtons();
  });
  td.append(input);
  tr.prepend(td);
}
function updateFileSelection() {
  text(
    "#selectedFileCount",
    selectedFiles.size
      ? number(selectedFiles.size) + " مورد انتخاب‌شده"
      : "هیچ موردی انتخاب نشده",
  );
  const available = fileRowsVisible.filter((f) => !f.symlink),
    check = $("#fileSelectAll");
  check.checked =
    !!available.length && available.every((f) => selectedFiles.has(f.path));
  check.indeterminate =
    available.some((f) => selectedFiles.has(f.path)) && !check.checked;
}
$("#fileSelectAll").addEventListener("change", (e) => {
  fileRowsVisible
    .filter((f) => !f.symlink)
    .forEach((f) =>
      e.target.checked
        ? selectedFiles.add(f.path)
        : selectedFiles.delete(f.path),
    );
  $$("#fileRows tr[data-path]").forEach(
    (tr) =>
      ($("input[type=checkbox]", tr).checked = selectedFiles.has(
        tr.dataset.path,
      )),
  );
  updateFileSelection();
  updateButtons();
});
$("#clearFileSelection").addEventListener("click", () => {
  selectedFiles.clear();
  $$("#fileRows input[type=checkbox]").forEach((n) => (n.checked = false));
  updateFileSelection();
  updateButtons();
});
let searchDebounce = null;
$("#fileSearch").addEventListener("input", () => {
  clearTimeout(searchDebounce);
  searchDebounce = setTimeout(() => safe(loadFiles)(), 250);
});
$("#fileRecursive").addEventListener("change", safe(loadFiles));
$("#fileTypeFilter").addEventListener("change", safe(loadFiles));
$("#filesPrev").addEventListener(
  "click",
  safe(async () => {
    filePage = Math.max(0, filePage - 1);
    await loadFiles();
  }),
);
$("#filesNext").addEventListener(
  "click",
  safe(async () => {
    filePage++;
    await loadFiles();
  }),
);
async function batchSelected(operation) {
  await action(async () => {
    const paths = [...selectedFiles];
    if (!paths.length) return;
    if (paths.length > 200)
      throw new Error("حداکثر ۲۰۰ مورد در یک عملیات مجاز است.");
    let destination = "";
    if (operation === "delete") {
      if (
        !(await ask({
          title: "حذف گروهی " + number(paths.length) + " مورد",
          description:
            "قبل از حذف یک بکاپ کامل ذخیره می‌شود. پوشه‌های انتخاب‌شده با همهٔ محتویاتشان حذف می‌شوند.\n" +
            paths.slice(0, 8).join("\n"),
          confirm: "بکاپ و حذف گروهی",
          danger: true,
        }))
      )
        return;
    } else {
      const data = await ask({
        title:
          operation === "copy"
            ? "کپی موارد انتخاب‌شده"
            : "انتقال موارد انتخاب‌شده",
        description:
          "مقصد باید یک پوشهٔ موجود باشد. فایل هم‌نام بازنویسی نمی‌شود. مسیر نسبت به server است.",
        fields: [
          {
            name: "destination",
            label: "پوشهٔ مقصد (خالی = ریشه)",
            dir: "ltr",
          },
        ],
        confirm: operation === "copy" ? "کپی" : "انتقال",
      });
      if (!data) return;
      destination = data.destination;
    }
    await api("/api/files/batch", {
      method: "POST",
      body: { action: operation, paths, destination },
    });
    selectedFiles.clear();
    updateFileSelection();
  });
}
$("#copySelected").addEventListener("click", () => batchSelected("copy"));
$("#moveSelected").addEventListener("click", () => batchSelected("move"));
$("#deleteSelected").addEventListener("click", () => batchSelected("delete"));

async function loadWorlds() {
  const data = await api("/api/worlds"),
    rows = $("#worldRows");
  rows.replaceChildren();
  text("#activeWorld", "فعال: " + data.active);
  if (!data.worlds.length)
    emptyTable(rows, 4, "هنوز دنیایی تولید یا وارد نشده است.");
  for (const world of data.worlds) {
    const tr = el("tr"),
      name = el("td"),
      title = el("strong", "", world.name);
    title.dir = "auto";
    name.append(
      title,
      el(
        "p",
        "small-note",
        world.generated
          ? "دنیای دارای level.dat"
          : "آمادهٔ تولید در اولین Start",
      ),
    );
    const size = el("td");
    size.append(
      el("span", "", bytes(world.size)),
      el("p", "small-note", world.dimensions.join(" · ")),
    );
    const status = el("td");
    status.append(
      el(
        "span",
        world.active ? "tag-enabled" : "tag-disabled",
        world.active ? "فعال" : "غیرفعال",
      ),
    );
    const ops = el("td"),
      box = el("div", "row-actions");
    if (!world.active)
      box.append(
        smallButton(
          "check",
          "فعال کردن دنیا",
          () =>
            action(async () => {
              if (
                !(await ask({
                  title: "فعال کردن " + world.name,
                  description:
                    "level-name تغییر می‌کند. هنگام Start بعدی، Minecraft این دنیا را باز می‌کند.",
                  confirm: "فعال کن",
                }))
              )
                return;
              await api("/api/worlds/select", {
                method: "POST",
                body: { name: world.name },
              });
              await loadWorlds();
            }),
          true,
        ),
      );
    const download = smallButton("download", "ZIP و دانلود این دنیا", () =>
      action(async () => {
        if (
          server?.running &&
          !(await ask({
            title: "خروجی سالم دنیا",
            description:
              "بازی موقتاً متوقف و سپس دوباره روشن می‌شود؛ بازیکن‌ها قطع می‌شوند.",
            confirm: "ساخت ZIP",
          }))
        )
          return;
        await api("/api/worlds/export", {
          method: "POST",
          body: { name: world.name },
        });
      }),
    );
    download.dataset.export = "true";
    box.append(download);
    if (!world.active)
      box.append(
        smallButton(
          "trash",
          "حذف دنیا و ابعاد وابسته",
          () =>
            action(async () => {
              if (
                !(await ask({
                  title: "حذف دنیا " + world.name,
                  description:
                    "ابتدا بکاپ کامل ساخته می‌شود؛ بعد پوشهٔ این دنیا و ابعاد _nether و _the_end وابسته حذف می‌شوند.",
                  confirm: "بکاپ و حذف",
                  danger: true,
                }))
              )
                return;
              await api("/api/worlds", {
                method: "DELETE",
                body: { name: world.name },
              });
            }),
          true,
          true,
        ),
      );
    ops.append(box);
    tr.append(name, size, status, ops);
    rows.append(tr);
  }
  updateButtons();
}
$("#refreshWorlds").addEventListener("click", safe(loadWorlds));
$("#worldCreateForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    const data = await api("/api/worlds/create", {
      method: "POST",
      body: { name: form.elements.name.value.trim() },
    });
    toast(data.message);
    form.reset();
    await loadWorlds();
  });
});
$("#worldImportForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    await api("/api/worlds/import", {
      method: "POST",
      body: new FormData(form),
    });
    form.reset();
  });
});

async function loadPacks() {
  const data = await api("/api/packs"),
    rows = $("#packRows"),
    select = $("#packSelect");
  rows.replaceChildren();
  select.replaceChildren(el("option", "", "بدون ریسورس‌پک"));
  select.firstElementChild.value = "";
  if (!data.packs.length)
    emptyTable(rows, 4, "هنوز ریسورس‌پکی آپلود نشده است.");
  for (const pack of data.packs) {
    const option = el("option", "", pack.name);
    option.value = pack.id;
    select.append(option);
    const tr = el("tr"),
      name = el("td");
    name.append(
      el("strong", "", pack.name),
      el("p", "small-note", "SHA-1: " + pack.sha1),
    );
    const size = el("td");
    size.append(
      el("span", "", bytes(pack.size)),
      el("p", "small-note", "Format: " + JSON.stringify(pack.format)),
    );
    const state = el("td");
    state.append(
      el(
        "span",
        pack.active ? "tag-enabled" : "tag-disabled",
        pack.active ? "فعال" : "غیرفعال",
      ),
    );
    const ops = el("td"),
      box = el("div", "row-actions"),
      link = el("a", "icon-btn");
    link.href = "/packs/" + pack.id + ".zip";
    link.title = "دانلود ZIP عمومی پک";
    link.setAttribute("aria-label", "دانلود " + pack.name);
    link.append(ico("download"));
    box.append(link);
    if (!pack.active)
      box.append(
        smallButton(
          "trash",
          "حذف پک",
          () =>
            action(async () => {
              if (
                !(await ask({
                  title: "حذف " + pack.name,
                  description: "لینک عمومی این پک دیگر کار نخواهد کرد.",
                  confirm: "حذف",
                  danger: true,
                }))
              )
                return;
              await api("/api/packs/" + pack.id, { method: "DELETE" });
              await loadPacks();
            }),
          true,
          true,
        ),
      );
    ops.append(box);
    tr.append(name, size, state, ops);
    rows.append(tr);
  }
  select.value = data.active || "";
  const form = $("#packActivateForm");
  const current = data.properties["resource-pack"];
  let base = location.origin;
  if (current) {
    try {
      base = new URL(current).origin;
    } catch {}
  }
  form.elements.base_url.value = base;
  form.elements.required.checked =
    data.properties["require-resource-pack"] === "true";
  let prompt = "";
  try {
    prompt =
      JSON.parse(data.properties["resource-pack-prompt"] || "{}").text || "";
  } catch {}
  form.elements.prompt.value = prompt;
  updateButtons();
}
$("#refreshPacks").addEventListener("click", safe(loadPacks));
$("#uploadPack").addEventListener("click", () => $("#packUploadInput").click());
$("#packUploadInput").addEventListener("change", (e) => {
  const input = e.currentTarget,
    file = input.files[0];
  if (!file) return;
  action(async () => {
    const body = new FormData();
    body.append("file", file);
    await api("/api/packs/upload", { method: "POST", body });
    input.value = "";
    toast("ریسورس‌پک مانیکس ذخیره شد.");
    await loadPacks();
  });
});
$("#packActivateForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    const body = {
      id: form.elements.id.value,
      base_url: form.elements.base_url.value.trim(),
      required: form.elements.required.checked,
      prompt: form.elements.prompt.value,
    };
    await api("/api/packs/activate", { method: "POST", body });
    toast("تنظیمات پک ذخیره شد؛ از Start بعدی اعمال می‌شود.");
    await loadPacks();
  });
});

function taskTime(timestamp, zone) {
  if (!timestamp) return "—";
  try {
    return new Date(timestamp * 1000).toLocaleString("fa-IR", {
      timeZone: zone,
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return when(timestamp);
  }
}
function updateTaskFields() {
  const form = $("#taskForm"),
    mode = form.elements.mode.value,
    command = form.elements.action.value === "command";
  $("#taskOnceLabel").hidden = mode !== "once";
  $("#taskTimeLabel").hidden = mode === "once";
  $("#taskWeekdayLabel").hidden = mode !== "weekly";
  $("#taskCommandLabel").hidden = !command;
  form.elements.command.required = command;
  form.elements.at.required = mode === "once" && form.elements.enabled.checked;
  form.elements.time.required = mode !== "once";
}
$("#taskMode").addEventListener("change", updateTaskFields);
$("#taskAction").addEventListener("change", updateTaskFields);
$("#taskForm [name=enabled]").addEventListener("change", updateTaskFields);
updateTaskFields();
function resetTask() {
  const form = $("#taskForm");
  form.reset();
  $("#editingTask").value = "";
  $("#cancelTaskEdit").hidden = true;
  text("#taskFormTitle", "Task جدید");
  updateTaskFields();
}
$("#cancelTaskEdit").addEventListener("click", resetTask);
async function loadSchedules() {
  const data = await api("/api/schedules"),
    rows = $("#taskRows");
  rows.replaceChildren();
  text("#taskCount", number(data.tasks.length) + " / ۵۰");
  if (!data.tasks.length) emptyTable(rows, 5, "هنوز Task ساخته نشده است.");
  const results = {
    done: "انجام شد",
    failed: "ناموفق؛ بررسی Job/کنسول",
    missed: "گذشته؛ عمداً اجرا نشد",
    claimed: "ثبت/در حال اجرا",
  };
  for (const task of data.tasks) {
    const tr = el("tr"),
      name = el("td");
    name.append(
      el("strong", "", task.name),
      el(
        "p",
        "small-note",
        taskNames[task.action] +
          " · " +
          ({ once: "یک‌باره", daily: "روزانه", weekly: "هفتگی" }[task.mode] ||
            task.mode),
      ),
    );
    const next = el("td");
    next.append(
      el("span", "", taskTime(task.next_run, task.timezone)),
      el("p", "small-note", task.timezone),
    );
    const previous = el("td");
    previous.append(
      el("span", "", taskTime(task.last_run, task.timezone)),
      el("p", "small-note", results[task.last_result] || "بدون اجرا"),
    );
    const state = el("td");
    state.append(
      el(
        "span",
        task.enabled ? "tag-enabled" : "tag-disabled",
        task.enabled ? "فعال" : "غیرفعال",
      ),
    );
    const ops = el("td"),
      box = el("div", "row-actions");
    box.append(
      smallButton(
        "power",
        task.enabled ? "غیرفعال کردن Task" : "فعال کردن Task",
        () =>
          action(async () => {
            await api("/api/schedules/" + task.id, {
              method: "PATCH",
              body: { enabled: !task.enabled },
            });
            await loadSchedules();
          }),
      ),
    );
    box.append(
      smallButton("edit", "ویرایش Task", () => {
        populateForm($("#taskForm"), task);
        $("#editingTask").value = task.id;
        $("#cancelTaskEdit").hidden = false;
        text("#taskFormTitle", "ویرایش " + task.name);
        updateTaskFields();
        $("#taskForm").scrollIntoView({ behavior: "smooth", block: "center" });
      }),
    );
    box.append(
      smallButton(
        "trash",
        "حذف Task",
        () =>
          action(async () => {
            if (
              !(await ask({
                title: "حذف Task",
                description: task.name,
                confirm: "حذف",
                danger: true,
              }))
            )
              return;
            await api("/api/schedules/" + task.id, { method: "DELETE" });
            if ($("#editingTask").value === task.id) resetTask();
            await loadSchedules();
          }),
        false,
        true,
      ),
    );
    ops.append(box);
    tr.append(name, next, previous, state, ops);
    rows.append(tr);
  }
}
$("#refreshSchedules").addEventListener("click", safe(loadSchedules));
$("#taskForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    const body = {
      name: form.elements.name.value,
      action: form.elements.action.value,
      mode: form.elements.mode.value,
      timezone: form.elements.timezone.value.trim(),
      at: form.elements.at.value,
      time: form.elements.time.value || "03:00",
      weekday: Number(form.elements.weekday.value),
      command: form.elements.command.value,
      enabled: form.elements.enabled.checked,
    };
    const identifier = $("#editingTask").value;
    await api("/api/schedules" + (identifier ? "/" + identifier : ""), {
      method: identifier ? "PUT" : "POST",
      body,
    });
    toast("Task مانیکس ذخیره شد.");
    resetTask();
    await loadSchedules();
  });
});

function playerText(item) {
  return typeof item === "string" ? item : item.name || item.ip || "—";
}
function renderManixPlayers() {
  if (!playerData) return;
  const data = playerData,
    q = $("#playerSearch").value.trim().toLowerCase(),
    box = $("#playerLists");
  box.replaceChildren();
  const info = new Map((data.online_info || []).map((r) => [r.name, r]));
  const lists = [
    [
      data.source === "console-list"
        ? "آنلاین (فهرست کنسول)"
        : "آنلاین (نمونهٔ Status)",
      data.online || [],
    ],
    ["وایت‌لیست", data.whitelist || []],
    ["دارای OP", data.ops || []],
    ["بن‌شده", data.banned || []],
    ["IPهای بن‌شده", data.banned_ips || []],
    ["آخرین ورودهای مشاهده‌شده", data.known || []],
  ];
  for (const [title, items] of lists) {
    const matches = items.filter((r) =>
        playerText(r).toLowerCase().includes(q),
      ),
      card = el("article", "card player-list"),
      head = el("h3", "", title);
    head.append(el("span", "mini-tag", number(matches.length)));
    card.append(head);
    if (!matches.length)
      card.append(
        el("div", "empty-state", q ? "نتیجه‌ای پیدا نشد." : "فهرست خالی است."),
      );
    else {
      const ul = el("ul");
      for (const item of matches.slice(0, 200)) {
        const name = playerText(item),
          li = el("li"),
          button = el("button", "player-name plain-button", name);
        button.addEventListener("click", () => {
          $("#playerName").value = name;
        });
        li.append(button);
        const detail = typeof item === "object" ? item : info.get(name);
        if (detail?.joined_at)
          li.append(
            el("span", "small-note", "ورود: " + when(detail.joined_at)),
          );
        if (title.startsWith("آخرین"))
          li.append(
            el(
              "span",
              "small-note",
              detail?.online
                ? "آنلاین از لاگ"
                : "آخرین وضعیت مشاهده‌شده: آفلاین",
            ),
          );
        ul.append(li);
      }
      card.append(ul);
      if (matches.length > 200)
        card.append(
          el("p", "small-note", "نمایش ۲۰۰ نتیجهٔ اول؛ جستجو را دقیق‌تر کن."),
        );
    }
    box.append(card);
  }
}
$("#playerSearch").addEventListener("input", renderManixPlayers);
function updatePlayerAction() {
  const action = $("#playerAction").value,
    name = $("#playerName"),
    ip = ["ban_ip", "pardon_ip"].includes(action),
    noName = ["whitelist_on", "whitelist_off"].includes(action);
  name.required = !noName;
  name.disabled = noName;
  name.maxLength = ip ? 64 : 16;
  if (ip || noName) name.removeAttribute("pattern");
  else name.pattern = "[A-Za-z0-9_]{3,16}";
  name.placeholder = ip ? "1.2.3.4 / IPv6" : "PlayerName";
  $("#targetCommandLabel").hidden = action !== "command";
  $("#playerCommand").required = action === "command";
}
$("#playerAction").addEventListener("change", updatePlayerAction);
updatePlayerAction();
async function sendPlayerAction() {
  const operation = $("#playerAction").value,
    name = $("#playerName").value;
  if (
    ["op", "ban", "ban_ip", "whitelist_off"].includes(operation) &&
    !(await ask({
      title: "تأیید عملیات بازیکن",
      description:
        operation === "ban_ip"
          ? "IP پشت TCP Proxy ممکن است متعلق به Proxy باشد، نه بازیکن. درستی IP " +
            name +
            " را بررسی کرده‌ای؟"
          : "این عملیات روی " + (name || "وایت‌لیست") + " اعمال می‌شود.",
      confirm: "اجرا",
    }))
  )
    return;
  await api("/api/players/action", {
    method: "POST",
    body: {
      action: operation,
      username: name,
      reason: $("#playerReason").value,
      command: $("#playerCommand").value,
    },
  });
  toast("دستور ارسال شد؛ نتیجه را در کنسول ببین.");
  setTimeout(() => safe(loadPlayers)(), 1000);
}

async function loadRuntimeEngines() {
  const data = await api("/api/versions/installed"),
    box = $("#runtimeRows");
  box.replaceChildren();
  if (!data.engines.length) {
    box.append(el("div", "empty-state", "هسته‌ای نصب نشده است."));
    return;
  }
  for (const engine of data.engines) {
    const row = el("div", "runtime-row"),
      info = el("div");
    info.append(
      el("strong", "", `${engine.kind} · ${engine.version}`),
      el(
        "p",
        "small-note",
        `Java ${engine.java} · ${bytes(engine.size)} · ${engine.active ? "فعال" : "قدیمی"}`,
      ),
    );
    row.append(info);
    if (!engine.active)
      row.append(
        smallButton(
          "trash",
          "حذف هستهٔ قدیمی",
          () =>
            action(async () => {
              if (
                !(await ask({
                  title: "حذف هستهٔ قدیمی",
                  description:
                    "فقط فایل runtime پاک می‌شود، نه سیو. بکاپ وابسته ممکن است نصب مجدد هسته را بخواهد.",
                  confirm: "حذف runtime",
                  danger: true,
                }))
              )
                return;
              await api("/api/versions/installed/" + engine.id, {
                method: "DELETE",
              });
              await loadRuntimeEngines();
            }),
          true,
          true,
        ),
      );
    box.append(row);
  }
  updateButtons();
}
$("#customJarForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    if (
      !(await ask({
        title: "اعتماد به JAR اجرایی",
        description:
          "این فایل با دسترسی همان کاربر کانتینر اجرا می‌شود و می‌تواند فایل‌های پنل را بخواند. فقط JAR سرور مورداعتماد خودت را نصب کن. ساخت خودکار Spigot انجام نمی‌شود.",
        confirm: "اعتماد دارم؛ نصب کن",
        danger: true,
      }))
    )
      return;
    const data = new FormData(form);
    data.set("allow_downgrade", String(form.elements.allow_downgrade.checked));
    await api("/api/versions/custom", { method: "POST", body: data });
    form.reset();
  });
});
async function loadManixStartup() {
  try {
    const data = await api("/api/startup");
    text(
      "#startupPreview",
      data.command || data.message || "هسته نصب نشده است.",
    );
  } catch (e) {
    text("#startupPreview", e.message);
  }
}

function clearAccountSecrets() {
  $$("#passwordForm input,#keyForm input[type=password]").forEach(
    (n) => (n.value = ""),
  );
  $("#secretValue").value = "";
  if ($("#secretDialog").open) $("#secretDialog").close();
  if ($("#promptDialog").open) endPrompt(null);
  previousPhase = null;
  warningSeen.clear();
}
function showSecret(title, value, hint) {
  text("#secretTitle", title);
  text("#secretHint", hint);
  $("#secretValue").value = value;
  $("#secretDialog").showModal();
}
function closeSecret() {
  $("#secretValue").value = "";
  $("#secretDialog").close();
}
$("#closeSecret").addEventListener("click", closeSecret);
$("#acknowledgeSecret").addEventListener("click", closeSecret);
$("#secretDialog").addEventListener("cancel", (e) => {
  e.preventDefault();
  closeSecret();
});
$("#copySecret").addEventListener(
  "click",
  safe(async () => {
    try {
      await navigator.clipboard.writeText($("#secretValue").value);
      toast("کپی شد؛ در محل امن آفلاین ذخیره کن.");
    } catch {
      $("#secretValue").select();
      toast("متن انتخاب شد؛ Ctrl/Cmd+C را بزن.");
    }
  }),
);
async function requestPassword(title) {
  return await ask({
    title,
    fields: [
      {
        name: "password",
        label: "رمز فعلی پنل",
        type: "password",
        required: true,
        autocomplete: "current-password",
      },
    ],
    confirm: "ادامه",
  });
}
async function loadAccount() {
  const data = await api("/api/account");
  populateForm($("#profileForm"), data);
  text("#factorStatus", data.two_factor ? "۲FA فعال" : "۲FA غیرفعال");
  text(
    "#factorRecovery",
    data.two_factor
      ? number(data.recovery_remaining) +
          " کد بازیابی باقی مانده؛ کدها یک‌بارمصرف‌اند."
      : "پس از فعال‌سازی، هشت کد بازیابی را خارج از سرور نگه دار.",
  );
  $("#enableFactor").hidden = data.two_factor;
  $("#disableFactor").hidden = !data.two_factor;
  const devices = $("#deviceRows");
  devices.replaceChildren();
  for (const device of data.devices) {
    const row = el("div", "device-row"),
      info = el("div");
    info.append(
      el("strong", "", device.current ? "همین نشست" : "نشست دیگر"),
      el(
        "p",
        "small-note",
        (device.ip || "IP قدیمی ثبت نشده") +
          " · " +
          (device.agent || "دستگاه نامشخص"),
      ),
      el(
        "p",
        "small-note",
        "شروع: " +
          (device.created ? when(device.created) : "نامشخص") +
          " · انقضا: " +
          when(device.expires),
      ),
    );
    row.append(
      info,
      smallButton("logout", "بستن نشست", () =>
        action(async () => {
          await api("/api/account/devices/" + device.id, { method: "DELETE" });
          if (device.current) showLogin();
          else await loadAccount();
        }),
      ),
    );
    devices.append(row);
  }
  const scopes = $("#keyScopes");
  scopes.replaceChildren();
  for (const value of data.scopes) {
    const label = el("label", "check-block"),
      input = el("input");
    input.type = "checkbox";
    input.name = "scopes";
    input.value = value;
    input.checked = value === "status";
    label.append(input, el("span", "", scopeLabels[value] || value));
    scopes.append(label);
  }
  const keys = $("#keyRows");
  keys.replaceChildren();
  if (!data.api_keys.length)
    keys.append(el("div", "empty-state", "کلیدی صادر نشده است."));
  for (const key of data.api_keys) {
    const row = el("div", "key-row"),
      info = el("div");
    info.append(
      el("strong", "", key.name),
      el(
        "p",
        "small-note",
        key.scopes.map((s) => scopeLabels[s] || s).join(" · "),
      ),
      el(
        "p",
        "small-note",
        "انقضا: " +
          when(key.expires) +
          (key.last_used ? " · آخرین استفاده: " + when(key.last_used) : ""),
      ),
    );
    row.append(
      info,
      smallButton(
        "trash",
        "لغو API Key",
        () =>
          action(async () => {
            if (
              !(await ask({
                title: "لغو کلید " + key.name,
                description: "درخواست‌های این کلید فوراً رد می‌شوند.",
                confirm: "لغو",
                danger: true,
              }))
            )
              return;
            await api("/api/account/keys/" + key.id, { method: "DELETE" });
            await loadAccount();
          }),
        false,
        true,
      ),
    );
    keys.append(row);
  }
  const history = $("#loginHistoryRows");
  history.replaceChildren();
  for (const event of data.login_history) {
    const row = el("div", "audit-row"),
      content = el("div");
    content.append(el("strong", "", event.action), el("p", "", event.detail));
    row.append(el("time", "", when(event.time)), content);
    history.append(row);
  }
}
$("#refreshAccount").addEventListener("click", safe(loadAccount));
$("#profileForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    await api("/api/account", {
      method: "PATCH",
      body: {
        display_name: form.elements.display_name.value,
        email: form.elements.email.value.trim(),
      },
    });
    toast("پروفایل مانیکس ذخیره شد.");
  });
});
$("#passwordForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    if (form.elements.new_password.value !== form.elements.confirm.value)
      throw new Error("تکرار رمز جدید یکسان نیست.");
    if (
      !(await ask({
        title: "تغییر رمز عبور",
        description:
          "همهٔ نشست‌ها و API Keyها لغو می‌شوند؛ دوباره باید وارد شوی.",
        confirm: "تغییر رمز",
      }))
    )
      return;
    const data = await api("/api/account/password", {
      method: "POST",
      body: {
        password: form.elements.password.value,
        new_password: form.elements.new_password.value,
      },
    });
    toast(data.message);
    form.reset();
    showLogin();
  });
});
$("#logoutAll").addEventListener("click", () =>
  action(async () => {
    if (
      !(await ask({
        title: "خروج از همهٔ دستگاه‌ها",
        description:
          "همین نشست هم بسته می‌شود. API Key مستقل است؛ برای لغو، کلید را جدا حذف کن.",
        confirm: "خروج از همه",
        danger: true,
      }))
    )
      return;
    await api("/api/account/logout-all", { method: "POST" });
    showLogin();
    toast("همهٔ نشست‌های مانیکس بسته شدند.");
  }),
);
$("#enableFactor").addEventListener(
  "click",
  safe(async () => {
    const input = await requestPassword("شروع فعال‌سازی ۲FA");
    if (!input) return;
    const setup = await api("/api/account/2fa/setup", {
      method: "POST",
      body: input,
    });
    showSecret(
      "Secret برنامهٔ Authenticator",
      "Secret:\n" + setup.secret + "\n\notpauth URI:\n" + setup.uri,
      "در Authenticator یک حساب با نام Manix و کلید Secret بالا، نوع Time-based و شش رقم اضافه کن. پس از ذخیره این پنجره را ببند و کد را وارد کن.",
    );
    await new Promise((resolve) =>
      $("#secretDialog").addEventListener("close", resolve, { once: true }),
    );
    const code = await ask({
      title: "تأیید کد برنامه",
      description:
        "یک کد شش‌رقمی فعلی را وارد کن. تنظیمات موقت پس از ۱۰ دقیقه منقضی می‌شوند.",
      fields: [
        { name: "code", label: "کد ۲FA", required: true, max: 6, dir: "ltr" },
      ],
      confirm: "فعال کن",
    });
    if (!code) return;
    const confirmed = await api("/api/account/2fa/confirm", {
      method: "POST",
      body: code,
    });
    await loadAccount();
    showSecret(
      "کدهای بازیابی مانیکس",
      confirmed.recovery_codes.join("\n"),
      "این هشت کد فقط یک بار نمایش داده می‌شوند. هر کد یک بار به‌جای کد برنامه قابل‌استفاده است؛ خارج از سرور ذخیره کن.",
    );
    toast("۲FA فعال شد؛ نشست‌های دیگر بسته شدند.");
  }),
);
$("#disableFactor").addEventListener("click", () =>
  action(async () => {
    const input = await ask({
      title: "غیرفعال کردن ۲FA",
      description:
        "رمز و یک کد فعلی یا بازیابیِ استفاده‌نشده لازم است. نشست‌های دیگر بسته می‌شوند.",
      fields: [
        {
          name: "password",
          label: "رمز فعلی",
          type: "password",
          required: true,
        },
        {
          name: "code",
          label: "کد ۲FA / بازیابی",
          required: true,
          dir: "ltr",
          max: 80,
        },
      ],
      confirm: "غیرفعال کن",
      danger: true,
    });
    if (!input) return;
    await api("/api/account/2fa/disable", { method: "POST", body: input });
    toast("۲FA غیرفعال شد.");
    await loadAccount();
  }),
);
$("#keyForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const form = e.currentTarget;
  action(async () => {
    const scopes = $$("#keyScopes input:checked").map((n) => n.value);
    if (!scopes.length) throw new Error("حداقل یک دسترسی انتخاب کن.");
    const data = await api("/api/account/keys", {
      method: "POST",
      body: {
        name: form.elements.name.value,
        days: Number(form.elements.days.value),
        password: form.elements.password.value,
        scopes,
      },
    });
    form.reset();
    await loadAccount();
    showSecret(
      "API Key مانیکس",
      data.token,
      "فقط یک بار نمایش داده می‌شود؛ در GitHub، URL، لاگ یا مرورگر اشتراکی نگذار. درخواست‌ها با Authorization: Bearer انجام می‌شوند.",
    );
  });
});
icons();
