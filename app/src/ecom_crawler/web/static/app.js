const listView = document.querySelector("#list-view");
const detailView = document.querySelector("#detail-view");
const taskRows = document.querySelector("#task-rows");
const itemRows = document.querySelector("#item-rows");
const listStatus = document.querySelector("#list-status");
const detailStatus = document.querySelector("#detail-status");
const itemsStatus = document.querySelector("#items-status");

let detailTimer = null;
let currentTaskId = null;
let currentKind = "product";

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

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message = payload?.error?.message || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
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

function renderList(tasks) {
  if (!tasks.length) {
    taskRows.innerHTML = '<tr><td colspan="8" class="empty">没有任务</td></tr>';
    return;
  }
  taskRows.innerHTML = tasks
    .map((task) => {
      const href = `#/tasks/${encodeURIComponent(task.task_id)}`;
      const counts = countsText(task.counts);
      return `
        <tr>
          <td><a href="${href}">${escapeHtml(task.task_id)}</a></td>
          <td>${escapeHtml(task.task_type)}</td>
          <td>
            <div>${escapeHtml(task.site_key || "-")}</div>
            <div class="muted">${escapeHtml(task.plan_id)}@${escapeHtml(task.plan_version)}</div>
          </td>
          <td>${escapeHtml(task.market || "-")}</td>
          <td><span class="${stateClass(task.state)}">${escapeHtml(task.state)}</span></td>
          <td>${escapeHtml(task.outcome || "-")}${task.stop_reason ? `<div class="muted">${escapeHtml(task.stop_reason)}</div>` : ""}</td>
          <td class="counts-cell">${escapeHtml(counts)}</td>
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
  if (state) params.set("state", state);
  if (type) params.set("task_type", type);
  try {
    const payload = await api(`/api/tasks?${params.toString()}`);
    renderList(payload.items || []);
    setStatus(listStatus, `共 ${payload.total ?? 0} 个任务`);
  } catch (error) {
    renderList([]);
    setStatus(listStatus, `读取失败：${error.message}`, true);
  }
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
    <div><span class="label">更新时间</span>${escapeHtml(task.updated_at || "-")}</div>
  `;
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

function route() {
  const hash = window.location.hash || "#/tasks";
  const match = hash.match(/^#\/tasks\/([^/]+)$/);
  if (detailTimer) {
    clearInterval(detailTimer);
    detailTimer = null;
  }
  if (match) {
    listView.hidden = true;
    detailView.hidden = false;
    const taskId = decodeURIComponent(match[1]);
    loadDetail(taskId);
    detailTimer = setInterval(() => loadDetail(taskId), 3000);
  } else {
    detailView.hidden = true;
    listView.hidden = false;
    document.title = "采集任务 · 只读预览";
    loadList();
  }
}

document.querySelector("#refresh-list").addEventListener("click", loadList);
document.querySelector("#refresh-detail").addEventListener("click", () => {
  if (currentTaskId) loadDetail(currentTaskId);
});
document.querySelector("#filter-state").addEventListener("change", loadList);
document.querySelector("#filter-type").addEventListener("change", loadList);
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    if (currentTaskId) loadItems(currentTaskId, tab.dataset.kind);
  });
});
window.addEventListener("hashchange", route);
route();
