const base = {
  siteKey: "www.bennytex.fr",
  batch: "Bennytex 全量 2026-11-23 v2",
  batchId: "b-5ad551c1778f",
  url: "https://www.bennytex.fr/",
  note: "候选方案：bennytex-fr-build@2026.11.24-3，有界验证 6 条有效、0 失败；待人工激活",
  rule: "bennytex-fr-build@2026.11.23-2",
  rulePath: "rules/bennytex-fr-build.yaml",
  updated: "2026-11-24 10:21",
  market: "FR / FR",
  language: "fr-FR",
  category: "tissus",
};

const products = [
  {
    name: "popeline coton 120 fils tara jannon luxe bleu indigo",
    price: "11,92 EUR",
    meta: "Tissus · coton",
  },
  {
    name: "popeline coton 120 fils tara jannon jaune et bleu marine",
    price: "11,92 EUR",
    meta: "Tissus · coton",
  },
  {
    name: "Coton froissé élasthanne motif tartan violet fuchsia orange texturé",
    price: "2,50 EUR",
    meta: "Tissus · coton",
  },
  {
    name: "Velours milleraies côtelé framboise",
    price: "14,90 EUR",
    meta: "Tissus · velours",
  },
  {
    name: "Lin lavé naturel écru",
    price: "18,40 EUR",
    meta: "Tissus · lin",
  },
  {
    name: "Sergé de coton bio kaki",
    price: "9,80 EUR",
    meta: "Tissus · coton",
  },
];

const history = [
  { id: "web-687a85f9f897", state: "已结束", outcome: "完成", count: "20 有效", time: "2026-11-24 10:21", tone: "success" },
  { id: "web-5a6ef774c604", state: "已取消", outcome: "已取消", count: "3 有效", time: "2026-11-23 18:02", tone: "warning" },
  { id: "web-7c6d0dde7646", state: "已结束", outcome: "部分完成", count: "18 有效／2 失败", time: "2026-11-22 16:40", tone: "warning" },
  { id: "web-2d38ec48c34e", state: "已结束", outcome: "完成", count: "20 有效", time: "2026-11-21 11:18", tone: "success" },
];

const qualityPartial = [
  {
    product: "Coton froissé élasthanne motif tartan",
    issue: "描述正文只有成分，缺少规格块",
    source: "https://www.bennytex.fr/p/coton-froisse",
  },
  {
    product: "Velours milleraies côtelé framboise",
    issue: "描述正文为空，已标记为不完整",
    source: "https://www.bennytex.fr/p/velours-milleraies",
  },
];

const states = {
  done: {
    label: "已结束 · 结果可用",
    readiness: "可采",
    taskBadge: "已结束",
    buildBadge: null,
    statusLine: "任务已结束 · COMPLETED",
    task: {
      id: "web-687a85f9f897",
      state: "已结束",
      outcome: "完成",
      stop: "自然结束",
      coverage: "部分",
      denominator: "20 / 20",
      quality: 0,
      valid: 20,
      failed: 0,
      excluded: 0,
      fresh: false,
    },
    build: null,
    primary: { label: "导出当前任务 ZIP", kind: "export" },
    mode: "results",
    quality: [],
    notice: null,
    approvals: false,
    buildAvailable: true,
  },
  running: {
    label: "执行中 · 部分结果",
    readiness: "可采",
    taskBadge: "运行中",
    buildBadge: null,
    statusLine: "采集运行中 · 结果会继续追加",
    task: {
      id: "web-45b756614eb6",
      state: "运行中",
      outcome: null,
      stop: "尚未结束",
      coverage: "部分",
      denominator: "20 / 20",
      quality: 0,
      valid: 6,
      failed: 0,
      excluded: 0,
      fresh: true,
    },
    build: null,
    primary: { label: "暂停任务", kind: "pause" },
    mode: "results",
    quality: [],
    notice: null,
    approvals: false,
    buildAvailable: true,
  },
  approval: {
    label: "构建等待审批",
    readiness: "可采",
    taskBadge: "已结束",
    buildBadge: "运行中",
    statusLine: "规则修复中 · 构建会话等待人工确认",
    task: {
      id: "web-687a85f9f897",
      state: "已结束",
      outcome: "完成",
      stop: "自然结束",
      coverage: "部分",
      denominator: "20 / 20",
      quality: 0,
      valid: 20,
      failed: 0,
      excluded: 0,
      fresh: false,
    },
    build: {
      id: "build-1ad1cbb7cf32",
      state: "运行中",
      outcome: null,
      mode: "修复规则",
      model: "opencode-go/deepseek-v4.1-flash",
      elapsed: "128 秒",
      note: "规则修复构建正在进行；批准后继续同一会话，不会重新创建任务。",
    },
    primary: { label: "暂停构建", kind: "pause-build" },
    mode: "results",
    quality: [],
    notice: null,
    approvals: true,
    buildAvailable: true,
  },
  partial: {
    label: "部分完成 · 待修复",
    readiness: "可采",
    taskBadge: "已结束",
    buildBadge: null,
    statusLine: "任务未完整完成 · 先看质量异常",
    task: {
      id: "web-7c6d0dde7646",
      state: "已结束",
      outcome: "部分完成",
      stop: "达到失败上限",
      coverage: "部分",
      denominator: "20 / 20",
      quality: 2,
      valid: 18,
      failed: 2,
      excluded: 0,
      fresh: false,
    },
    build: null,
    primary: { label: "修复规则", kind: "repair" },
    mode: "results",
    quality: qualityPartial,
    notice: null,
    approvals: false,
    buildAvailable: true,
  },
  onboarding: {
    label: "待接入 · 构建可用",
    readiness: "待接入",
    taskBadge: null,
    buildBadge: null,
    statusLine: "待接入 · 需要规则包",
    task: null,
    build: null,
    primary: { label: "启动构建", kind: "build" },
    mode: "build",
    quality: [],
    notice: null,
    approvals: false,
    buildAvailable: true,
  },
  readonly: {
    label: "待接入 · 只读阻断",
    readiness: "待接入",
    taskBadge: null,
    buildBadge: null,
    statusLine: "待接入 · 构建入口已关闭",
    task: null,
    build: null,
    primary: { label: "启动构建", kind: "build", disabled: true },
    mode: "build",
    quality: [],
    notice:
      "只读预览已关闭构建入口，启动构建和修复规则不可用。切换到可写服务后再发起构建。",
    approvals: false,
    buildAvailable: false,
  },
};

const viewLabels = {
  current: "当前采集",
  history: "任务历史",
  rules: "规则与构建",
  info: "站点资料",
};

const icon = {
  download: "↓",
  export: "↓",
  more: "⋯",
  refresh: "↻",
  back: "←",
  play: "▶",
  pause: "Ⅱ",
  "pause-build": "Ⅱ",
  build: "⌁",
  repair: "⌁",
  wrench: "⌁",
  shield: "!",
  arrow: "→",
};

const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        char
      ],
  );

const view = document.querySelector("#view");
const toast = document.querySelector("#toast");
const sidebar = document.querySelector("#sidebar");
const navBackdrop = document.querySelector("#nav-backdrop");
const menuButton = document.querySelector("#menu-button");

let toastTimer = null;
let menuOpen = false;
let approvalsResolved = false;

function readParams() {
  const raw = location.hash.replace(/^#\/site\??/, "");
  const params = new URLSearchParams(raw);
  const state = states[params.get("state")] ? params.get("state") : "done";
  const view = viewLabels[params.get("view")] ? params.get("view") : "current";
  return { state, view };
}

function writeParams(next) {
  const current = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const params = new URLSearchParams();
  params.set("state", next.state);
  params.set("view", next.view);
  if (current.get("chrome") === "0") params.set("chrome", "0");
  history.replaceState(null, "", `#/site?${params.toString()}`);
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
  const primary = state.primary;
  const classes = "button button-primary";
  if (primary.disabled) {
    return `<button class="${classes}" type="button" data-action="primary" disabled title="${esc(
      state.notice ?? "当前操作不可用",
    )}"><span aria-hidden="true">${icon[primary.kind] ?? icon.play}</span>${esc(
      primary.label,
    )}</button>`;
  }
  return `<button class="${classes}" type="button" data-action="primary"><span aria-hidden="true">${
    icon[primary.kind] ?? icon.play
  }</span>${esc(primary.label)}</button>`;
}

function moreMenu(state) {
  const items = [];
  const task = state.task;
  const primaryKind = state.primary.kind;
  if (task && primaryKind !== "export") {
    items.push(
      `<button type="button" data-action="export"><span aria-hidden="true">${icon.download}</span>导出当前任务 ZIP</button>`,
    );
  }
  if (task && (state.taskBadge === "运行中" || state.taskBadge === "已暂停")) {
    items.push(
      `<button type="button" class="is-danger" data-action="cancel-task"><span aria-hidden="true">⊘</span>取消任务…</button>`,
    );
  }
  if (state.build && primaryKind !== "pause-build") {
    items.push(
      `<button type="button" data-action="cancel-build"><span aria-hidden="true">⊘</span>取消构建…</button>`,
    );
  }
  if (state.build) {
    items.push(
      `<button type="button" data-action="build-detail"><span aria-hidden="true">${icon.wrench}</span>打开构建详情</button>`,
    );
  }
  items.push(
    `<button type="button" data-action="back-batch"><span aria-hidden="true">${icon.back}</span>返回批次详情</button>`,
  );
  return `
    <div class="more-wrap">
      <button class="button" type="button" data-action="more" aria-haspopup="menu" aria-expanded="false">
        <span aria-hidden="true">${icon.more}</span>更多
      </button>
      <div class="menu" data-menu hidden>
        ${items.join("")}
      </div>
    </div>
  `;
}

function renderHeader(state) {
  const badges = [`<span class="badge badge-success">${esc(state.readiness)}</span>`];
  if (state.taskBadge)
    badges.push(`<span class="badge badge-info">${esc(state.taskBadge)}</span>`);
  if (state.buildBadge)
    badges.push(`<span class="badge badge-warning">${esc(state.buildBadge)}</span>`);
  return `
    <header class="page-head">
      <a class="back-link" href="#/site" data-action="back-batch"><span aria-hidden="true">${icon.back}</span>返回 ${esc(
        base.batch,
      )}</a>
      <div class="head-row">
        <div class="head-main">
          <div class="head-title">
            <h1>${esc(base.siteKey)}</h1>
            ${badges.join("")}
          </div>
          <p class="head-url">${esc(base.url)} · ${esc(base.note)}</p>
          <div class="head-meta">
            <span>${esc(state.statusLine)}</span>
            <span>更新 ${esc(base.updated)}</span>
            <span class="mono">${esc(base.rule)}</span>
          </div>
        </div>
        <div class="head-actions">
          ${primaryButton(state)}
          ${moreMenu(state)}
          <button class="button" type="button" data-action="refresh"><span aria-hidden="true">${icon.refresh}</span>刷新</button>
        </div>
      </div>
    </header>
  `;
}

function renderPrototypeBar(state, activeView) {
  const params = new URLSearchParams(location.hash.split("?")[1] ?? "");
  if (params.get("chrome") === "0") return "";
  return `
    <div class="prototype-bar">
      <strong>原型控制</strong>
      <label>页面状态
        <select id="state-select" aria-label="原型页面状态">
          ${Object.entries(states)
            .map(
              ([key, item]) =>
                `<option value="${key}" ${key === state ? "selected" : ""}>${esc(item.label)}</option>`,
            )
            .join("")}
        </select>
      </label>
      <label>视图
        <select id="view-select" aria-label="原型视图">
          ${Object.entries(viewLabels)
            .map(
              ([key, label]) =>
                `<option value="${key}" ${key === activeView ? "selected" : ""}>${esc(label)}</option>`,
            )
            .join("")}
        </select>
      </label>
      <span class="prototype-hint">只切换 mock 状态，不调用后端</span>
    </div>
  `;
}

function renderNotice(state) {
  if (!state.notice) return "";
  return `
    <div class="notice" role="status">
      <span aria-hidden="true">${icon.shield}</span>
      <div>
        <strong>构建服务不可用</strong>
        <span>${esc(state.notice)}</span>
      </div>
    </div>
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
          <p>构建已暂停在需要人工确认的步骤；批准后会继续同一会话。处理结果会写回本次构建记录。</p>
        </div>
      </div>
      <div class="request-list">
        <div class="request">
          <strong>依赖 six</strong>
          <code class="mono">@1.17.0</code>
          <span class="muted">pip · build</span>
          <span class="muted">语言识别库，用于读取页面上的成分表</span>
          <div class="request-actions">
            <button class="button button-sm" type="button" data-action="approve-dependency">批准一次</button>
            <button class="button button-sm button-danger" type="button" data-action="reject-approval">拒绝</button>
          </div>
        </div>
        <div class="request">
          <strong>权限请求</strong>
          <code class="mono">shell</code>
          <span class="muted">npm install</span>
          <div class="request-actions">
            <button class="button button-sm" type="button" data-action="approve-permission">允许一次</button>
            <button class="button button-sm button-danger" type="button" data-action="reject-approval">拒绝</button>
          </div>
        </div>
      </div>
    </section>
  `;
}

function renderSummary(state) {
  const task = state.task;
  return `
    <dl class="summary" aria-label="站点进度">
      <div><dt>任务</dt><dd>${task ? esc(task.state) : "—"}</dd></div>
      <div><dt>有效／失败</dt><dd>${task ? `${task.valid} / ${task.failed}` : "—"}</dd></div>
      <div><dt>覆盖</dt><dd>${task ? `${task.coverage} · ${task.denominator}` : "—"}</dd></div>
      <div><dt>质量异常</dt><dd>${task ? task.quality : 0}</dd></div>
    </dl>
  `;
}

function renderTabs(state, activeView) {
  const counts = {
    current: state.task ? String(state.task.valid) : "",
    history: String(history.length),
    rules: "1",
    info: "",
  };
  return `
    <div class="tabs-row">
      <nav class="tabs" role="tablist" aria-label="站点视图">
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

function renderTaskCard(state) {
  const task = state.task;
  if (!task) return "";
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>当前任务</h2>
          <p>${esc(task.id)} · ${esc(base.rule)}</p>
        </div>
        <button class="button button-sm" type="button" data-action="task-detail">打开任务详情</button>
      </div>
      <dl class="facts task-facts">
        <div class="fact"><dt>停止原因</dt><dd>${esc(task.stop)}</dd></div>
        <div class="fact"><dt>更新</dt><dd>${esc(base.updated)}</dd></div>
        <div class="fact"><dt>排除</dt><dd>${task.excluded}</dd></div>
        <div class="fact"><dt>结果</dt><dd>${task.fresh ? "任务仍在运行，结果会继续追加" : "已生成，可用于导出"}</dd></div>
      </dl>
    </section>
  `;
}

function renderProducts(state) {
  if (!state.task) return "";
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>已采数据预览</h2>
          <p>${state.task.fresh ? "显示最近 6 条有效商品；任务仍在运行，结果会继续追加。" : "显示最近 6 条有效商品；共 20 条有效。"}</p>
        </div>
        <button class="button button-sm" type="button" data-action="refresh-preview"><span aria-hidden="true">${icon.refresh}</span>刷新预览</button>
      </div>
      <div class="panel-body">
        <div class="product-grid">
          ${products
            .map(
              (product, index) => `
                <article class="product">
                  <div class="product-image" role="img" aria-label="商品图片占位 ${index + 1}">image</div>
                  <div class="product-copy">
                    <span class="product-name">${esc(product.name)}</span>
                    <span class="product-meta">${esc(product.meta)}</span>
                    <span class="product-price">${esc(product.price)}</span>
                  </div>
                </article>
              `,
            )
            .join("")}
        </div>
      </div>
    </section>
  `;
}

function renderQuality(state) {
  if (!state.task) return "";
  if (!state.quality.length) {
    return `
      <section class="panel">
        <div class="panel-head">
          <div>
            <h3>质量异常</h3>
            <p>正文不完整或非可选字段缺失；当前为 0 条。</p>
          </div>
          <span class="badge badge-success">0 条</span>
        </div>
      </section>
    `;
  }
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h3>质量异常</h3>
          <p>先看具体商品和原因，再决定修复规则或复跑。</p>
        </div>
        <span class="badge badge-warning">${state.quality.length} 条</span>
      </div>
      <div class="panel-body">
        <ul class="quality-list">
          ${state.quality
            .map(
              (item) => `
                <li class="quality-item">
                  <strong>${esc(item.product)}</strong>
                  <span>${esc(item.issue)}</span>
                  <span class="mono muted">${esc(item.source)}</span>
                </li>
              `,
            )
            .join("")}
        </ul>
      </div>
    </section>
  `;
}

function renderRawData(state) {
  if (!state.task) return "";
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h3>原始数据</h3>
          <p>CSV 预览和任务明细在任务详情中查看，站点页只保留结果与入口，避免两处重复。</p>
        </div>
        <button class="button button-sm" type="button" data-action="task-detail">打开任务详情看 CSV 与明细</button>
      </div>
    </section>
  `;
}

function renderBuildPanel(state) {
  const build = state.build;
  if (!build && !state.buildAvailable && !state.notice) return "";
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>规则构建与修复</h2>
          <p>${
            build
              ? "构建会话与采集任务分开；审批请求固定在首屏，不要求先翻日志。"
              : state.buildAvailable
                ? state.readiness === "可采"
                  ? `当前规则 ${base.rule}。可对已安装规则重新验证并修复描述块、规格和缺失字段；不删除已有采集数据。`
                  : "新站由构建 Agent 生成候选规则；主机完成有界验证后站点才变为可采。"
                : "只读预览或服务未配置构建时，构建入口保持关闭并说明原因。"
          }</p>
        </div>
        ${
          build
            ? `<button class="button button-sm" type="button" data-action="build-detail">构建详情</button>`
            : state.buildAvailable && state.readiness === "可采" && state.primary.kind !== "repair"
              ? `<button class="button button-sm" type="button" data-action="repair">修复规则</button>`
              : ""
        }
      </div>
      ${
        build
          ? `
            <dl class="facts">
              <div class="fact"><dt>构建状态</dt><dd>${esc(build.state)}</dd></div>
              <div class="fact"><dt>模式</dt><dd>${esc(build.mode)}</dd></div>
              <div class="fact"><dt>模型</dt><dd class="mono">${esc(build.model)}</dd></div>
              <div class="fact"><dt>耗时</dt><dd>${esc(build.elapsed)}</dd></div>
            </dl>
            <div class="panel-body">
              <p class="small muted">${esc(build.note)}</p>
            </div>
          `
          : `
            <div class="panel-body">
              <p class="small muted">${
                state.buildAvailable
                  ? "当前没有构建记录。主操作在页头；开始构建会调用模型分析站点并生成规则。"
                  : "当前没有构建记录。构建入口已关闭，页头主操作保持禁用。"
              }</p>
            </div>
          `
      }
    </section>
  `;
}

function renderRules(state) {
  return `
    ${renderBuildPanel(state)}
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>规则版本</h2>
          <p>当前生效、候选和回滚入口；候选证据不足时保留阻断理由。</p>
        </div>
        <button class="button button-sm" type="button" data-action="refresh-rule">刷新</button>
      </div>
      <div class="panel-body rules-grid">
        <div class="rule-card">
          <h3>当前生效 <span class="badge badge-success">已激活</span></h3>
          <p class="mono">${esc(base.rule)}</p>
          <p>过期任务 2 · 未关闭反馈 0</p>
          <div class="rule-actions">
            <button class="button button-sm" type="button" data-action="rollback">回滚上一版本</button>
          </div>
        </div>
        <div class="rule-card is-candidate">
          <h3>候选规则 <span class="badge badge-warning">待激活</span></h3>
          <p class="mono">bennytex-fr-build@2026.11.24-3</p>
          <p>build-1ad1cbb7cf32 · 2026-11-24 10:18</p>
          <div class="evidence">
            <dl>
              <dt>验证状态</dt><dd>证据不完整（INCOMPLETE）</dd>
              <dt>候选冒烟</dt><dd>2 有效 · 0 失败 · GBP 2</dd>
              <dt>同页回归</dt><dd>未执行</dd>
              <dt>字段差异</dt><dd>未记录</dd>
            </dl>
          </div>
          <div class="rule-actions">
            <button class="button button-sm button-primary" type="button" data-action="activate" disabled title="验证证据不完整，不能激活">激活</button>
            <button class="button button-sm" type="button" data-action="reject-rule">放弃</button>
          </div>
          <p class="small muted">验证证据不完整，不能激活；补齐回归后再启用。</p>
        </div>
      </div>
    </section>
  `;
}

function renderHistory() {
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>任务历史</h2>
          <p>最近 4 个任务；旧任务和结果保留，不随复跑删除。</p>
        </div>
        <button class="button button-sm" type="button" data-action="all-tasks">全部任务</button>
      </div>
      <ul class="history-list">
        ${history
          .map(
            (item) => `
              <li class="history-item">
                <span class="task-id">${esc(item.id)}</span>
                <span class="badge badge-${item.tone}">${esc(item.state)}</span>
                <span class="history-meta">${esc(item.outcome)} · ${esc(item.count)} · ${esc(item.time)}</span>
                <button class="button button-sm" type="button" data-action="task-detail">查看</button>
              </li>
            `,
          )
          .join("")}
      </ul>
    </section>
  `;
}

function renderInfo() {
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>站点资料</h2>
          <p>低频事实和技术信息集中在这里，不占当前采集首屏。</p>
        </div>
      </div>
      <div class="panel-body">
        <dl class="info-grid">
          <dt>批次</dt><dd>${esc(base.batch)}</dd>
          <dt>站点 ID</dt><dd class="mono">${esc(base.siteKey)}</dd>
          <dt>国家／市场</dt><dd>${esc(base.market)}</dd>
          <dt>语言</dt><dd>${esc(base.language)}</dd>
          <dt>品类</dt><dd>${esc(base.category)}</dd>
          <dt>规则</dt><dd class="mono">${esc(base.rule)}</dd>
          <dt>规则路径</dt><dd class="mono">${esc(base.rulePath)}</dd>
          <dt>任务 ID</dt><dd class="mono">web-687a85f9f897</dd>
          <dt>构建 ID</dt><dd class="mono">build-1ad1cbb7cf32</dd>
          <dt>创建</dt><dd>2026-11-22 19:12</dd>
          <dt>更新</dt><dd>${esc(base.updated)}</dd>
        </dl>
      </div>
    </section>
  `;
}

function renderCurrent(state) {
  if (state.mode === "build") {
    return `
      ${renderBuildPanel(state)}
      <section class="panel">
        <div class="empty">
          <h3>${state.buildAvailable ? "站点待接入" : "构建入口已关闭"}</h3>
          <p>${
            state.buildAvailable
              ? "没有匹配到受管规则包。使用页头「启动构建」生成候选规则；验证通过后站点自动变为可采。"
              : "当前服务不能发起构建；已采集结果和任务历史仍可查看。请在可写服务或配置构建 Agent 后重试。"
          }</p>
        </div>
      </section>
    `;
  }
  return `
    ${renderTaskCard(state)}
    ${renderProducts(state)}
    ${renderQuality(state)}
    ${renderRawData(state)}
  `;
}

function renderPanel(state, panelView, activeView) {
  const body =
    panelView === "current"
      ? renderCurrent(state)
      : panelView === "history"
        ? renderHistory()
        : panelView === "rules"
          ? renderRules(state)
          : renderInfo();
  return `
    <section id="panel-${panelView}" role="tabpanel" aria-labelledby="tab-${panelView}" tabindex="0" ${
      panelView === activeView ? "" : "hidden"
    }>
      <div class="stack">${body}</div>
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
      ${renderNotice(state)}
      ${renderApprovals(state)}
      ${renderSummary(state)}
      ${renderTabs(state, activeView)}
      ${Object.keys(viewLabels)
        .map((panelView) => renderPanel(state, panelView, activeView))
        .join("")}
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
  } else if (target.id === "view-select") {
    writeParams({ state, view: target.value });
    render();
  }
});

view.addEventListener("click", (event) => {
  const target = event.target.closest("button, a");
  if (!target) {
    if (menuOpen) {
      setMenu(false);
    }
    return;
  }

  const tab = target.closest("[data-view]");
  if (tab) {
    const { state } = readParams();
    writeParams({ state, view: tab.dataset.view });
    render();
    const nextTab = document.querySelector(`[data-view="${tab.dataset.view}"]`);
    nextTab?.focus();
    return;
  }

  if (target.dataset.action === "more") {
    setMenu(!menuOpen);
    return;
  }

  if (target.dataset.action === "approve-dependency" || target.dataset.action === "approve-permission") {
    approvalsResolved = true;
    showToast("原型：审批已受理，构建会继续同一会话。");
    render();
    return;
  }

  if (target.dataset.action === "reject-approval") {
    approvalsResolved = true;
    showToast("原型：请求已拒绝，构建会按拒绝结果继续或结束。");
    render();
    return;
  }

  if (target.dataset.action === "activate") {
    showToast("验证证据不完整，不能激活；补齐同页回归后再启用。");
    return;
  }

  if (target.dataset.action === "primary") {
    const { state } = readParams();
    const primary = states[state].primary;
    showToast(`原型：${primary.label}（未调用后端）。`);
    setMenu(false);
    return;
  }

  if (target.dataset.action === "export") {
    showToast("原型：下载当前任务 ZIP（未调用后端）。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "cancel-task") {
    showToast("原型：取消当前任务需要二次确认。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "cancel-build") {
    showToast("原型：取消构建需要二次确认。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "build-detail") {
    showToast("原型：打开构建详情（未接后端）。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "repair") {
    showToast("原型：修复规则会打开构建对话框，需要真实构建服务。");
    return;
  }

  if (target.dataset.action === "task-detail") {
    showToast("原型：打开任务详情（未接后端）。");
    return;
  }

  if (target.dataset.action === "all-tasks") {
    showToast("原型：打开全部任务（未接后端）。");
    return;
  }

  if (target.dataset.action === "refresh" || target.dataset.action === "refresh-preview" || target.dataset.action === "refresh-rule") {
    showToast("原型：已刷新 mock 数据。");
    return;
  }

  if (target.dataset.action === "rollback" || target.dataset.action === "reject-rule") {
    showToast("原型：规则操作需要真实账本与后端。");
    return;
  }

  if (target.dataset.action === "back-batch" || target.closest("[data-static]")) {
    event.preventDefault();
    showToast("原型：返回批次详情会恢复原清单筛选和位置。");
    if (location.hash.startsWith("#/site")) {
      // Keep the prototype on one page; a production build would navigate to the batch detail.
    }
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
  if (event.target.closest("[data-action='more']") || event.target.closest("[data-menu]")) {
    return;
  }
  setMenu(false);
});

window.addEventListener("hashchange", render);

if (!location.hash.startsWith("#/site")) {
  location.hash = "#/site?state=done&view=current";
}

render();
