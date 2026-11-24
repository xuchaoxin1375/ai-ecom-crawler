const base = {
  taskId: "web-687a85f9f897",
  site: "www.bennytex.fr",
  batchId: "b-5ad551c1778f",
  batch: "Bennytex 全量 2026-11-23 v2",
  plan: "bennytex-fr-build@2026.11.23-2",
  activeRule: "bennytex-fr-build@2026.11.24-4",
  market: "FR",
  updated: "2026-11-24 10:21",
  created: "2026-11-24 10:12",
  started: "2026-11-24 10:12",
  finished: "2026-11-24 10:21",
};

const products = [
  { name: "popeline coton 120 fils tara jannon luxe bleu indigo", price: "11,92 EUR", meta: "Tissus · coton" },
  { name: "popeline coton 120 fils tara jannon jaune et bleu marine", price: "11,92 EUR", meta: "Tissus · coton" },
  { name: "Coton froissé élasthanne motif tartan violet fuchsia orange texturé", price: "2,50 EUR", meta: "Tissus · coton" },
  { name: "Velours milleraies côtelé framboise", price: "14,90 EUR", meta: "Tissus · velours" },
  { name: "Lin lavé naturel écru", price: "18,40 EUR", meta: "Tissus · lin" },
  { name: "Sergé de coton bio kaki", price: "9,80 EUR", meta: "Tissus · coton" },
];

const urls = [
  { url: "https://www.bennytex.fr/3-tissus", state: "已发现", detail: "分类页 · 第 1 页" },
  { url: "https://www.bennytex.fr/3-tissus?page=2", state: "已发现", detail: "分类页 · 第 2 页" },
  { url: "https://www.bennytex.fr/3-tissus?page=3", state: "已发现", detail: "分类页 · 第 3 页" },
  { url: "https://www.bennytex.fr/p/popeline-indigo", state: "已发现", detail: "商品页" },
  { url: "https://www.bennytex.fr/p/popeline-jaune", state: "已发现", detail: "商品页" },
  { url: "https://www.bennytex.fr/p/coton-froisse", state: "已发现", detail: "商品页" },
  { url: "https://www.bennytex.fr/p/velours-framboise", state: "已发现", detail: "商品页" },
  { url: "https://www.bennytex.fr/p/lin-naturel", state: "已发现", detail: "商品页" },
];

const qualityPartial = [
  { product: "Coton froissé élasthanne motif tartan", issue: "描述正文只有成分，缺少规格块" },
  { product: "Velours milleraies côtelé framboise", issue: "描述正文为空，已标记为不完整" },
];

const feedback = [
  {
    category: "字段缺失",
    status: "待分诊",
    note: "描述块只有成分，缺规格",
    time: "2026-11-24 11:02",
    tone: "warning",
  },
  {
    category: "数据范围",
    status: "已解决",
    note: "分类页第 2 页已加入发现范围",
    time: "2026-11-23 18:20",
    tone: "success",
  },
];

const states = {
  "product-done": {
    label: "商品任务 · 完成",
    error: false,
    type: "product",
    state: "已结束",
    outcome: "完成",
    archived: false,
    stale: false,
    stop: "自然结束",
    valid: 20,
    failed: 0,
    excluded: 0,
    coverage: "部分",
    denominator: "20 / 20",
    quality: 0,
    primary: { label: "导出 ZIP", kind: "export" },
    live: false,
  },
  "product-running": {
    label: "商品任务 · 运行中",
    error: false,
    type: "product",
    state: "运行中",
    outcome: null,
    archived: false,
    stale: false,
    stop: "尚未结束",
    valid: 6,
    failed: 0,
    excluded: 0,
    coverage: "部分",
    denominator: "20 / 20",
    quality: 0,
    primary: { label: "暂停任务", kind: "pause" },
    live: true,
  },
  "product-partial": {
    label: "商品任务 · 部分完成",
    error: false,
    type: "product",
    state: "已结束",
    outcome: "部分完成",
    archived: false,
    stale: false,
    stop: "达到失败上限",
    valid: 18,
    failed: 2,
    excluded: 0,
    coverage: "部分",
    denominator: "20 / 20",
    quality: 2,
    primary: { label: "导出 ZIP", kind: "export" },
    live: false,
  },
  "product-empty": {
    label: "商品任务 · 空结果",
    error: false,
    type: "product",
    state: "已结束",
    outcome: "完成",
    archived: false,
    stale: false,
    stop: "自然结束",
    valid: 0,
    failed: 2,
    excluded: 0,
    coverage: "部分",
    denominator: "20 / 20",
    quality: 2,
    primary: { label: "导出 ZIP", kind: "export" },
    live: false,
  },
  "discovery-done": {
    label: "网址任务 · 完成",
    error: false,
    type: "discovery",
    state: "已结束",
    outcome: "完成",
    archived: false,
    stale: false,
    stop: "自然结束",
    valid: 30,
    failed: 0,
    excluded: 0,
    coverage: "部分",
    denominator: "30 / 30",
    quality: 0,
    primary: { label: "导出 ZIP", kind: "export" },
    live: false,
  },
  stale: {
    label: "商品任务 · 旧规则",
    error: false,
    type: "product",
    state: "已结束",
    outcome: "完成",
    archived: false,
    stale: true,
    stop: "自然结束",
    valid: 20,
    failed: 0,
    excluded: 0,
    coverage: "部分",
    denominator: "20 / 20",
    quality: 0,
    primary: { label: "导出 ZIP", kind: "export" },
    live: false,
  },
  "read-error": {
    label: "读取失败",
    error: true,
    type: "product",
    state: "—",
    outcome: null,
    archived: false,
    stale: false,
    stop: null,
    valid: 0,
    failed: 0,
    excluded: 0,
    coverage: "—",
    denominator: "—",
    quality: 0,
    primary: { label: "重试读取", kind: "retry" },
    live: false,
  },
};

const viewLabels = {
  results: "结果",
  quality: "质量与验收",
  data: "数据明细",
  detail: "运行明细",
};

const icon = {
  download: "↓",
  more: "⋯",
  refresh: "↻",
  back: "←",
  play: "▶",
  pause: "Ⅱ",
  export: "↓",
  retry: "↻",
  shield: "!",
  copy: "⧉",
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

function readParams() {
  const raw = location.hash.replace(/^#\/task\??/, "");
  const params = new URLSearchParams(raw);
  const state = states[params.get("state")] ? params.get("state") : "product-done";
  const view = viewLabels[params.get("view")] ? params.get("view") : "results";
  return { state, view };
}

function writeParams(next) {
  const current = new URLSearchParams(location.hash.split("?")[1] ?? "");
  const params = new URLSearchParams();
  params.set("state", next.state);
  params.set("view", next.view);
  if (current.get("chrome") === "0") params.set("chrome", "0");
  history.replaceState(null, "", `#/task?${params.toString()}`);
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
  if (state.primary.kind !== "export") {
    items.push(`<button type="button" data-action="export"><span aria-hidden="true">${icon.download}</span>导出 ZIP</button>`);
  }
  if (state.state === "运行中" || state.state === "已暂停") {
    items.push(`<button type="button" class="is-danger" data-action="cancel"><span aria-hidden="true">⊘</span>取消任务…</button>`);
  }
  items.push(`<button type="button" data-action="copy"><span aria-hidden="true">${icon.copy}</span>复制任务 ID</button>`);
  items.push(`<button type="button" data-action="archive"><span aria-hidden="true">⌁</span>${state.archived ? "恢复任务" : "归档任务"}</button>`);
  items.push(`<button type="button" data-action="site"><span aria-hidden="true">↗</span>打开站点详情</button>`);
  items.push(`<button type="button" data-action="batch"><span aria-hidden="true">↗</span>打开批次详情</button>`);
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
    state.outcome ? `<span class="badge badge-${state.outcome === "完成" ? "success" : "warning"}">${esc(state.outcome)}</span>` : "",
    `<span class="badge">${state.type === "discovery" ? "网址发现" : "商品采集"}</span>`,
    state.archived ? `<span class="badge">已归档</span>` : "",
    state.stale ? `<span class="badge badge-warning">结果基于旧规则</span>` : "",
  ].join("");
  return `
    <header class="page-head">
      <a class="back-link" href="#/task" data-action="back"><span aria-hidden="true">${icon.back}</span>返回全部任务</a>
      <div class="head-row">
        <div class="head-main">
          <div class="head-title">
            <h1>${esc(base.site)}</h1>
            ${badges}
          </div>
          <p class="head-url">${state.stop ? `${esc(state.stop)} · ` : ""}规则 <span class="mono">${esc(base.plan)}</span></p>
          <div class="head-meta">
            <span>批次 <a class="text-accent" href="#/task" data-action="batch">${esc(base.batch)}</a></span>
            <span>站点 <a class="text-accent" href="#/task" data-action="site">${esc(base.site)}</a></span>
            <span>更新 ${esc(base.updated)}</span>
            <span>${state.live ? "实时更新" : "已结束，结果不再追加"}</span>
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

function renderSummary(state) {
  const label = state.type === "discovery" ? "发现网址" : "有效商品";
  return `
    <dl class="summary" aria-label="任务概览">
      <div><dt>${label}</dt><dd>${state.valid}</dd></div>
      <div><dt>失败／排除</dt><dd>${state.failed} / ${state.excluded}</dd></div>
      <div><dt>覆盖</dt><dd>${esc(state.coverage)}</dd></div>
      <div><dt>质量异常</dt><dd>${state.quality}</dd></div>
    </dl>
  `;
}

function renderTabs(state, activeView) {
  const counts = {
    results: String(state.valid),
    quality: state.quality || feedback.filter((item) => item.status !== "已解决").length ? String(state.quality + feedback.filter((item) => item.status !== "已解决").length) : "",
    data: state.type === "discovery" ? String(urls.length) : String(state.valid + state.failed),
    detail: "",
  };
  return `
    <div class="tabs-row">
      <label class="sr-only" for="task-view-select">切换任务视图</label>
      <select class="view-select-mobile" id="task-view-select">
        ${Object.entries(viewLabels)
          .map(([key, label]) => `<option value="${key}" ${key === activeView ? "selected" : ""}>${esc(label)}${counts[key] ? `（${counts[key]}）` : ""}</option>`)
          .join("")}
      </select>
      <nav class="tabs" role="tablist" aria-label="任务视图">
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

function renderStale(state) {
  if (!state.stale) return "";
  return `
    <div class="notice" role="status">
      <span aria-hidden="true">${icon.shield}</span>
      <div>
        <strong>结果基于旧规则</strong>
        <span>站点当前规则已到 ${esc(base.activeRule)}，当前结果仍基于 ${esc(base.plan)}；需要复跑后再判断新规则是否改善。</span>
      </div>
    </div>
  `;
}

function renderQualitySummary(state) {
  if (state.type !== "product") return "";
  return `
    <div class="panel-body quality-summary">
      <div>
        <strong>质量异常 ${state.quality} 条</strong>
        <p class="small muted">正文不完整或非可选字段缺失；先看具体商品和原因，再决定修复规则或复跑。</p>
      </div>
      <button class="button button-sm" type="button" data-view-link="quality">查看质量与验收</button>
    </div>
  `;
}

function renderProductPreview(state) {
  if (state.type !== "product") return "";
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>已采商品预览</h2>
          <p>${state.live ? "显示最近 6 条有效商品；任务仍在运行，结果会继续追加。" : "显示最近 6 条有效商品；共 " + state.valid + " 条有效。"}</p>
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

function renderUrlList(state) {
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>发现网址</h2>
          <p>${state.live ? "显示最近网址；任务仍在运行，结果会继续追加。" : `共发现 ${state.valid} 个网址；网址发现任务不产生商品 CSV。`}</p>
        </div>
        <button class="button button-sm" type="button" data-action="refresh-preview"><span aria-hidden="true">${icon.refresh}</span>刷新</button>
      </div>
      <ul class="url-list">
        ${urls
          .map(
            (item) => `
              <li class="url-item">
                <code>${esc(item.url)}</code>
                <span class="muted">${esc(item.detail)}</span>
                <span class="badge badge-success">${esc(item.state)}</span>
              </li>
            `,
          )
          .join("")}
      </ul>
    </section>
  `;
}

function renderDataEntry(state) {
  return `
    <section class="panel panel-body">
      <div class="quality-summary">
        <div>
          <strong>需要全部数据？</strong>
          <p class="small muted">CSV 预览和全部商品／网址明细在「数据明细」中；结果视图只保留预览。</p>
        </div>
        <button class="button button-sm" type="button" data-view-link="data">查看数据明细</button>
      </div>
    </section>
  `;
}

function renderResults(state) {
  if (state.error) {
    return `
      <section class="panel error-state">
        <h2>读取任务失败</h2>
        <p>任务不存在或服务暂时不可用；重试不会修改任务和结果。</p>
        <button class="button button-sm" type="button" data-action="retry">重试读取</button>
      </section>
    `;
  }
  if (state.type === "discovery") {
    return `${renderUrlList(state)}${renderDataEntry(state)}`;
  }
  if (!state.valid) {
    return `
      <section class="panel">
        <div class="empty-result">
          <h3>本次没有有效商品</h3>
          <p>先看质量异常和全部明细，确认是范围、访问还是规则问题；导出仍会包含失败记录。</p>
          <div class="feedback-actions">
            <button class="button button-sm" type="button" data-view-link="quality">查看质量与验收</button>
            <button class="button button-sm" type="button" data-view-link="data">查看数据明细</button>
          </div>
        </div>
      </section>
    `;
  }
  return `
    ${renderProductPreview(state)}
    <section class="panel">
      ${renderQualitySummary(state)}
    </section>
    ${renderDataEntry(state)}
  `;
}

function renderQuality(state) {
  const exceptions = state.type === "product" ? (state.quality ? qualityPartial : []) : [];
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>结果验收</h2>
          <p>记录分类、样本和期望；反馈分诊后再决定规则修复、运行复跑或业务处理。</p>
        </div>
      </div>
      <div class="panel-body feedback-grid">
        <div class="feedback-card">
          <h3>记录本次结果</h3>
          <p>验收对象是当前任务结果，不改变已采数据和规则版本。</p>
          <div class="feedback-form">
            <label>分类
              <select>
                <option>字段缺失</option>
                <option>数据范围</option>
                <option>访问与运行</option>
                <option>业务期望</option>
              </select>
            </label>
            <label>样本 URL
              <textarea placeholder="每行一个样本 URL；规则修复会使用这些页面。"></textarea>
            </label>
            <div class="feedback-actions">
              <button class="button button-sm button-primary" type="button" data-action="feedback">记录结果验收</button>
              <span class="small muted">原型不会提交。</span>
            </div>
          </div>
        </div>
        <div>
          <h3 class="panel-head-h3">反馈记录</h3>
          <div class="feedback-grid">
            ${feedback
              .map(
                (item) => `
                  <div class="feedback-entry">
                    <strong>${esc(item.category)}</strong>
                    <span>${esc(item.note)}</span>
                    <span class="muted">${esc(item.time)}</span>
                    <span class="badge badge-${item.tone}">${esc(item.status)}</span>
                  </div>
                `,
              )
              .join("")}
          </div>
        </div>
      </div>
    </section>
    ${
      state.type === "product"
        ? `
          <section class="panel">
            <div class="panel-head">
              <div>
                <h2>质量异常</h2>
                <p>${state.quality ? "先看具体商品和原因，再决定修复规则或复跑。" : "当前没有质量异常；正文不完整或非可选字段缺失时会出现在这里。"}</p>
              </div>
              <span class="badge badge-${state.quality ? "warning" : "success"}">${state.quality} 条</span>
            </div>
            ${
              exceptions.length
                ? `<div class="panel-body"><ul class="quality-list">${exceptions
                    .map(
                      (item) => `
                        <li class="quality-item">
                          <strong>${esc(item.product)}</strong>
                          <span>${esc(item.issue)}</span>
                        </li>
                      `,
                    )
                    .join("")}</ul></div>`
                : ""
            }
          </section>
        `
        : `<section class="panel panel-body"><p class="small muted">网址发现任务不产生商品质量异常；如果发现问题，请在结果验收中记录访问或范围问题。</p></section>`
    }
  `;
}

function renderData(state) {
  if (state.type === "discovery") {
    return `${renderUrlList(state)}<section class="panel panel-body"><p class="small muted">网址发现任务不产生商品 CSV；全部网址已在上方列出。</p></section>`;
  }
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>CSV 预览</h2>
          <p>与导出使用同一快照；任务运行中为部分结果。</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="data-table-wrap">
          <table>
            <thead>
              <tr><th>来源 URL</th><th>商品名称</th><th>价格</th><th>币种</th><th>描述</th></tr>
            </thead>
            <tbody>
              ${products
                .map(
                  (product, index) => `
                    <tr>
                      <td class="mono">/p/fixture-${index + 1}</td>
                      <td>${esc(product.name)}</td>
                      <td>${esc(product.price.replace(" EUR", ""))}</td>
                      <td>EUR</td>
                      <td>完整</td>
                    </tr>
                  `,
                )
                .join("")}
            </tbody>
          </table>
        </div>
      </div>
    </section>
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>全部商品明细</h2>
          <p>共 ${state.valid + state.failed} 条处理记录；失败和排除不混入有效商品。</p>
        </div>
      </div>
      <div class="data-table-wrap">
        <table>
          <thead><tr><th>状态</th><th>来源 URL</th><th>名称</th><th>尝试</th><th>更新</th></tr></thead>
          <tbody>
            ${products
              .map(
                (product, index) => `
                  <tr>
                    <td><span class="badge badge-success">有效</span></td>
                    <td class="mono">/p/fixture-${index + 1}</td>
                    <td>${esc(product.name)}</td>
                    <td>1</td>
                    <td>${esc(base.updated)}</td>
                  </tr>
                `,
              )
              .join("")}
          </tbody>
        </table>
      </div>
    </section>
  `;
}

function renderDetail(state) {
  return `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>任务事实</h2>
          <p>状态、规则、站点和批次；低频技术信息不占结果首屏。</p>
        </div>
      </div>
      <div class="panel-body">
        <dl class="info-grid">
          <dt>任务 ID</dt><dd class="mono">${esc(base.taskId)}</dd>
          <dt>类型</dt><dd>${state.type === "discovery" ? "网址发现" : "商品采集"}</dd>
          <dt>结果规则</dt><dd class="mono">${esc(base.plan)}</dd>
          <dt>站点当前规则</dt><dd class="mono">${esc(base.activeRule)}${state.stale ? "（新于结果）" : "（与结果一致）"}</dd>
          <dt>市场</dt><dd>${esc(base.market)}</dd>
          <dt>站点</dt><dd>${esc(base.site)}</dd>
          <dt>批次</dt><dd>${esc(base.batch)}</dd>
          <dt>停止原因</dt><dd>${esc(state.stop ?? "—")}</dd>
          <dt>创建</dt><dd>${esc(base.created)}</dd>
          <dt>开始</dt><dd>${esc(base.started)}</dd>
          <dt>结束</dt><dd>${esc(base.finished)}</dd>
          <dt>更新</dt><dd>${esc(base.updated)}</dd>
        </dl>
      </div>
    </section>
    ${
      state.type === "product"
        ? `
          <section class="panel">
            <div class="panel-head">
              <div>
                <h2>内容完整度</h2>
                <p>主机按样本检查描述缺口；品牌等可空字段不计入质量异常。</p>
              </div>
            </div>
            <div class="panel-body">
              <dl class="info-grid">
                <dt>检查商品</dt><dd>20</dd>
                <dt>描述缺口</dt><dd>${state.quality}</dd>
              </dl>
            </div>
          </section>
        `
        : ""
    }
  `;
}

function renderPanel(state, panelView, activeView) {
  const content =
    panelView === "results"
      ? renderResults(state)
      : panelView === "quality"
        ? renderQuality(state)
        : panelView === "data"
          ? renderData(state)
          : renderDetail(state);
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
      ${renderStale(state)}
      ${state.error ? "" : renderSummary(state)}
      ${state.error ? "" : renderTabs(state, activeView)}
      ${
        state.error
          ? renderResults(state)
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
    writeParams({ state: target.value, view: activeView });
    render();
  } else if (target.id === "view-select" || target.id === "task-view-select") {
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

  const viewLink = target.closest("[data-view-link]");
  if (viewLink) {
    const { state } = readParams();
    writeParams({ state, view: viewLink.dataset.viewLink });
    render();
    return;
  }

  if (target.dataset.action === "more") {
    setMenu(!menuOpen);
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

  if (target.dataset.action === "cancel") {
    showToast("原型：取消任务需要二次确认。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "copy") {
    showToast("原型：任务 ID 已复制。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "archive") {
    showToast("原型：归档／恢复任务需要真实账本。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "site" || target.dataset.action === "batch") {
    event.preventDefault();
    showToast("原型：打开关联对象（未接后端）。");
    setMenu(false);
    return;
  }

  if (target.dataset.action === "refresh" || target.dataset.action === "refresh-preview") {
    showToast("原型：已刷新 mock 数据。");
    return;
  }

  if (target.dataset.action === "feedback") {
    showToast("原型：结果验收已记录（未调用后端）。");
    return;
  }

  if (target.dataset.action === "retry") {
    showToast("原型：重试读取（未调用后端）。");
    return;
  }

  if (target.dataset.action === "back" || target.closest("[data-static]")) {
    event.preventDefault();
    showToast("原型：返回全部任务（未接后端）。");
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

if (!location.hash.startsWith("#/task")) {
  location.hash = "#/task?state=product-done&view=results";
}

render();
