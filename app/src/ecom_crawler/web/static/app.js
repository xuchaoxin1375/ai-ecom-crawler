const listView = document.querySelector("#list-view");
const detailView = document.querySelector("#detail-view");
const taskRows = document.querySelector("#task-rows");
const itemRows = document.querySelector("#item-rows");
const listStatus = document.querySelector("#list-status");
const detailStatus = document.querySelector("#detail-status");
const itemsStatus = document.querySelector("#items-status");
const createStatus = document.querySelector("#create-status");

let detailTimer = null;
let eventSource = null;
let currentTaskId = null;
let currentKind = "product";
let rulesLoaded = false;
let rulesCache = [];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setStatus(element, message, isError = false) {
  element.textContent = message || "";
  element.classList.toggle("error", isError);
}

async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = {};
  }
  if (!response.ok) {
    throw new Error(payload?.error?.message || `HTTP ${response.status}`);
  }
  return payload;
}

function apiPost(path, body) {
  return api(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
}

function requestId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function countsText(counts) {
  if (!counts || typeof counts !== "object") return "-";
  return Object.entries(counts)
    .map(([key, value]) => `${key}=${value}`)
    .join("  ");
}

function stateClass(state) {
  return `state state-${String(state || "").toLowerCase()}`;
}

async function loadRules() {
  if (rulesLoaded) return;
  rulesLoaded = true;
  const select = document.querySelector("#rule-select");
  const submit = document.querySelector("#create-submit");
  try {
    const payload = await api("/api/rules");
    rulesCache = Array.isArray(payload.items) ? payload.items : [];
    if (!payload.configured) {
      select.innerHTML = '<option value="">未配置 --rules-dir</option>';
      submit.disabled = true;
      setStatus(createStatus, "serve 未配置 --rules-dir，当前只能查看任务。", true);
      return;
    }
    const valid = rulesCache.filter((rule) => rule.valid);
    if (!valid.length) {
      select.innerHTML = '<option value="">没有可用规则包</option>';
      submit.disabled = true;
      setStatus(createStatus, "规则目录中没有可用规则包。", true);
      return;
    }
    select.innerHTML = valid
      .map((rule) => {
        const key = `${rule.rule_id}@${rule.rule_version}`;
        const label = `${rule.site || rule.rule_id} · ${key} · ${rule.market || "-"}`;
        return `<option value="${escapeHtml(key)}">${escapeHtml(label)}</option>`;
      })
      .join("");
    setStatus(createStatus, `已加载 ${valid.length} 个规则包`);
  } catch (error) {
    submit.disabled = true;
    setStatus(createStatus, `规则加载失败：${error.message}`, true);
  }
}

function renderList(tasks) {
  if (!tasks.length) {
    taskRows.innerHTML = '<tr><td colspan="8" class="empty">没有任务</td></tr>';
    return;
  }
  taskRows.innerHTML = tasks
    .map((task) => {
      const href = `#/tasks/${encodeURIComponent(task.task_id)}`;
      const archived = task.archived_at ? ' <span class="state state-excluded">归档</span>' : "";
      return `
        <tr>
          <td><a href="${href}">${escapeHtml(task.task_id)}</a>${archived}</td>
          <td>${escapeHtml(task.task_type)}</td>
          <td>
            <div>${escapeHtml(task.site_key || "-")}</div>
            <div class="muted">${escapeHtml(task.plan_id)}@${escapeHtml(task.plan_version)}</div>
          </td>
          <td>${escapeHtml(task.market || "-")}</td>
          <td><span class="${stateClass(task.state)}">${escapeHtml(task.state)}</span></td>
          <td>${escapeHtml(task.outcome || "-")}${task.stop_reason ? `<div class="muted">${escapeHtml(task.stop_reason)}</div>` : ""}</td>
          <td class="counts-cell">${escapeHtml(countsText(task.counts))}</td>
          <td>${escapeHtml(task.updated_at || "-")}</td>
        </tr>`;
    })
    .join("");
}

async function loadList() {
  setStatus(listStatus, "加载中…");
  const params = new URLSearchParams();
  const state = document.querySelector("#filter-state").value;
  const type = document.querySelector("#filter-type").value;
  const archived = document.querySelector("#filter-archived").checked;
  if (state) params.set("state", state);
  if (type) params.set("task_type", type);
  if (archived) params.set("include_archived", "true");
  try {
    const payload = await api(`/api/tasks?${params.toString()}`);
    renderList(payload.items || []);
    setStatus(listStatus, `共 ${payload.total ?? 0} 个任务`);
  } catch (error) {
    renderList([]);
    setStatus(listStatus, `读取失败：${error.message}`, true);
  }
}

async function createTask(event) {
  event.preventDefault();
  const select = document.querySelector("#rule-select");
  const submit = document.querySelector("#create-submit");
  const key = select.value;
  const rule = rulesCache.find(
    (item) => `${item.rule_id}@${item.rule_version}` === key,
  );
  if (!rule) {
    setStatus(createStatus, "请选择规则包。", true);
    return;
  }
  const body = {
    request_id: requestId(),
    rule_id: rule.rule_id,
    rule_version: rule.rule_version,
    task_type: document.querySelector("#create-type").value,
    limits: {
      max_products: Number(document.querySelector("#create-max-products").value || 20),
      max_urls: Number(document.querySelector("#create-max-urls").value || 100),
      max_seconds: Number(document.querySelector("#create-max-seconds").value || 180),
    },
  };
  submit.disabled = true;
  setStatus(createStatus, "创建中…");
  try {
    const created = await apiPost("/api/tasks", body);
    const taskId = created.task.task_id;
    setStatus(createStatus, `已创建 ${taskId}，正在启动…`);
    if (created.task.state === "DRAFT") {
      await apiPost(`/api/tasks/${encodeURIComponent(taskId)}/start`);
    }
    setStatus(createStatus, `任务 ${taskId} 已进入队列；由 worker 执行。`);
    window.location.hash = `#/tasks/${encodeURIComponent(taskId)}`;
  } catch (error) {
    setStatus(createStatus, `创建失败：${error.message}`, true);
  } finally {
    submit.disabled = false;
  }
}

function controlActions(task) {
  if (task.archived_at) return ["restore"];
  if (task.state === "DRAFT") return ["start", "cancel"];
  if (task.state === "QUEUED") return ["cancel"];
  if (task.state === "RUNNING") return ["pause", "cancel"];
  if (task.state === "PAUSING") return ["cancel"];
  if (task.state === "PAUSED") return ["resume", "cancel"];
  if (task.state === "CANCELLING") return [];
  if (task.state === "FINISHED" || task.state === "CANCELLED") return ["archive"];
  return [];
}

function actionLabel(action) {
  return {
    start: "启动",
    pause: "暂停",
    resume: "恢复",
    cancel: "取消任务",
    archive: "归档",
    restore: "还原",
  }[action];
}

async function controlTask(action) {
  if (!currentTaskId) return;
  setStatus(detailStatus, `已提交${actionLabel(action)}请求，等待后台确认…`);
  try {
    const payload = await apiPost(
      `/api/tasks/${encodeURIComponent(currentTaskId)}/${action}`,
    );
    setStatus(
      detailStatus,
      `已受理：${actionLabel(action)}，当前 ${payload.state}；最终状态以任务账本为准。`,
    );
    setTimeout(() => {
      if (currentTaskId) loadDetail(currentTaskId);
    }, 500);
  } catch (error) {
    setStatus(detailStatus, `操作失败：${error.message}`, true);
  }
}

function renderControls(task) {
  const controls = document.querySelector("#detail-controls");
  const actions = controlActions(task);
  if (!actions.length) {
    controls.innerHTML = '<span class="muted">当前状态无可执行操作</span>';
    return;
  }
  controls.innerHTML = actions
    .map(
      (action) =>
        `<button type="button" data-action="${action}">${escapeHtml(actionLabel(action))}</button>`,
    )
    .join("");
  controls.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => controlTask(button.dataset.action));
  });
}

function renderDetail(task) {
  document.title = `${task.task_id} · 采集任务`;
  document.querySelector("#detail-title").textContent = task.task_id;
  document.querySelector("#export-link").href = `/api/tasks/${encodeURIComponent(task.task_id)}/export`;
  const coverage = task.coverage?.status || "UNKNOWN";
  const stop = task.stop_reason || "-";
  const outcome = task.outcome || "-";
  const qualityCount = Array.isArray(task.quality_exceptions) ? task.quality_exceptions.length : 0;
  document.querySelector("#detail-meta").innerHTML = `
    <div><span class="label">状态</span><span class="${stateClass(task.state)}">${escapeHtml(task.state)}</span></div>
    <div><span class="label">结果</span>${escapeHtml(outcome)}</div>
    <div><span class="label">停止原因</span>${escapeHtml(stop)}</div>
    <div><span class="label">站点</span>${escapeHtml(task.site_key || "-")}</div>
    <div><span class="label">市场</span>${escapeHtml(task.market || "-")}</div>
    <div><span class="label">方案</span>${escapeHtml(task.plan_id)}@${escapeHtml(task.plan_version)}</div>
    <div><span class="label">类型</span>${escapeHtml(task.task_type)}</div>
    <div><span class="label">覆盖</span>${escapeHtml(coverage)}</div>
    <div><span class="label">质量异常</span>${qualityCount}</div>
    <div><span class="label">归档</span>${task.archived_at ? "是" : "否"}</div>
    <div><span class="label">更新时间</span>${escapeHtml(task.updated_at || "-")}</div>
  `;
  renderControls(task);
  const counts = task.counts || {};
  document.querySelector("#detail-counts").innerHTML = Object.entries(counts)
    .map(([key, value]) => `<div class="count"><span>${escapeHtml(key)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");

  const quality = Array.isArray(task.quality_exceptions) ? task.quality_exceptions : [];
  document.querySelector("#detail-quality").innerHTML = quality.length
    ? `<h2>质量异常</h2><ul>${quality
        .map((item) => `<li><code>${escapeHtml(JSON.stringify(item))}</code></li>`)
        .join("")}</ul>`
    : `<h2>质量异常</h2><p class="muted">无</p>`;
}

async function loadItems(taskId, kind) {
  currentKind = kind;
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.classList.toggle("active", tab.dataset.kind === kind);
  });
  setStatus(itemsStatus, "加载中…");
  try {
    const payload = await api(
      `/api/tasks/${encodeURIComponent(taskId)}/items?kind=${encodeURIComponent(kind)}&limit=200`,
    );
    if (!payload.items?.length) {
      itemRows.innerHTML = '<tr><td colspan="4" class="empty">暂无记录</td></tr>';
    } else {
      itemRows.innerHTML = payload.items
        .map(
          (item) => `
          <tr>
            <td class="url">${escapeHtml(item.url)}</td>
            <td><span class="${stateClass(item.state)}">${escapeHtml(item.state)}</span></td>
            <td>${escapeHtml(item.failure_class || "-")}</td>
            <td>${escapeHtml(item.attempts ?? 0)}</td>
          </tr>`,
        )
        .join("");
    }
    setStatus(itemsStatus, `共 ${payload.total ?? 0} 条`);
  } catch (error) {
    itemRows.innerHTML = "";
    setStatus(itemsStatus, `读取失败：${error.message}`, true);
  }
}

async function loadDetail(taskId) {
  currentTaskId = taskId;
  setStatus(detailStatus, "加载中…");
  try {
    const task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
    renderDetail(task);
    setStatus(detailStatus, "");
    await loadItems(taskId, currentKind);
  } catch (error) {
    setStatus(detailStatus, `读取失败：${error.message}`, true);
  }
}

function closeEvents() {
  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

function openEvents(taskId) {
  closeEvents();
  if (!window.EventSource) return;
  eventSource = new EventSource(`/api/tasks/${encodeURIComponent(taskId)}/events`);
  const refresh = () => {
    if (currentTaskId === taskId) loadDetail(taskId);
  };
  eventSource.addEventListener("snapshot", refresh);
  eventSource.addEventListener("update", refresh);
  eventSource.addEventListener("end", closeEvents);
  eventSource.onerror = closeEvents;
}

function route() {
  const hash = window.location.hash || "#/tasks";
  const match = hash.match(/^#\/tasks\/([^/]+)$/);
  if (detailTimer) {
    clearInterval(detailTimer);
    detailTimer = null;
  }
  closeEvents();
  if (match) {
    listView.hidden = true;
    detailView.hidden = false;
    const taskId = decodeURIComponent(match[1]);
    loadDetail(taskId);
    openEvents(taskId);
    detailTimer = setInterval(() => {
      if (currentTaskId === taskId) loadDetail(taskId);
    }, 5000);
  } else {
    detailView.hidden = true;
    listView.hidden = false;
    document.title = "采集任务 · 本地控制台";
    currentTaskId = null;
    loadRules();
    loadList();
  }
}

document.querySelector("#create-form").addEventListener("submit", createTask);
document.querySelector("#refresh-list").addEventListener("click", loadList);
document.querySelector("#refresh-detail").addEventListener("click", () => {
  if (currentTaskId) loadDetail(currentTaskId);
});
document.querySelector("#filter-state").addEventListener("change", loadList);
document.querySelector("#filter-type").addEventListener("change", loadList);
document.querySelector("#filter-archived").addEventListener("change", loadList);
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (currentTaskId) loadItems(currentTaskId, tab.dataset.kind);
  });
});
window.addEventListener("hashchange", route);
route();
