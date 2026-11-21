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
let lastListLoadedAt = null;
let lastDetailLoadedAt = null;

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
  const method = (options.method || "GET").toUpperCase();
  if (options.body) headers["Content-Type"] = "application/json";
  if (method !== "GET" && method !== "HEAD") {
    headers["X-Requested-With"] = "XMLHttpRequest";
  }
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

const COUNT_LABELS = {
  discovered_urls: "发现 URL",
  pending_navigation_entries: "待访问导航",
  product_candidates: "商品候选",
  pending_products: "待处理商品",
  in_flight_products: "在途商品",
  in_flight: "在途",
  processed_products: "已处理商品",
  valid_products: "有效商品",
  excluded_products: "业务排除",
  failed_products: "失败商品",
  partial_description_products: "部分描述",
  pending: "待处理",
  excluded: "业务排除",
  failed: "失败",
  navigation_urls: "导航页",
  url_candidates: "URL 候选",
  pending_urls: "待处理 URL",
  valid_urls: "有效 URL",
  excluded_urls: "排除 URL",
  failed_urls: "失败 URL",
};

function countLabel(key) {
  return COUNT_LABELS[key] || key;
}

function trustedTime(value) {
  return value ? value.toLocaleString("zh-CN", { hour12: false }) : "无";
}

function countsText(counts) {
  if (!counts || typeof counts !== "object") return "-";
  const entries = Object.entries(counts);
  if (!entries.length) return "-";
  const order = [
    "valid_products",
    "excluded_products",
    "failed_products",
    "pending_products",
    "in_flight_products",
    "in_flight",
    "excluded",
    "failed",
    "pending",
    "discovered_urls",
    "valid_urls",
    "excluded_urls",
    "failed_urls",
    "pending_urls",
  ];
  const parts = [];
  for (const key of order) {
    if (!(key in counts)) continue;
    if (key === "excluded" && "excluded_products" in counts) continue;
    if (key === "failed" && "failed_products" in counts) continue;
    if (key === "pending" && "pending_products" in counts) continue;
    if (key === "in_flight" && "in_flight_products" in counts) continue;
    const value = counts[key];
    if (value === 0 && !["valid_products", "valid_urls", "discovered_urls"].includes(key)) {
      continue;
    }
    parts.push(`${countLabel(key)} ${value}`);
  }
  if (!parts.length) {
    return entries.map(([key, value]) => `${countLabel(key)} ${value}`).join(" · ");
  }
  return parts.join(" · ");
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
    lastListLoadedAt = new Date();
    renderList(payload.items || []);
    setStatus(listStatus, `共 ${payload.total ?? 0} 个任务`);
  } catch (error) {
    setStatus(
      listStatus,
      `读取失败：${error.message}（最后可信时间：${trustedTime(lastListLoadedAt)}）`,
      true,
    );
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
  let created;
  try {
    created = await apiPost("/api/tasks", body);
  } catch (error) {
    setStatus(createStatus, `创建失败：${error.message}`, true);
    submit.disabled = false;
    return;
  }
  const taskId = created.task.task_id;
  let startFailed = false;
  try {
    setStatus(createStatus, `已创建 ${taskId}，正在启动…`);
    if (created.task.state === "DRAFT") {
      await apiPost(`/api/tasks/${encodeURIComponent(taskId)}/start`);
    }
    setStatus(createStatus, `任务 ${taskId} 已进入队列；由 worker 执行。`);
  } catch (error) {
    startFailed = true;
    setStatus(
      createStatus,
      `任务 ${taskId} 已创建，但启动失败：${error.message}；请到详情重试启动。`,
      true,
    );
  } finally {
    submit.disabled = false;
  }
  if (startFailed) {
    loadList();
    return;
  }
  window.location.hash = `#/tasks/${encodeURIComponent(taskId)}`;
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
  const controls = document.querySelector("#detail-controls");
  const buttons = controls.querySelectorAll("button");
  buttons.forEach((button) => {
    button.disabled = true;
  });
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
  } finally {
    buttons.forEach((button) => {
      button.disabled = false;
    });
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
  const exportLink = document.querySelector("#export-link");
  const terminal = ["FINISHED", "CANCELLED"].includes(task.state);
  const exportable = !["DRAFT", "QUEUED"].includes(task.state);
  exportLink.href = `/api/tasks/${encodeURIComponent(task.task_id)}/export${terminal ? "" : "?partial=true"}`;
  exportLink.textContent = terminal ? "导出 zip" : "部分导出 zip";
  exportLink.title = terminal
    ? "导出完整结果"
    : "任务未结束，只导出当前快照";
  exportLink.hidden = !exportable;
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
  const countEntries = Object.entries(counts).filter(
    ([key]) =>
      !(
        (key === "excluded" && "excluded_products" in counts) ||
        (key === "failed" && "failed_products" in counts) ||
        (key === "pending" && "pending_products" in counts) ||
        (key === "in_flight" && "in_flight_products" in counts)
      ),
  );
  document.querySelector("#detail-counts").innerHTML = countEntries
    .map(([key, value]) => `<div class="count"><span>${escapeHtml(countLabel(key))}</span><strong>${escapeHtml(value)}</strong></div>`)
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
    if (currentTaskId !== taskId) return;
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
    if (currentTaskId !== taskId) return;
    setStatus(itemsStatus, `读取失败：${error.message}`, true);
  }
}

function clearDetail(taskId) {
  document.title = `${taskId} · 采集任务`;
  document.querySelector("#detail-title").textContent = taskId;
  document.querySelector("#detail-meta").innerHTML = "";
  document.querySelector("#detail-counts").innerHTML = "";
  document.querySelector("#detail-quality").innerHTML = "";
  document.querySelector("#detail-controls").innerHTML = "";
  document.querySelector("#export-link").href = "#";
  document.querySelector("#export-link").hidden = true;
  itemRows.innerHTML = "";
  setStatus(itemsStatus, "");
}

async function loadDetail(taskId) {
  const changed = taskId !== currentTaskId;
  if (changed) {
    lastDetailLoadedAt = null;
    clearDetail(taskId);
  }
  currentTaskId = taskId;
  if (changed) {
    setStatus(detailStatus, "加载中…");
  }
  try {
    const task = await api(`/api/tasks/${encodeURIComponent(taskId)}`);
    if (currentTaskId !== taskId) return;
    lastDetailLoadedAt = new Date();
    renderDetail(task);
    setStatus(detailStatus, "");
    await loadItems(taskId, currentKind);
  } catch (error) {
    if (currentTaskId !== taskId) return;
    setStatus(
      detailStatus,
      `读取失败：${error.message}（最后可信时间：${trustedTime(lastDetailLoadedAt)}）`,
      true,
    );
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
