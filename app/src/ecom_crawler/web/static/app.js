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
let lastItemsLoadedAt = null;
let pendingControl = null;

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

const STATE_LABELS = {
  DRAFT: "草稿",
  QUEUED: "排队中",
  RUNNING: "运行中",
  PAUSING: "暂停中",
  PAUSED: "已暂停",
  CANCELLING: "取消中",
  CANCELLED: "已取消",
  FINISHED: "已结束",
  DONE: "完成",
  FAILED: "失败",
  IN_FLIGHT: "处理中",
  PENDING: "待处理",
  EXCLUDED: "已排除",
};

const OUTCOME_LABELS = {
  COMPLETED: "完成",
  PARTIAL: "部分完成",
  FAILED: "失败",
  CANCELLED: "已取消",
};

const STOP_REASON_LABELS = {
  NATURAL_END: "自然结束",
  BUDGET_EXHAUSTED: "预算耗尽",
  ACCESS_DENIED: "访问被拒",
  QUALITY_BLOCKED: "质量阻塞",
  ENVIRONMENT_ERROR: "环境错误",
  PLAN_ERROR: "方案错误",
  USER_CANCELLED: "用户取消",
  OTHER: "其他",
};

const TASK_TYPE_LABELS = {
  product: "商品",
  discovery: "发现",
};

const COVERAGE_LABELS = {
  KNOWN: "已知",
  PARTIAL: "部分",
  UNKNOWN: "未知",
};

function labelFor(labels, value) {
  return labels[value] || value || "-";
}

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

function updateRuleContext() {
  const select = document.querySelector("#rule-select");
  const target = document.querySelector("#rule-context");
  const key = select.value;
  const rule = rulesCache.find(
    (item) => `${item.rule_id}@${item.rule_version}` === key,
  );
  target.textContent = rule
    ? `市场 ${rule.market || "-"} · 语言 ${rule.locale || "-"}`
    : "";
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
    updateRuleContext();
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
      const typeLabel = labelFor(TASK_TYPE_LABELS, task.task_type);
      const stateText = labelFor(STATE_LABELS, task.state);
      const outcomeText = task.outcome ? labelFor(OUTCOME_LABELS, task.outcome) : "-";
      const stopText = task.stop_reason ? labelFor(STOP_REASON_LABELS, task.stop_reason) : "";
      return `
        <tr>
          <td class="col-task">
            <a href="${href}">${escapeHtml(task.task_id)}</a>${archived}
            <div class="mobile-meta muted">${escapeHtml(typeLabel)} · ${escapeHtml(task.market || "-")}</div>
            <div class="mobile-meta muted">${escapeHtml(countsText(task.counts))}</div>
          </td>
          <td class="col-type" title="${escapeHtml(task.task_type)}">${escapeHtml(typeLabel)}</td>
          <td class="col-site">
            <div>${escapeHtml(task.site_key || "-")}</div>
            <div class="muted">${escapeHtml(task.plan_id)}@${escapeHtml(task.plan_version)}</div>
          </td>
          <td class="col-market">${escapeHtml(task.market || "-")}</td>
          <td class="col-state"><span class="${stateClass(task.state)}" title="${escapeHtml(task.state)}">${escapeHtml(stateText)}</span></td>
          <td class="col-result">${escapeHtml(outcomeText)}${stopText ? `<div class="muted" title="${escapeHtml(task.stop_reason)}">${escapeHtml(stopText)}</div>` : ""}</td>
          <td class="counts-cell col-counts">${escapeHtml(countsText(task.counts))}</td>
          <td class="col-updated">${escapeHtml(task.updated_at || "-")}</td>
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

function controlStatusText(task) {
  if (!pendingControl) return "";
  const action = pendingControl.action;
  const label = actionLabel(action);
  const stateText = labelFor(STATE_LABELS, task.state);
  const settled = {
    pause: ["PAUSED"],
    cancel: ["CANCELLED"],
    archive: ["FINISHED", "CANCELLED"],
    restore: ["FINISHED", "CANCELLED"],
  }[action] || [];
  if (settled.includes(task.state)) {
    return `${label}已完成；当前 ${stateText}。`;
  }
  return `已受理：${label}；当前 ${stateText}；等待后台确认。`;
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
    pendingControl = { action, state: payload.state };
    setStatus(
      detailStatus,
      `已受理：${actionLabel(action)}，当前 ${labelFor(STATE_LABELS, payload.state)}；最终状态以任务账本为准。`,
    );
    setTimeout(() => {
      if (currentTaskId) loadDetail(currentTaskId);
    }, 500);
  } catch (error) {
    pendingControl = null;
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
  const stop = task.stop_reason;
  const outcome = task.outcome;
  const stateText = labelFor(STATE_LABELS, task.state);
  const outcomeText = outcome ? labelFor(OUTCOME_LABELS, outcome) : "-";
  const stopText = stop ? labelFor(STOP_REASON_LABELS, stop) : "-";
  const typeText = labelFor(TASK_TYPE_LABELS, task.task_type);
  const qualityCount = Array.isArray(task.quality_exceptions) ? task.quality_exceptions.length : 0;
  document.querySelector("#detail-meta").innerHTML = `
    <div><span class="label">状态</span><span class="${stateClass(task.state)}" title="${escapeHtml(task.state)}">${escapeHtml(stateText)}</span></div>
    <div><span class="label">结果</span><span title="${escapeHtml(outcome || "")}">${escapeHtml(outcomeText)}</span></div>
    <div><span class="label">停止原因</span><span title="${escapeHtml(stop || "")}">${escapeHtml(stopText)}</span></div>
    <div><span class="label">站点</span>${escapeHtml(task.site_key || "-")}</div>
    <div><span class="label">市场</span>${escapeHtml(task.market || "-")}</div>
    <div><span class="label">方案</span>${escapeHtml(task.plan_id)}@${escapeHtml(task.plan_version)}</div>
    <div><span class="label">类型</span><span title="${escapeHtml(task.task_type)}">${escapeHtml(typeText)}</span></div>
    <div><span class="label">覆盖</span><span title="${escapeHtml(coverage)}">${escapeHtml(labelFor(COVERAGE_LABELS, coverage))}</span></div>
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
  if (kind !== currentKind) {
    lastItemsLoadedAt = null;
  }
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
    lastItemsLoadedAt = new Date();
    if (!payload.items?.length) {
      itemRows.innerHTML = '<tr><td colspan="4" class="empty">暂无记录</td></tr>';
    } else {
      itemRows.innerHTML = payload.items
        .map(
          (item) => `
          <tr>
            <td class="url">${escapeHtml(item.url)}</td>
            <td><span class="${stateClass(item.state)}" title="${escapeHtml(item.state)}">${escapeHtml(labelFor(STATE_LABELS, item.state))}</span></td>
            <td>${escapeHtml(item.failure_class || "-")}</td>
            <td>${escapeHtml(item.attempts ?? 0)}</td>
          </tr>`,
        )
        .join("");
    }
    setStatus(itemsStatus, `共 ${payload.total ?? 0} 条`);
  } catch (error) {
    if (currentTaskId !== taskId) return;
    setStatus(
      itemsStatus,
      `读取失败：${error.message}（最后可信时间：${trustedTime(lastItemsLoadedAt)}）`,
      true,
    );
  }
}

function clearDetail(taskId) {
  lastItemsLoadedAt = null;
  pendingControl = null;
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
    setStatus(detailStatus, controlStatusText(task));
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
document.querySelector("#rule-select").addEventListener("change", updateRuleContext);
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
