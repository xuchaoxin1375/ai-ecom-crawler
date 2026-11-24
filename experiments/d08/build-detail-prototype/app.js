const base = {
  buildId: "build-1ad1cbb7cf32",
  site: "www.bennytex.fr",
  batchId: "b-5ad551c1778f",
  batch: "Bennytex 全量 2026-11-23 v2",
  model: "opencode-go/deepseek-v4.1-flash",
  sourceRule: "bennytex-fr-build@2026.11.23-2",
  targetRule: "bennytex-fr-build@2026.11.24-3",
  started: "2026-11-24 10:12",
  updated: "2026-11-24 10:21",
  elapsed: "978 秒",
  workspace: "workbench/builds/build-1ad1cbb7cf32",
  session: "ses_1ad1cbb7",
};

const states = {
  queued: {
    label: "排队中",
    error: false,
    state: "排队",
    outcome: null,
    mode: "规则修复",
    primary: { label: "取消排队", kind: "cancel" },
    live: false,
    queue: "当前已有构建在运行；这个站点排在第 2 位，会在前一个构建结束后自动开始。",
    summary: { repair: "0", elapsed: "—", validation: "未开始" },
    approvals: false,
    continue: false,
    phases: ["等待构建槽位；尚未创建模型会话。"],
    evidence: null,
    repairs: [],
    trace: false,
  },
  running: {
    label: "运行中",
    error: false,
    state: "运行中",
    outcome: null,
    mode: "规则修复",
    primary: { label: "暂停构建", kind: "pause" },
    live: true,
    summary: { repair: "0/1", elapsed: "128 秒", validation: "等待中" },
    approvals: false,
    continue: false,
    phases: [
      "模型正在读取站点样例和现有规则",
      "调用工具 browser_navigate",
      "主机验证尚未开始",
    ],
    evidence: null,
    repairs: [],
    trace: true,
  },
  pending: {
    label: "等待审批",
    error: false,
    state: "运行中",
    outcome: null,
    mode: "规则修复",
    primary: { label: "暂停构建", kind: "pause" },
    live: true,
    summary: { repair: "0/1", elapsed: "128 秒", validation: "等待中" },
    approvals: true,
    continue: false,
    phases: ["模型请求安装依赖 six", "模型请求 shell 权限", "等待人工决定后继续"],
    evidence: null,
    repairs: [],
    trace: true,
  },
  paused: {
    label: "已暂停",
    error: false,
    state: "已暂停",
    outcome: null,
    mode: "规则修复",
    primary: { label: "继续构建", kind: "resume" },
    live: false,
    summary: { repair: "0/1", elapsed: "302 秒", validation: "等待中" },
    approvals: false,
    continue: false,
    phases: ["构建在模型执行阶段暂停", "会话和工作区保留", "继续后从暂停点恢复"],
    evidence: null,
    repairs: [],
    trace: true,
  },
  failed: {
    label: "失败 · 可继续",
    error: false,
    state: "已结束",
    outcome: "失败",
    mode: "规则修复",
    primary: { label: "继续原会话", kind: "continue" },
    live: false,
    summary: { repair: "1/1", elapsed: "459 秒", validation: "失败" },
    approvals: false,
    continue: true,
    phases: ["主机验证失败：价格选择器为空", "自动修复第 1 轮未解决", "会话和工作区仍可继续"],
    evidence: {
      changed: ["description_blocks", "price_selector", "discovery.sources"],
      smoke: "0 有效 · 2 失败",
      regression: "未执行",
    },
    repairs: [
      { round: "1", result: "未解决", error: "价格选择器没有匹配到商品价格", time: "10:18 → 10:20" },
    ],
    trace: true,
  },
  interrupted: {
    label: "中断 · 可继续",
    error: false,
    state: "已结束",
    outcome: "中断",
    mode: "方案构建",
    primary: { label: "继续原会话", kind: "continue" },
    live: false,
    summary: { repair: "0/1", elapsed: "—", validation: "未完成" },
    approvals: false,
    continue: true,
    phases: ["服务重启中断了构建会话", "会话和工作区已保留", "继续会重新加载同一会话"],
    evidence: null,
    repairs: [],
    trace: true,
  },
  succeeded: {
    label: "成功",
    error: false,
    state: "已结束",
    outcome: "成功",
    mode: "规则修复",
    primary: { label: "查看站点", kind: "site" },
    live: false,
    summary: { repair: "1/1", elapsed: "978 秒", validation: "通过" },
    approvals: false,
    continue: false,
    phases: ["模型结束：succeeded", "主机验证通过 6 有效 / 0 失败", "候选规则已安装"],
    evidence: {
      changed: ["description_blocks", "price_selector"],
      smoke: "6 有效 · 0 失败",
      regression: "3 / 3 已执行，无退化",
    },
    repairs: [
      { round: "1", result: "已解决", error: "价格选择器为空", time: "10:12 → 10:14" },
    ],
    trace: true,
  },
  cancelled: {
    label: "已取消",
    error: false,
    state: "已取消",
    outcome: "已取消",
    mode: "方案构建",
    primary: { label: "重新构建", kind: "rebuild" },
    live: false,
    summary: { repair: "0/1", elapsed: "88 秒", validation: "未完成" },
    approvals: false,
    continue: false,
    phases: ["用户取消构建", "站点回到待接入", "旧构建记录和中间文件保留"],
    evidence: null,
    repairs: [],
    trace: false,
  },
  error: {
    label: "读取失败",
    error: true,
    state: "—",
    outcome: null,
    mode: "—",
    primary: { label: "重试读取", kind: "retry" },
    live: false,
    summary: { repair: "—", elapsed: "—", validation: "—" },
    approvals: false,
    continue: false,
    phases: [],
    evidence: null,
    repairs: [],
    trace: false,
  },
};

const viewLabels = {
  status: "运行状态",
  evidence: "验证证据",
  repairs: "修复轮次",
  logs: "日志与 Trace",
};

const icon = {
  back: "←",
  pause: "Ⅱ",
  play: "▶",
  cancel: "⊘",
  continue: "▶",
  site: "↗",
  rebuild: "↻",
  retry: "↻",
  refresh: "↻",
  more: "⋯",
  copy: "⧉",
  download: "↓",
  shield: "!",
};

const esc = (value) =>
  String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);

const view = document.querySelector("#view");
const toast = document.querySelector("#toast");
const sidebar = document.querySelector("#sidebar");
const navBackdrop = document.querySelector("#nav-backdrop");
const menuButton = document.querySelector("#menu-button");

let toastTimer = null;
let menuOpen = false;
let approvalsResolved = false;

function readParams() {
  const raw = location.hash.replace(/^#\/build\??/, "");
  const params = new URLSearchParams(raw);
  const state = states[params.get("state")] ? params.get("state") : "running";
  const view = viewLabels[params.get("view")] ? params.get("view") : "status";
  return { state, view };
}

function writeParams(next) {
  const current = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const params = new URLSearchParams();
  params.set("state", next.state);
  params.set("view", next.view);
  if (current.get("chrome") === "0") params.set("chrome", "0");
  history.replaceState(null, "", `#/build?${params.toString()}`);
}

function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 2600);
}

function setMenu(open) {
  menuOpen = open;
  const menu = document.querySelector("[data-menu]");
  const trigger = document.querySelector("[data-action='more']");
  if (menu) menu.hidden = !open;
  if (trigger) trigger.setAttribute("aria-expanded", String(open));
}

function closeMobileNav() {
  sidebar.classList.remove("is-open");
  navBackdrop.hidden = true;
}

function primaryButton(state) {
  return `<button class="button button-primary" type="button" data-action="primary"><span aria-hidden="true">${
    icon[state.primary.kind] ?? icon.play
  }</span>${esc(state.primary.label)}</button>`;
}

function moreMenu(state) {
  const items = [];
  if (state.continue || state.state === "已取消") {
    items.push(`<button type="button" data-action="rebuild"><span aria-hidden="true">${icon.rebuild}</span>重新构建（新 build）</button>`);
  }
  if (state.live || state.state === "排队") {
    items.push(`<button type="button" class="is-danger" data-action="cancel"><span aria-hidden="true">${icon.cancel}</span>取消构建…</button>`);
  }
  items.push(`<button type="button" data-action="copy"><span aria-hidden="true">${icon.copy}</span>复制构建 ID</button>`);
  items.push(`<button type="button" data-action="trace"><span aria-hidden="true">${icon.download}</span>下载 trace</button>`);
  items.push(`<button type="button" data-action="site"><span aria-hidden="true">${icon.site}</span>打开站点详情</button>`);
  items.push(`<button type="button" data-action="batch"><span aria-hidden="true">${icon.site}</span>打开批次详情</button>`);
  return `
    <div class="more-wrap">
      <button class="button" type="button" data-action="more" aria-haspopup="menu" aria-expanded="false">
        <span aria-hidden="true">${icon.more}</span>更多
      </button>
      <div class="menu" data-menu hidden>${items.join("")}</div>
    </div>
  `;
}

function renderPrototypeBar(stateKey, activeView) {
  const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
  if (params.get("chrome") === "0") return "";
  return `
    <div class="prototype-bar">
      <strong>原型控制</strong>
      <label>页面状态
        <select id="state-select" aria-label="原型页面状态">
          ${Object.entries(states)
            .map(([key, item]) => `<option value="${key}" ${key === stateKey ? "selected" : ""}>${esc(item.label)}</option>`)
            .join("")}
        </select>
      </label>
      <label>视图
        <select id="view-select" aria-label="原型视图">
          ${Object.entries(viewLabels)
            .map(([key, label]) => `<option value="${key}" ${key === activeView ? "selected" : ""}>${esc(label)}</option>`)
            .join("")}
        </select>
      </label>
      <span class="prototype-hint">只切换 mock 状态，不调用后端</span>
    </div>
  `;
}

function renderHeader(state) {
  const badges = [
    `<span class="badge badge-info">${esc(state.state)}</span>`,
    state.outcome ? `<span class="badge badge-${state.outcome === "成功" ? "success" : state.outcome === "已取消" ? "" : "warning"}">${esc(state.outcome)}</span>` : "",
    `<span class="badge">${esc(state.mode)}</span>`,
  ].join("");
  return `
    <header class="page-head">
      <a class="back-link" href="#/build" data-action="back"><span aria-hidden="true">${icon.back}</span>返回构建记录</a>
      <div class="head-row">
        <div class="head-main">
          <div class="head-title">
            <h1>${esc(base.site)}</h1>
            ${badges}
          </div>
          <p class="head-url">${esc(base.model)} · ${esc(base.mode)} · 开始 ${esc(base.started)}</p>
          <div class="head-meta">
            <span>批次 <a class="text-accent" href="#/build" data-action="batch">${esc(base.batch)}</a></span>
            <span>站点 <a class="text-accent" href="#/build" data-action="site">${esc(base.site)}</a></span>
            <span>更新 ${esc(base.updated)}</span>
            <span>${state.live ? "实时更新" : "已结束"}</span>
          </div>
        </div>
        <div class="head-actions">
          ${primaryButton(state)}
          ${state.error ? "" : moreMenu(state)}
          <button class="button" type="button" data-action="refresh"><span aria-hidden="true">${icon.refresh}</span>刷新</button>
        </div>
      </div>
    </header>
  `;
}

function renderApprovals(state) {
  if (!state.approvals || approvalsResolved) return "";
  return `
    <section class="approvals" aria-label="构建等待审批">
      <div class="approvals-head">
        <span aria-hidden="true">${icon.shield}</span>
        <div>
          <h2>构建等待审批</h2>
          <p>构建已暂停在需要人工确认的步骤；批准后会继续同一会话，拒绝会按拒绝结果继续或结束。</p>
        </div>
      </div>
      <div class="request-list">
        <div class="request">
          <strong>依赖 six</strong>
          <code class="mono">@1.17.0</code>
          <span class="muted">pip · build</span>
          <span class="muted">语言识别库，用于读取页面上的成分表</span>
          <div class="request-actions">
            <button class="button button-sm" type="button" data-action="approve">批准一次</button>
            <button class="button button-sm button-danger" type="button" data-action="reject">拒绝</button>
          </div>
        </div>
        <div class="request">
          <strong>权限请求</strong>
          <code class="mono">shell</code>
          <span class="muted">npm install</span>
          <div class="request-actions">
            <button class="button button-sm" type="button" data-action="approve">允许一次</button>
            <button class="button button-sm button-danger" type="button" data-action="reject">拒绝</button>
          </div>
        </div>
      </div>
    </section>
  `;
}

function renderSummary(state) {
  return `
    <dl class="summary" aria-label="构建概览">
      <div><dt>状态</dt><dd>${esc(state.state)}${state.outcome ? ` · ${esc(state.outcome)}` : ""}</dd></div>
      <div><dt>自动修复</dt><dd>${esc(state.summary.repair)}</dd></div>
      <div><dt>耗时</dt><dd>${esc(state.summary.elapsed)}</dd></div>
      <div><dt>验证</dt><dd>${esc(state.summary.validation)}</dd></div>
    </dl>
  `;
}

function renderTabs(state, activeView) {
  const counts = {
    status: "",
    evidence: state.evidence ? "1" : "",
    repairs: state.repairs.length ? String(state.repairs.length) : "",
    logs: state.trace ? "1" : "",
  };
  return `
    <div class="tabs-row">
      <label class="sr-only" for="build-view-select">切换构建视图</label>
      <select class="view-select-mobile" id="build-view-select">
        ${Object.entries(viewLabels)
          .map(([key, label]) => `<option value="${key}" ${key === activeView ? "selected" : ""}>${esc(label)}${counts[key] ? `（${counts[key]}）` : ""}</option>`)
          .join("")}
      </select>
      <nav class="tabs" role="tablist" aria-label="构建视图">
        ${Object.entries(viewLabels)
          .map(
            ([key, label]) => `
              <button class="tab" type="button" role="tab" id="tab-${key}" data-view="${key}"
                aria-selected="${key === activeView}" aria-controls="panel-${key}"
                tabindex="${key === activeView ? "0" : "-1"}">
                ${esc(label)}${counts[key] ? `<span class="count">${counts[key]}</span>` : ""}
              </button>
            `,
          )
          .join("")}
      </nav>
    </div>
  `;
}

function renderBuildFacts() {
  return `
    <dl class="build-facts">
      <div class="build-fact"><dt>模型</dt><dd class="mono">${esc(base.model)}</dd></div>
      <div class="build-fact"><dt>出口</dt><dd>服务默认／直连</dd></div>
      <div class="build-fact"><dt>开始</dt><dd>${esc(base.started)}</dd></div>
      <div class="build-fact"><dt>会话</dt><dd class="mono">${esc(base.session)}</dd></div>
      <div class="build-fact"><dt>来源规则</dt><dd class="mono">${esc(base.sourceRule)}</dd></div>
      <div class="build-fact"><dt>目标规则</dt><dd class="mono">${esc(base.targetRule)}</dd></div>
      <div class="build-fact"><dt>工作区</dt><dd class="mono">${esc(base.workspace)}</dd></div>
      <div class="build-fact"><dt>样例存档</dt><dd>20 页 / 4.2 MB</dd></div>
    </dl>
  `;
}

function renderContinue(state) {
  if (!state.continue) return "";
  return `
    <section class="continue-card" aria-label="继续构建会话">
      <h2>继续原会话</h2>
      <p>沿用当前构建记录、会话和工作区，把补充指令发回同一模型会话；不会产生新的 build。重新构建会回到站点详情发起新构建，旧记录和证据保留。</p>
      <label class="sr-only" for="continue-message">给构建 Agent 的补充指令</label>
      <textarea id="continue-message" placeholder="例如：上次失败在价格选择器，请检查商品页结构并重新生成选择器。"></textarea>
      <div class="continue-actions">
        <button class="button button-sm button-primary" type="button" data-action="continue">发送并继续</button>
        <button class="button button-sm" type="button" data-action="rebuild">重新构建（新 build）</button>
      </div>
    </section>
  `;
}

function renderStatus(state) {
  return `
    ${state.continue ? renderContinue(state) : ""}
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>当前阶段</h2>
          <p>${state.live ? "实时输出在「日志与 Trace」；这里只保留当前阶段和构建事实。" : "构建已结束；验证证据、修复轮次和日志分别在各自视图。"}</p>
        </div>
      </div>
      <div class="panel-body">
        <ul class="phase-list">
          ${state.phases.map((phase) => `<li class="phase-item">${esc(phase)}</li>`).join("")}
        </ul>
      </div>
      ${renderBuildFacts()}
    </section>
    ${state.state === "已结束" && state.outcome === "成功" ? `<div class="success-note">构建完成，候选规则已安装。回到站点详情启动可采站点即可创建采集任务。</div>` : ""}
    ${state.state === "排队" ? `<div class="notice" role="status"><span aria-hidden="true">${icon.shield}</span><div><strong>构建排队中</strong><span>${esc(state.queue)}</span></div></div>` : ""}
  `;
}

function renderEvidence(state) {
  if (state.error) return `<section class="panel error-state"><h2>读取构建失败</h2><p>构建不存在或服务暂时不可用；重试不会修改构建记录。</p><button class="button button-sm" type="button" data-action="retry">重试读取</button></section>`;
  if (!state.evidence) {
    return `<section class="panel panel-body"><p class="small muted">这次构建还没有记录主机验证摘要。旧构建、取消或未进入候选安装的会话不会伪造验证结果。</p></section>`;
  }
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>验证证据</h2>
          <p>主机验证摘要、字段差异和候选冒烟；证据不足时保留阻断理由。</p>
        </div>
      </div>
      <div class="panel-body evidence-grid">
        <div class="evidence-block">
          <h3>主机变更</h3>
          <dl>
            <dt>改动字段</dt><dd>${state.evidence.changed.map(esc).join("、")}</dd>
            <dt>发现策略</dt><dd>未改变</dd>
          </dl>
        </div>
        <div class="evidence-block">
          <h3>候选冒烟</h3>
          <dl>
            <dt>结果</dt><dd>${esc(state.evidence.smoke)}</dd>
            <dt>同页回归</dt><dd>${esc(state.evidence.regression)}</dd>
            <dt>验证结论</dt><dd>${esc(state.summary.validation)}</dd>
          </dl>
        </div>
        <div class="evidence-block">
          <h3>样例存档</h3>
          <dl>
            <dt>页面</dt><dd>20 页</dd>
            <dt>大小</dt><dd>4.2 MB</dd>
            <dt>范围</dt><dd>样例验证</dd>
          </dl>
        </div>
      </div>
    </section>
  `;
}

function renderRepairs(state) {
  if (!state.repairs.length) {
    return `<section class="panel panel-body"><p class="small muted">本次会话没有触发自动修复；主机验证失败后才会出现修复轮次。</p></section>`;
  }
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>自动修复轮次</h2>
          <p>每轮由主机验证失败触发，使用同一构建会话继续；轮次上限由服务配置。</p>
        </div>
      </div>
      <div class="panel-body">
        <ul class="repair-list">
          ${state.repairs
            .map(
              (item) => `
                <li class="repair-item">
                  <strong>第 ${esc(item.round)} 轮</strong>
                  <span class="muted">${esc(item.time)}</span>
                  <span>${esc(item.error)}</span>
                  <span class="badge badge-${item.result === "已解决" ? "success" : "warning"}">${esc(item.result)}</span>
                </li>
              `,
            )
            .join("")}
        </ul>
      </div>
    </section>
  `;
}

function renderLogs(state) {
  const entries = state.error
    ? []
    : [
        { kind: "阶段", text: "模型开始执行", time: "10:12", tone: "info" },
        { kind: "工具", text: "browser_navigate 完成", time: "10:13", tone: "neutral" },
        { kind: "思考", text: "检查商品页价格节点", time: "10:14", tone: "info" },
        { kind: "结束", text: state.outcome ?? "运行中", time: state.live ? "—" : "10:21", tone: state.outcome === "成功" ? "success" : "warning" },
      ];
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>日志与 Trace</h2>
          <p>构建时间线有界滚动；trace 可能包含页面或提示内容，按证据文件管理。</p>
        </div>
        <div class="trace-actions">
          <button class="button button-sm" type="button" data-action="trace">下载构建过程</button>
          <button class="button button-sm" type="button" data-action="trace">trace.json</button>
        </div>
      </div>
      <div class="panel-body">
        <ol class="timeline-list">
          ${entries
            .map(
              (item) => `
                <li class="timeline-item">
                  <strong>${esc(item.kind)}</strong>
                  <span>${esc(item.text)}</span>
                  <span class="muted">${esc(item.time)}</span>
                  <span class="badge badge-${item.tone}">${esc(item.tone)}</span>
                </li>
              `,
            )
            .join("")}
        </ol>
      </div>
    </section>
  `;
}

function renderPanel(state, panelView, activeView) {
  const content =
    panelView === "status"
      ? renderStatus(state)
      : panelView === "evidence"
        ? renderEvidence(state)
        : panelView === "repairs"
          ? renderRepairs(state)
          : renderLogs(state);
  return `
    <section id="panel-${panelView}" role="tabpanel" aria-labelledby="tab-${panelView}" tabindex="0" ${
      panelView === activeView ? "" : "hidden"
    }>
      <div class="stack">${panelView === activeView ? content : ""}</div>
    </section>
  `;
}

function render() {
  const { state: stateKey, view: activeView } = readParams();
  const state = states[stateKey];
  view.innerHTML = `
    ${renderPrototypeBar(stateKey, activeView)}
    <div class="stack">
      ${renderHeader(state)}
      ${state.error ? "" : renderApprovals(state)}
      ${state.error ? "" : renderSummary(state)}
      ${state.error ? "" : renderTabs(state, activeView)}
      ${
        state.error
          ? `<section class="panel error-state"><h2>读取构建失败</h2><p>构建不存在或服务暂时不可用；重试不会修改构建记录。</p><button class="button button-sm" type="button" data-action="retry">重试读取</button></section>`
          : Object.keys(viewLabels)
              .map((panelView) => renderPanel(state, panelView, activeView))
              .join("")
      }
    </div>
  `;
  menuOpen = false;
}

view.addEventListener("change", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLSelectElement)) return;
  const { state, view: activeView } = readParams();
  if (target.id === "state-select") {
    approvalsResolved = false;
    writeParams({ state: target.value, view: activeView });
    render();
  } else if (target.id === "view-select" || target.id === "build-view-select") {
    writeParams({ state, view: target.value });
    render();
  }
});

view.addEventListener("click", (event) => {
  const target = event.target.closest("button, a");
  if (!target) {
    if (menuOpen) setMenu(false);
    return;
  }

  const tab = target.closest("[data-view]");
  if (tab) {
    const { state } = readParams();
    writeParams({ state, view: tab.dataset.view });
    render();
    document.querySelector(`[data-view="${tab.dataset.view}"]`)?.focus();
    return;
  }

  if (target.dataset.action === "more") {
    setMenu(!menuOpen);
    return;
  }

  if (target.dataset.action === "primary") {
    const { state } = readParams();
    const primary = states[state].primary;
    if (primary.kind === "continue") {
      writeParams({ state, view: "status" });
      render();
      document.querySelector("#continue-message")?.focus();
      showToast("原型：已聚焦继续原会话的补充指令。");
      return;
    }
    if (primary.kind === "rebuild") {
      showToast("原型：跳转站点详情发起新 build；旧构建记录保留。");
      return;
    }
    if (primary.kind === "site") {
      showToast("原型：打开站点详情（未接后端）。");
      return;
    }
    showToast(`原型：${primary.label}（未调用后端）。`);
    setMenu(false);
    return;
  }

  if (target.dataset.action === "approve" || target.dataset.action === "reject") {
    approvalsResolved = true;
    showToast(
      target.dataset.action === "approve"
        ? "原型：审批已受理，构建会继续同一会话。"
        : "原型：请求已拒绝，构建会按拒绝结果继续或结束。",
    );
    render();
    return;
  }

  if (target.dataset.action === "continue") {
    showToast("原型：已继续原会话（同一 build）。");
    return;
  }

  if (target.dataset.action === "rebuild") {
    showToast("原型：跳转站点详情发起新 build；旧构建记录保留。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "cancel") {
    showToast("原型：取消构建需要二次确认。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "copy") {
    showToast("原型：构建 ID 已复制。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "trace") {
    showToast("原型：下载构建过程／trace.json（未接后端）。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "site" || target.dataset.action === "batch") {
    event.preventDefault();
    showToast("原型：打开关联对象（未接后端）。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "refresh") {
    showToast("原型：已刷新 mock 数据。");
    return;
  }

  if (target.dataset.action === "retry") {
    showToast("原型：重试读取（未调用后端）。");
    return;
  }

  if (target.dataset.action === "back" || target.closest("[data-static]")) {
    event.preventDefault();
    showToast("原型：返回构建记录（未接后端）。");
    return;
  }

  if (menuOpen) setMenu(false);
});

view.addEventListener("keydown", (event) => {
  const tab = event.target.closest("[role='tab']");
  if (!tab) return;
  const tabs = [...view.querySelectorAll("[role='tab']")];
  const index = tabs.indexOf(tab);
  if (event.key === "ArrowRight" || event.key === "ArrowLeft") {
    event.preventDefault();
    const next = tabs[(index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length];
    next.focus();
    next.click();
  }
  if (event.key === "Home" || event.key === "End") {
    event.preventDefault();
    const target = event.key === "Home" ? tabs[0] : tabs[tabs.length - 1];
    target.focus();
    target.click();
  }
});

menuButton?.addEventListener("click", () => {
  sidebar.classList.toggle("is-open");
  navBackdrop.hidden = !sidebar.classList.contains("is-open");
});

navBackdrop?.addEventListener("click", closeMobileNav);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setMenu(false);
    closeMobileNav();
  }
});

document.addEventListener("click", (event) => {
  if (!menuOpen) return;
  if (event.target.closest("[data-action='more']") || event.target.closest("[data-menu]")) return;
  setMenu(false);
});

window.addEventListener("hashchange", render);

if (!location.hash.startsWith("#/build")) {
  location.hash = "#/build?state=running&view=status";
}

render();
