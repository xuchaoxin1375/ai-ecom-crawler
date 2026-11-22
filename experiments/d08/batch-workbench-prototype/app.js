const view = document.querySelector("#view");
const breadcrumb = document.querySelector("#breadcrumb");
const topbarSub = document.querySelector("#topbar-sub");
const dialog = document.querySelector("#dialog");
const toastEl = document.querySelector("#toast");

const state = {
  batchFilter: "all",
  siteFilter: "all",
  itemTab: "product",
  wizard: null,
};

let lastRouteKey = "";

const SAMPLE_SITES = `https://maison-lin.fr/
https://atelier-laine.fr/
https://nouvelle-boutique.fr/
https://autre-atelier-textile.fr/
https://pas-un-domaine
https://maison-lin.fr/`;

const DEFAULT_COUNTS = {
  valid: 0,
  excluded: 0,
  failed: 0,
  pending: 0,
  inFlight: 0,
  discovered: 0,
};

const RULE_DATA = {
  "maison-lin.fr": { id: "maison-lin-fr", version: "2026.11.18-1", verified: "2026-11-18" },
  "atelier-laine.fr": { id: "atelier-laine-fr", version: "2026.11.20-1", verified: "2026-11-20" },
  "tissus-de-normandie.fr": { id: "tissus-normandie-fr", version: "2026.11.21-1", verified: "2026-11-21" },
  "broderie-moderne.fr": { id: "broderie-moderne-fr", version: "2026.11.17-2", verified: "2026-11-17" },
  "fil-et-aiguille.fr": { id: "fil-aiguille-fr", version: "2026.11.19-1", verified: "2026-11-19" },
  "coton-sauvage.fr": { id: "coton-sauvage-fr", version: "2026.11.16-1", verified: "2026-11-16" },
  "lin-ancien.fr": { id: "lin-ancien-fr", version: "2026.11.21-2", verified: "2026-11-21" },
  "patchwork-nord.fr": { id: "patchwork-nord-fr", version: "2026.11.15-1", verified: "2026-11-15" },
  "mercerie-du-village.fr": { id: "mercerie-village-fr", version: "2026.11.20-2", verified: "2026-11-20" },
  "toile-de-jouy.fr": { id: "toile-jouy-fr", version: "2026.11.22-1", verified: "2026-11-22" },
  "rouen-textile.fr": { id: "rouen-textile-fr", version: "2026.11.19-2", verified: "2026-11-19" },
  "lille-broderie.fr": { id: "lille-broderie-fr", version: "2026.11.18-2", verified: "2026-11-18" },
  "lin-et-soie.fr": { id: "lin-soie-fr", version: "2026.10.28-1", verified: "2026-10-28" },
  "coton-bio.fr": { id: "coton-bio-fr", version: "2026.10.29-1", verified: "2026-10-29" },
  "atelier-tissage.fr": { id: "atelier-tissage-fr", version: "2026.10.30-1", verified: "2026-10-30" },
  "mercerie-rouge.fr": { id: "mercerie-rouge-fr", version: "2026.11.02-1", verified: "2026-11-02" },
  "broderie-ancienne.fr": { id: "broderie-ancienne-fr", version: "2026.11.03-1", verified: "2026-11-03" },
  "toile-lin.fr": { id: "toile-lin-fr", version: "2026.11.04-1", verified: "2026-11-04" },
  "filature-nord.fr": { id: "filature-nord-fr", version: "2026.11.05-1", verified: "2026-11-05" },
  "patchwork-ouest.fr": { id: "patchwork-ouest-fr", version: "2026.11.06-1", verified: "2026-11-06" },
  "maison-coton.fr": { id: "maison-coton-fr", version: "2026.09.12-1", verified: "2026-09-12" },
  "atelier-broderie.fr": { id: "atelier-broderie-fr", version: "2026.09.18-1", verified: "2026-09-18" },
};

const SITE_NAMES = {
  "maison-lin.fr": "Maison Lin",
  "atelier-laine.fr": "Atelier Laine",
  "tissus-de-normandie.fr": "Tissus de Normandie",
  "broderie-moderne.fr": "Broderie Moderne",
  "fil-et-aiguille.fr": "Fil & Aiguille",
  "coton-sauvage.fr": "Coton Sauvage",
  "lin-ancien.fr": "Lin Ancien",
  "patchwork-nord.fr": "Patchwork Nord",
  "mercerie-du-village.fr": "Mercerie du Village",
  "toile-de-jouy.fr": "Toile de Jouy",
  "rouen-textile.fr": "Rouen Textile",
  "lille-broderie.fr": "Lille Broderie",
  "lin-et-soie.fr": "Lin & Soie",
  "coton-bio.fr": "Coton Bio",
  "atelier-tissage.fr": "Atelier Tissage",
  "mercerie-rouge.fr": "Mercerie Rouge",
  "broderie-ancienne.fr": "Broderie Ancienne",
  "toile-lin.fr": "Toile de Lin",
  "filature-nord.fr": "Filature du Nord",
  "patchwork-ouest.fr": "Patchwork Ouest",
  "maison-coton.fr": "Maison Coton",
  "atelier-broderie.fr": "Atelier Broderie",
};

function freshWizard() {
  return {
    step: 1,
    name: "",
    country: "FR",
    language: "fr-FR",
    category: "手工／纺织",
    note: "",
    sitesText: SAMPLE_SITES,
    parsed: null,
  };
}

state.wizard = freshWizard();

function makeSite(domain, name, readiness, taskState, counts, extra = {}) {
  return {
    domain,
    name,
    readiness,
    taskState: taskState || null,
    counts: { ...DEFAULT_COUNTS, ...counts },
    stopReason: extra.stopReason || null,
    coverage: extra.coverage || "UNKNOWN",
    quality: extra.quality || [],
    rule: RULE_DATA[domain] || null,
    taskId: extra.taskId || (taskState ? `web-${domain.replace(/[^a-z0-9]+/g, "")}` : null),
    updated: extra.updated || "2026-11-22 10:12",
    note: extra.note || "",
  };
}

const batches = [
  {
    id: "fr-handmade-2026-11",
    name: "法国手工纺织 2026-11",
    country: "FR",
    market: "FR",
    language: "fr-FR",
    category: "手工／纺织",
    status: "partial",
    createdAt: "2026-11-22 09:10",
    note: "2026 秋冬手工纺织站点，优先法国本土品牌。",
    sites: [
      makeSite("maison-lin.fr", "Maison Lin", "ready", "FINISHED", {
        valid: 24, excluded: 1, discovered: 27,
      }, {
        coverage: "KNOWN",
        stopReason: "NATURAL_END",
        updated: "2026-11-22 10:08",
        quality: [{
          source: "https://maison-lin.fr/products/lin-lave",
          description: "部分",
          reason: "规格区块未合并",
          missing: "品牌",
        }],
      }),
      makeSite("atelier-laine.fr", "Atelier Laine", "ready", "RUNNING", {
        valid: 12, pending: 8, inFlight: 1, discovered: 21,
      }, {
        updated: "2026-11-22 10:21",
      }),
      makeSite("tissus-de-normandie.fr", "Tissus de Normandie", "ready", "RUNNING", {
        valid: 18, pending: 2, inFlight: 1, discovered: 22,
      }, {
        updated: "2026-11-22 10:19",
      }),
      makeSite("broderie-moderne.fr", "Broderie Moderne", "ready", "FINISHED", {
        valid: 31, excluded: 1, discovered: 34,
      }, {
        coverage: "KNOWN",
        stopReason: "NATURAL_END",
        updated: "2026-11-22 09:58",
      }),
      makeSite("fil-et-aiguille.fr", "Fil & Aiguille", "ready", "FINISHED", {
        valid: 16, discovered: 18,
      }, {
        coverage: "KNOWN",
        stopReason: "NATURAL_END",
        updated: "2026-11-22 09:46",
      }),
      makeSite("coton-sauvage.fr", "Coton Sauvage", "ready", "FAILED", {
        valid: 3, failed: 2, pending: 5, discovered: 11,
      }, {
        stopReason: "ACCESS_DENIED",
        updated: "2026-11-22 10:02",
        quality: [{
          source: "https://coton-sauvage.fr/products/lin-ecru",
          description: "部分",
          reason: "商品页返回 403",
          missing: "价格、描述",
        }],
      }),
      makeSite("lin-ancien.fr", "Lin Ancien", "ready", "RUNNING", {
        valid: 8, pending: 4, inFlight: 1, discovered: 13,
      }, {
        updated: "2026-11-22 10:20",
      }),
      makeSite("patchwork-nord.fr", "Patchwork Nord", "ready", "FINISHED", {
        valid: 22, discovered: 24,
      }, {
        coverage: "KNOWN",
        stopReason: "NATURAL_END",
        updated: "2026-11-22 09:51",
      }),
      makeSite("mercerie-du-village.fr", "Mercerie du Village", "ready", "FINISHED", {
        valid: 14, discovered: 15,
      }, {
        coverage: "KNOWN",
        stopReason: "NATURAL_END",
        updated: "2026-11-22 09:42",
      }),
      makeSite("toile-de-jouy.fr", "Toile de Jouy", "ready", "QUEUED", {}, {
        updated: "2026-11-22 10:21",
      }),
      makeSite("atelier-des-fils.fr", "Atelier des Fils", "needs_onboarding", null, {}, {
        note: "未匹配受管规则包",
      }),
      makeSite("maison-textile.fr", "Maison Textile", "needs_onboarding", null, {}, {
        note: "未匹配受管规则包",
      }),
      makeSite("broderie-saint-malo.fr", "Broderie Saint-Malo", "needs_onboarding", null, {}, {
        note: "未匹配受管规则包",
      }),
      makeSite("lin-de-bretagne.fr", "Lin de Bretagne", "needs_onboarding", null, {}, {
        note: "未匹配受管规则包",
      }),
      makeSite("tissage-artisanal.fr", "Tissage Artisanal", "needs_onboarding", null, {}, {
        note: "未匹配受管规则包",
      }),
      makeSite("petit-atelier.fr", "Petit Atelier", "needs_onboarding", null, {}, {
        note: "未匹配受管规则包",
      }),
      makeSite("pas-un-domaine", "pas-un-domaine", "invalid", null, {}, {
        note: "网址不完整",
      }),
      makeSite("maison-lin.com", "Maison Lin（重复）", "invalid", null, {}, {
        note: "与 maison-lin.fr 重复",
      }),
      makeSite("rouen-textile.fr", "Rouen Textile", "ready", "FINISHED", {
        valid: 19, discovered: 20,
      }, {
        coverage: "KNOWN",
        stopReason: "NATURAL_END",
        updated: "2026-11-22 09:39",
      }),
      makeSite("lille-broderie.fr", "Lille Broderie", "ready", "PAUSED", {
        valid: 7, pending: 3, discovered: 10,
      }, {
        updated: "2026-11-22 10:04",
      }),
    ],
  },
  {
    id: "fr-textile-2026-10",
    name: "法国纺织补充 2026-10",
    country: "FR",
    market: "FR",
    language: "fr-FR",
    category: "纺织／面料",
    status: "finished",
    createdAt: "2026-10-28 14:20",
    note: "补充站点的历史批次，已完成。",
    sites: [
      makeSite("lin-et-soie.fr", "Lin & Soie", "ready", "FINISHED", { valid: 18, discovered: 20 }, { coverage: "KNOWN", stopReason: "NATURAL_END", updated: "2026-10-29 11:20" }),
      makeSite("coton-bio.fr", "Coton Bio", "ready", "FINISHED", { valid: 12, discovered: 13 }, { coverage: "KNOWN", stopReason: "NATURAL_END", updated: "2026-10-29 11:32" }),
      makeSite("atelier-tissage.fr", "Atelier Tissage", "ready", "FINISHED", { valid: 26, discovered: 28 }, { coverage: "KNOWN", stopReason: "NATURAL_END", updated: "2026-10-29 11:45" }),
      makeSite("mercerie-rouge.fr", "Mercerie Rouge", "ready", "FINISHED", { valid: 9, discovered: 10 }, { coverage: "KNOWN", stopReason: "NATURAL_END", updated: "2026-10-29 12:01" }),
      makeSite("broderie-ancienne.fr", "Broderie Ancienne", "ready", "FINISHED", { valid: 21, discovered: 22 }, { coverage: "KNOWN", stopReason: "NATURAL_END", updated: "2026-10-29 12:14" }),
      makeSite("toile-lin.fr", "Toile de Lin", "ready", "FINISHED", { valid: 17, discovered: 18 }, { coverage: "KNOWN", stopReason: "NATURAL_END", updated: "2026-10-29 12:28" }),
      makeSite("filature-nord.fr", "Filature du Nord", "ready", "FINISHED", { valid: 11, discovered: 12 }, { coverage: "KNOWN", stopReason: "NATURAL_END", updated: "2026-10-29 12:36" }),
      makeSite("patchwork-ouest.fr", "Patchwork Ouest", "ready", "FINISHED", { valid: 15, discovered: 16 }, { coverage: "KNOWN", stopReason: "NATURAL_END", updated: "2026-10-29 12:44" }),
    ],
  },
  {
    id: "normandy-home-2026-09",
    name: "诺曼底家居 2026-09",
    country: "FR",
    market: "FR",
    language: "fr-FR",
    category: "家居／织物",
    status: "draft",
    createdAt: "2026-09-18 10:00",
    note: "待补充站点和预算，尚未启动。",
    sites: [
      makeSite("maison-coton.fr", "Maison Coton", "ready", null, {}, { updated: "2026-09-18 10:04" }),
      makeSite("atelier-broderie.fr", "Atelier Broderie", "ready", null, {}, { updated: "2026-09-18 10:04" }),
      makeSite("textile-normand.fr", "Textile Normand", "needs_onboarding", null, {}, { note: "未匹配受管规则包" }),
      makeSite("lin-sauvage.fr", "Lin Sauvage", "needs_onboarding", null, {}, { note: "未匹配受管规则包" }),
      makeSite("petite-mercerie.fr", "Petite Mercerie", "needs_onboarding", null, {}, { note: "未匹配受管规则包" }),
    ],
  },
];

const BATCH_STATUS = {
  draft: ["草稿", "muted"],
  partial: ["部分就绪", "warning"],
  running: ["运行中", "info"],
  finished: ["已完成", "success"],
  archived: ["已归档", "muted"],
};

const READINESS = {
  ready: ["可采", "ready"],
  needs_onboarding: ["待接入", "warning"],
  building: ["构建中", "info"],
  invalid: ["无效／重复", "danger"],
};

const TASK_STATE = {
  null: ["未开始", "muted"],
  DRAFT: ["草稿", "muted"],
  QUEUED: ["排队中", "info"],
  RUNNING: ["运行中", "info"],
  PAUSED: ["已暂停", "warning"],
  FINISHED: ["已完成", "success"],
  FAILED: ["失败", "danger"],
  CANCELLED: ["已取消", "muted"],
};

const STOP_REASON = {
  NATURAL_END: "自然结束",
  ACCESS_DENIED: "访问被拒绝",
  USER_CANCELLED: "用户取消",
  BUDGET_EXHAUSTED: "预算耗尽",
  PARTIAL_ENUMERATION: "部分枚举",
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function badge(label, tone) {
  return `<span class="badge badge-${tone}">${esc(label)}</span>`;
}

function batchStatusBadge(status) {
  const [label, tone] = BATCH_STATUS[status] || BATCH_STATUS.draft;
  return badge(label, tone);
}

function readinessBadge(readiness) {
  const [label, tone] = READINESS[readiness] || READINESS.invalid;
  return badge(label, tone);
}

function taskStateBadge(taskState) {
  const [label, tone] = TASK_STATE[taskState || "null"] || TASK_STATE.null;
  return badge(label, tone);
}

function stopReasonLabel(reason) {
  return reason ? STOP_REASON[reason] || reason : "—";
}

function statsFor(batch) {
  const sites = batch.sites;
  const count = (readiness) => sites.filter((item) => item.readiness === readiness).length;
  const tasks = (taskState) => sites.filter((item) => item.taskState === taskState).length;
  return {
    total: sites.length,
    ready: count("ready"),
    needs: count("needs_onboarding") + count("building"),
    invalid: count("invalid"),
    startable: sites.filter((item) => item.readiness === "ready" && (!item.taskState || item.taskState === "DRAFT")).length,
    running: tasks("RUNNING"),
    queued: tasks("QUEUED"),
    paused: tasks("PAUSED"),
    finished: tasks("FINISHED"),
    failed: tasks("FAILED"),
    cancelled: tasks("CANCELLED"),
  };
}

function allStats() {
  return batches.reduce((acc, batch) => {
    const item = statsFor(batch);
    acc.batches += 1;
    acc.sites += item.total;
    acc.ready += item.ready;
    acc.needs += item.needs;
    acc.invalid += item.invalid;
    acc.running += item.running;
    acc.finished += item.finished;
    acc.failed += item.failed;
    return acc;
  }, {
    batches: 0, sites: 0, ready: 0, needs: 0, invalid: 0,
    running: 0, finished: 0, failed: 0,
  });
}

function siteName(domain) {
  return SITE_NAMES[domain] || domain;
}

function setTopbar(title, sub) {
  breadcrumb.textContent = title;
  topbarSub.textContent = sub;
  document.title = `${title} · 批次工作台原型`;
}

function setActiveNav(name) {
  document.querySelectorAll("[data-nav]").forEach((link) => {
    link.classList.toggle("active", link.dataset.nav === name);
  });
}

function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  if (parts[0] === "batches" && parts[1] === "new") return { page: "newBatch" };
  if (parts[0] === "batches" && parts[1] && parts[2] === "sites" && parts[3]) {
    return {
      page: "site",
      batchId: decodeURIComponent(parts[1]),
      siteId: decodeURIComponent(parts[3]),
    };
  }
  if (parts[0] === "batches" && parts[1]) {
    return { page: "batch", batchId: decodeURIComponent(parts[1]) };
  }
  if (parts[0] === "tasks") return { page: "tasks" };
  if (parts[0] === "rules") return { page: "rules" };
  return { page: "batches" };
}

function render() {
  const current = route();
  const routeKey = `${current.page}:${current.batchId || ""}:${current.siteId || ""}`;
  const routeChanged = routeKey !== lastRouteKey;
  if (routeChanged) {
    state.itemTab = "product";
    if (current.page === "batch") state.siteFilter = "all";
    lastRouteKey = routeKey;
  }
  setActiveNav(current.page === "tasks" ? "tasks" : current.page === "rules" ? "rules" : "batches");

  if (current.page === "newBatch") {
    renderNewBatch();
  } else if (current.page === "batch") {
    renderBatch(current.batchId);
  } else if (current.page === "site") {
    renderSite(current.batchId, current.siteId);
  } else if (current.page === "tasks") {
    renderTasks();
  } else if (current.page === "rules") {
    renderRules();
  } else {
    renderBatches();
  }

  view.focus({ preventScroll: true });
  if (routeChanged) {
    window.scrollTo({ top: 0, behavior: "instant" });
  }
}

function renderBatches() {
  setTopbar("采集批次", "从一批站点开始，而不是从规则包开始");
  const summary = allStats();
  const filters = [
    ["all", "全部"],
    ["draft", "草稿"],
    ["partial", "部分就绪"],
    ["running", "运行中"],
    ["finished", "已完成"],
  ];
  const visible = batches.filter((batch) => state.batchFilter === "all" || batch.status === state.batchFilter);

  const rows = visible.map((batch) => {
    const stats = statsFor(batch);
    return `
      <tr>
        <td class="batch-cell">
          <a class="text-link" href="#/batches/${encodeURIComponent(batch.id)}">${esc(batch.name)}</a>
          <span>${esc(batch.id)}</span>
        </td>
        <td>${esc(batch.market)} · ${esc(batch.language)}</td>
        <td>${esc(batch.category)}</td>
        <td class="num">${stats.total}</td>
        <td>${readinessBadge("ready")} ${stats.ready}<span class="cell-note">${stats.needs} 待接入 · ${stats.invalid} 无效</span></td>
        <td>${batchStatusBadge(batch.status)}<span class="cell-note">${stats.running} 运行 · ${stats.finished} 完成 · ${stats.failed} 失败</span></td>
        <td class="nowrap">${esc(batch.createdAt)}</td>
        <td><a class="button button-sm" href="#/batches/${encodeURIComponent(batch.id)}">查看</a></td>
      </tr>
    `;
  }).join("");

  view.innerHTML = `
    <div class="page-head">
      <div>
        <h1>采集批次</h1>
        <p>把一批站点组织成一个采集项目：先判断哪些站可采，再启动可采站点，最后按批次查看和导出结果。</p>
      </div>
      <div class="page-actions">
        <a class="button button-primary" href="#/batches/new">新建批次</a>
      </div>
    </div>

    <div class="summary-strip" aria-label="全部批次摘要">
      ${summaryItem("批次", summary.batches, "全部项目")}
      ${summaryItem("站点", summary.sites, `${summary.invalid} 无效／重复`)}
      ${summaryItem("可采", summary.ready, "已有规则包")}
      ${summaryItem("待接入", summary.needs, "需技术构建")}
      ${summaryItem("运行中", summary.running, "不含排队与暂停")}
      ${summaryItem("已完成", summary.finished, "不含失败")}
    </div>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>批次列表</h2>
          <p>批次是组织和交付单位，不是任务状态或计数单位。</p>
        </div>
      </div>
      <div class="toolbar">
        <div class="filters" aria-label="批次状态筛选">
          ${filters.map(([value, label]) => `
            <button class="filter-button ${state.batchFilter === value ? "active" : ""}" data-action="filter-batches" data-value="${value}">${label}</button>
          `).join("")}
        </div>
      </div>
      ${visible.length ? `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>批次</th>
                <th>市场 · 语言</th>
                <th>品类</th>
                <th class="num">站点</th>
                <th>可采 / 待接入</th>
                <th>状态</th>
                <th>创建时间</th>
                <th></th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      ` : emptyState("还没有符合条件的批次", "换一个状态筛选，或新建一个批次。", "#/batches/new", "新建批次")}
    </section>
  `;
}

function summaryItem(label, value, hint) {
  return `
    <div class="summary-item">
      <span class="label">${esc(label)}</span>
      <span class="value">${esc(value)}</span>
      <span class="hint">${esc(hint)}</span>
    </div>
  `;
}

function emptyState(title, description, href, action) {
  return `
    <div class="empty">
      <h2>${esc(title)}</h2>
      <p>${esc(description)}</p>
      ${href ? `<a class="button button-primary" href="${href}">${esc(action)}</a>` : ""}
    </div>
  `;
}

function renderNewBatch() {
  const wizard = state.wizard;
  setTopbar("新建批次", "先组织站点，再判断可采性；规则包不应成为第一步");
  const stepLabel = ["基础信息", "导入站点", "匹配预览"][wizard.step - 1];

  const steps = [1, 2, 3].map((step) => {
    const label = ["基础信息", "导入站点", "匹配预览"][step - 1];
    return `<li class="${wizard.step === step ? "active" : wizard.step > step ? "done" : ""}"><span>${step}</span>${label}</li>`;
  }).join("");

  let content = "";
  if (wizard.step === 1) {
    content = `
      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>这批站点是什么</h2>
            <p>批次名称和默认市场会应用到整批站点，后续可以单站覆盖。</p>
          </div>
        </div>
        <div class="panel-body">
          <div class="form-grid">
            <div class="field full">
              <label for="wizard-name">批次名称</label>
              <input id="wizard-name" type="text" value="${esc(wizard.name)}" placeholder="例如：法国手工纺织 2026-11" />
              <span class="hint">用于以后找回和导出，不要求与站点域名一致。</span>
            </div>
            <div class="field">
              <label for="wizard-country">国家／市场</label>
              <input id="wizard-country" type="text" value="${esc(wizard.country)}" />
            </div>
            <div class="field">
              <label for="wizard-language">语言</label>
              <input id="wizard-language" type="text" value="${esc(wizard.language)}" />
            </div>
            <div class="field">
              <label for="wizard-category">品类／业务线</label>
              <input id="wizard-category" type="text" value="${esc(wizard.category)}" />
            </div>
            <div class="field">
              <label for="wizard-note">备注</label>
              <input id="wizard-note" type="text" value="${esc(wizard.note || "")}" placeholder="可选" />
            </div>
          </div>
          <div class="form-actions">
            <a class="button" href="#/batches">取消</a>
            <button class="button button-primary" data-action="wizard-next">下一步：导入站点</button>
          </div>
        </div>
      </section>
    `;
  } else if (wizard.step === 2) {
    content = `
      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>导入站点</h2>
            <p>每行一个网址或域名；系统会去重、校验并匹配已有规则包。</p>
          </div>
        </div>
        <div class="panel-body">
          <div class="import-grid">
            <div>
              <label class="field" for="wizard-sites">
                <span>站点列表</span>
                <textarea id="wizard-sites" spellcheck="false">${esc(wizard.sitesText)}</textarea>
                <span class="hint">支持粘贴或上传 CSV；原型不解析真实文件。</span>
              </label>
            </div>
            <div>
              <div class="notice">
                <div>
                  <strong>先导入，再匹配</strong>
                  <p>未匹配到规则包的站点不会被隐藏；它们会进入“待接入”，由技术角色构建。</p>
                </div>
              </div>
              <div class="stat-line">
                <div class="stat-box"><span class="label">示例有效</span><span class="value">4</span></div>
                <div class="stat-box"><span class="label">重复</span><span class="value">1</span></div>
                <div class="stat-box"><span class="label">无效</span><span class="value">1</span></div>
              </div>
              <p class="muted">点击“解析并继续”后，系统会按域名匹配已有规则包，并显示可采／待接入数量。</p>
            </div>
          </div>
          <div class="form-actions">
            <button class="button" data-action="wizard-back">上一步</button>
            <button class="button button-primary" data-action="wizard-next">解析并继续</button>
          </div>
        </div>
      </section>
    `;
  } else {
    const parsed = wizard.parsed || [];
    const readyCount = parsed.filter((item) => item.readiness === "ready").length;
    const needsCount = parsed.filter((item) => item.readiness === "needs_onboarding").length;
    const invalidCount = parsed.filter((item) => item.readiness === "invalid").length;
    const invalidItems = parsed.filter((item) => item.readiness === "invalid");
    content = `
      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>匹配预览</h2>
            <p>确认哪些站点可以立即采集，哪些需要接入；保存草稿或只启动可采站点。</p>
          </div>
        </div>
        <div class="panel-body">
          <div class="stat-line">
            <div class="stat-box"><span class="label">可采</span><span class="value">${readyCount}</span></div>
            <div class="stat-box"><span class="label">待接入</span><span class="value">${needsCount}</span></div>
            <div class="stat-box"><span class="label">无效／重复</span><span class="value">${invalidCount}</span></div>
          </div>
          ${invalidItems.length ? `
            <div class="notice danger">
              <div>
                <strong>${invalidItems.length} 条无效／重复需要处理</strong>
                <ul class="issue-list">
                  ${invalidItems.map((item) => `<li><code>${esc(item.domain)}</code>：${esc(item.note || "网址无效或重复")}</li>`).join("")}
                </ul>
                <p>这些条目不会进入批次；修正后重新导入，不要把它们当成任务失败。</p>
              </div>
            </div>
          ` : ""}
          <div class="preview-list">
            ${parsed.map((item) => `
              <div class="preview-row">
                <div>
                  <code>${esc(item.domain)}</code>
                  <span class="cell-note">${esc(item.note || "")}</span>
                </div>
                ${readinessBadge(item.readiness)}
              </div>
            `).join("")}
          </div>
          <div class="notice ${needsCount ? "warning" : ""}">
            <div>
              <strong>${needsCount ? `${needsCount} 个站点需要接入` : "全部站点可采"}</strong>
              <p>${needsCount ? "可先启动可采站点；待接入站点保留在批次中，不会阻塞整批。" : "可以保存草稿，或直接启动可采站点。"}</p>
            </div>
          </div>
          <div class="form-actions">
            <button class="button" data-action="wizard-back">上一步</button>
            <button class="button" data-action="wizard-save" data-start="false">保存草稿</button>
            <button class="button button-primary" data-action="wizard-save" data-start="true">保存并启动可采站点</button>
          </div>
        </div>
      </section>
    `;
  }

  view.innerHTML = `
    <div class="page-head">
      <div>
        <a class="text-link back-link" href="#/batches">← 返回批次列表</a>
        <h1>新建批次</h1>
        <p>当前步骤：${esc(stepLabel)}。批次先保存站点和默认计划，规则包匹配在导入后完成。</p>
      </div>
    </div>
    <ol class="stepper">${steps}</ol>
    ${content}
  `;
}

function parseSites(text) {
  const seen = new Set();
  const parsed = [];
  text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean).forEach((raw) => {
    const cleaned = raw.replace(/^https?:\/\//i, "").split(/[/?#]/)[0].replace(/^www\./i, "").toLowerCase();
    if (!cleaned || !cleaned.includes(".")) {
      parsed.push({
        domain: raw,
        readiness: "invalid",
        note: "网址不完整",
      });
      return;
    }
    if (seen.has(cleaned)) {
      parsed.push({
        domain: cleaned,
        readiness: "invalid",
        note: "批次内重复",
      });
      return;
    }
    seen.add(cleaned);
    const rule = RULE_DATA[cleaned];
    parsed.push({
      domain: cleaned,
      readiness: rule ? "ready" : "needs_onboarding",
      note: rule ? `已匹配 ${rule.id}@${rule.version}` : "没有受管规则包",
    });
  });
  return parsed;
}

function renderBatch(batchId) {
  const batch = batches.find((item) => item.id === batchId);
  if (!batch) {
    setTopbar("批次不存在", "请返回批次列表");
    view.innerHTML = emptyState("找不到这个批次", "它可能已被移除，或链接不完整。", "#/batches", "返回采集批次");
    return;
  }
  const stats = statsFor(batch);
  setTopbar(batch.name, `${batch.country} · ${batch.language} · ${batch.category}`);

  const filters = [
    ["all", `全部 ${stats.total}`],
    ["ready", `可采 ${stats.ready}`],
    ...(stats.startable ? [["not_started", `未开始 ${stats.startable}`]] : []),
    ["needs_onboarding", `待接入 ${stats.needs}`],
    ["running", `运行中 ${stats.running}`],
    ...(stats.paused ? [["paused", `暂停 ${stats.paused}`]] : []),
    ...(stats.queued ? [["queued", `排队 ${stats.queued}`]] : []),
    ["finished", `已完成 ${stats.finished}`],
    ["failed", `失败 ${stats.failed}`],
    ["invalid", `无效／重复 ${stats.invalid}`],
  ];
  const visibleSites = batch.sites.filter((site) => {
    if (state.siteFilter === "all") return true;
    if (state.siteFilter === "ready") return site.readiness === "ready";
    if (state.siteFilter === "not_started") {
      return site.readiness === "ready" && (!site.taskState || site.taskState === "DRAFT");
    }
    if (state.siteFilter === "needs_onboarding") return site.readiness === "needs_onboarding" || site.readiness === "building";
    if (state.siteFilter === "invalid") return site.readiness === "invalid";
    return site.taskState === state.siteFilter.toUpperCase();
  });

  const rows = visibleSites.map((site) => {
    const countText = site.readiness === "ready"
      ? `${site.counts.valid} 有效 · ${site.counts.failed} 失败`
      : "—";
    return `
      <tr>
        <td class="site-cell">
          <a class="text-link" href="#/batches/${encodeURIComponent(batch.id)}/sites/${encodeURIComponent(site.domain)}">${esc(site.name)}</a>
          <span>${esc(site.domain)}</span>
        </td>
        <td>${esc(batch.market)}</td>
        <td>${readinessBadge(site.readiness)}</td>
        <td>${site.readiness === "ready" ? taskStateBadge(site.taskState) : '<span class="faint">—</span>'}</td>
        <td class="num">${countText}</td>
        <td>${esc(stopReasonLabel(site.stopReason))}</td>
        <td class="nowrap">${esc(site.updated)}</td>
        <td><a class="button button-sm" href="#/batches/${encodeURIComponent(batch.id)}/sites/${encodeURIComponent(site.domain)}">查看</a></td>
      </tr>
    `;
  }).join("");

  const needsCopy = stats.startable > 0
    ? `可以先用 ${stats.startable} 个未开始的可采站点启动本批次；待接入站点保留在批次中，由技术角色构建规则包后再启动。`
    : "可采站点均已启动或进入终态；待接入站点保留在批次中，由技术角色构建规则包后再启动。";
  const needsNotice = stats.needs > 0
    ? `<div class="notice warning">
        <div>
          <strong>${stats.needs} 个站点待接入，不阻塞可采站点</strong>
          <p>${needsCopy}</p>
        </div>
      </div>`
    : "";
  const failedNotice = stats.failed > 0
    ? `<div class="notice danger">
        <div>
          <strong>${stats.failed} 个站点失败</strong>
          <p>失败不会阻止其他站点完成；进入站点详情查看停止原因和下一步。</p>
        </div>
      </div>`
    : "";

  view.innerHTML = `
    <div class="page-head">
      <div>
        <a class="text-link back-link" href="#/batches">← 返回批次列表</a>
        <h1>${esc(batch.name)} ${batchStatusBadge(batch.status)}</h1>
        <p>${esc(batch.note || "按站点判断可采性，按批次组织采集和交付。")}</p>
      </div>
      <div class="page-actions">
        <button class="button button-primary" data-action="start-batch" data-batch-id="${esc(batch.id)}" title="${stats.startable === 0 ? "没有未开始的可采站点" : "启动未开始的可采站点"}" ${stats.startable === 0 ? "disabled" : ""}>启动未开始站点</button>
        <button class="button" data-action="pause-batch" data-batch-id="${esc(batch.id)}" ${stats.running === 0 ? "disabled" : ""}>暂停运行中</button>
        <button class="button button-danger" data-action="cancel-batch" data-batch-id="${esc(batch.id)}" ${stats.running === 0 && stats.queued === 0 ? "disabled" : ""}>取消运行中</button>
        <button class="button" data-action="export-batch" data-batch-id="${esc(batch.id)}" ${stats.finished === 0 && stats.running === 0 ? "disabled" : ""}>导出批次</button>
      </div>
    </div>

    <div class="summary-strip" aria-label="批次摘要">
      ${summaryItem("站点", stats.total, "整批")}
      ${summaryItem("可采", stats.ready, stats.startable ? `${stats.startable} 未开始` : "已有规则包")}
      ${summaryItem("待接入", stats.needs, "需技术构建")}
      ${summaryItem("无效／重复", stats.invalid, "不会启动")}
      ${summaryItem("运行中", stats.running, `${stats.paused + stats.queued} 暂停／排队`)}
      ${summaryItem("完成／失败", `${stats.finished}／${stats.failed}`, "终态／需处理")}
    </div>

    ${needsNotice}
    ${failedNotice}

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>站点</h2>
          <p>接入状态和任务状态分开看；待接入不是失败。</p>
        </div>
        <a class="text-link" href="#/tasks">在全部任务中查看 →</a>
      </div>
      <div class="toolbar">
        <div class="filters" aria-label="站点筛选">
          ${filters.map(([value, label]) => `
            <button class="filter-button ${state.siteFilter === value ? "active" : ""}" data-action="filter-sites" data-value="${value}">${label}</button>
          `).join("")}
        </div>
      </div>
      ${visibleSites.length ? `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>站点</th>
                <th>市场</th>
                <th>接入状态</th>
                <th>任务状态</th>
                <th class="num">结果</th>
                <th>停止原因</th>
                <th>更新时间</th>
                <th></th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      ` : emptyState("没有符合条件的站点", "换一个筛选条件，或回到全部站点。", "", "")}
    </section>

    <section class="panel">
      <div class="panel-body">
        <div class="meta-grid">
          <div class="meta-item"><span class="label">国家</span><span class="value">${esc(batch.country)}</span></div>
          <div class="meta-item"><span class="label">市场／语言</span><span class="value">${esc(batch.market)} / ${esc(batch.language)}</span></div>
          <div class="meta-item"><span class="label">品类</span><span class="value">${esc(batch.category)}</span></div>
          <div class="meta-item"><span class="label">创建时间</span><span class="value">${esc(batch.createdAt)}</span></div>
          <div class="meta-item"><span class="label">计数口径</span><span class="value">按任务分别计数，不合并商品数</span></div>
        </div>
      </div>
    </section>
  `;
}

function itemsForSite(site) {
  return {
    products: [
      { name: `${site.name} · 亚麻桌布`, price: "32,00 €", description: "完整", status: "有效" },
      { name: `${site.name} · 手工餐巾`, price: "18,50 €", description: "部分", status: "有效" },
      { name: `${site.name} · 织物样本`, price: "6,00 €", description: "完整", status: "有效" },
      { name: `${site.name} · 刺绣套件`, price: "24,90 €", description: "原站未提供", status: "有效" },
      { name: `${site.name} · 已下架商品`, price: "—", description: "—", status: "排除" },
    ],
    urls: [
      { url: `https://${site.domain}/collections/all`, type: "列表", status: "已完成" },
      { url: `https://${site.domain}/products/lin-lave`, type: "商品", status: "已完成" },
      { url: `https://${site.domain}/products/serviettes`, type: "商品", status: "已完成" },
      { url: `https://${site.domain}/products/kit-broderie`, type: "商品", status: "已完成" },
      { url: `https://${site.domain}/collections/archives`, type: "列表", status: "排除" },
    ],
  };
}

function renderSite(batchId, siteId) {
  const batch = batches.find((item) => item.id === batchId);
  const site = batch?.sites.find((item) => item.domain === siteId);
  if (!batch || !site) {
    setTopbar("站点不存在", "请返回批次列表");
    view.innerHTML = emptyState("找不到这个站点", "它可能不属于当前批次，或链接不完整。", "#/batches", "返回采集批次");
    return;
  }
  setTopbar(site.name, `${batch.name} · ${site.domain}`);

  const back = `<a class="text-link back-link" href="#/batches/${encodeURIComponent(batch.id)}">← 返回 ${esc(batch.name)}</a>`;

  if (site.readiness === "needs_onboarding" || site.readiness === "building") {
    view.innerHTML = `
      <div class="page-head">
        <div>
          ${back}
          <h1>${esc(site.name)} ${readinessBadge(site.readiness)}</h1>
          <p>${esc(site.domain)} · ${esc(batch.name)}</p>
        </div>
        <div class="page-actions">
          <a class="button" href="#/batches/${encodeURIComponent(batch.id)}">返回批次</a>
        </div>
      </div>
      <div class="notice warning">
        <div>
          <strong>该站点还没有受管规则包</strong>
          <p>“待接入”不是失败。技术角色需要在构建 harness 中分析站点、生成并复核规则包；业务侧可以先启动其他可采站点。</p>
        </div>
      </div>
      <section class="panel">
        <div class="panel-head"><div><h2>接入路径</h2><p>规则包是内部资产，不出现在批次创建主流程。</p></div></div>
        <div class="panel-body">
          <ol class="muted">
            <li>技术角色提交构建任务，分析站点入口、分页、字段和兼容条件。</li>
            <li>生成规则包并在独立环境复核，标记为可采。</li>
            <li>站点接入状态从“待接入”变为“可采”。</li>
            <li>回到批次详情，启动该站点。</li>
          </ol>
          <p class="muted">当前原型不触发真实构建；这里只展示业务用户会看到的状态和下一步。</p>
        </div>
      </section>
    `;
    return;
  }

  if (site.readiness === "invalid") {
    view.innerHTML = `
      <div class="page-head">
        <div>
          ${back}
          <h1>${esc(site.name)} ${readinessBadge(site.readiness)}</h1>
          <p>${esc(site.domain)} · ${esc(batch.name)}</p>
        </div>
        <div class="page-actions"><a class="button" href="#/batches/${encodeURIComponent(batch.id)}">返回批次</a></div>
      </div>
      <div class="notice danger">
        <div>
          <strong>这个站点不能进入采集</strong>
          <p>${esc(site.note || "网址无效或重复。")} 修正站点清单后重新导入；不要把它当成任务失败。</p>
        </div>
      </div>
    `;
    return;
  }

  const counts = site.counts;
  const coverageText = site.coverage === "KNOWN" ? "已知" : "未知";
  const quality = site.quality.length
    ? `<ul class="quality-list">${site.quality.map((item) => `
        <li>
          <code>${esc(item.source)}</code>
          <div class="muted">描述状态：${esc(item.description)} · 部分原因：${esc(item.reason)}</div>
          <div class="faint">缺失字段：${esc(item.missing)}</div>
        </li>
      `).join("")}</ul>`
    : `<p class="muted">没有质量异常。</p>`;
  const items = itemsForSite(site);
  const activeTab = state.itemTab === "url" ? "url" : "product";
  const rows = activeTab === "product"
    ? items.products.map((item) => `
        <tr>
          <td>${esc(item.name)}</td>
          <td>${esc(item.price)}</td>
          <td>${esc(item.description)}</td>
          <td>${esc(item.status)}</td>
        </tr>
      `).join("")
    : items.urls.map((item) => `
        <tr>
          <td><code>${esc(item.url)}</code></td>
          <td>${esc(item.type)}</td>
          <td>${esc(item.status)}</td>
        </tr>
      `).join("");

  view.innerHTML = `
    <div class="page-head">
      <div>
        ${back}
        <h1>${esc(site.name)} ${taskStateBadge(site.taskState)}</h1>
        <p>${esc(site.domain)} · ${esc(batch.name)} · ${esc(batch.market)} / ${esc(batch.language)}</p>
      </div>
      <div class="page-actions">
        ${site.taskState === "RUNNING" || site.taskState === "QUEUED" ? `<button class="button" data-action="pause-site" data-batch-id="${esc(batch.id)}" data-site-id="${esc(site.domain)}">暂停</button>` : ""}
        ${site.taskState === "PAUSED" ? `<button class="button" data-action="resume-site" data-batch-id="${esc(batch.id)}" data-site-id="${esc(site.domain)}">恢复</button>` : ""}
        ${site.taskState === "RUNNING" || site.taskState === "QUEUED" || site.taskState === "PAUSED" ? `<button class="button button-danger" data-action="cancel-site" data-batch-id="${esc(batch.id)}" data-site-id="${esc(site.domain)}">取消任务</button>` : ""}
        <button class="button" data-action="export-site" data-batch-id="${esc(batch.id)}" data-site-id="${esc(site.domain)}">导出</button>
      </div>
    </div>

    <div class="summary-strip" aria-label="站点摘要">
      ${summaryItem("有效商品", counts.valid, "进入有效集")}
      ${summaryItem("业务排除", counts.excluded, "保留原因")}
      ${summaryItem("失败", counts.failed, "需处理")}
      ${summaryItem("待处理", counts.pending, "未完成")}
      ${summaryItem("发现 URL", counts.discovered, "导航与商品")}
      ${summaryItem("覆盖", coverageText, "不伪造百分比")}
    </div>

    <div class="detail-grid">
      <div class="stack">
        <section class="panel">
          <div class="panel-head">
            <div><h2>结果</h2><p>先看是否能用的结果，再看明细；计数不等于业务验收。</p></div>
          </div>
          <div class="panel-body">
            <div class="tabs" role="tablist">
              <button class="tab ${activeTab === "product" ? "active" : ""}" data-action="item-tab" data-value="product" role="tab" aria-selected="${activeTab === "product"}">商品</button>
              <button class="tab ${activeTab === "url" ? "active" : ""}" data-action="item-tab" data-value="url" role="tab" aria-selected="${activeTab === "url"}">网址</button>
            </div>
            <div class="table-wrap">
              <table>
                <thead>
                  ${activeTab === "product"
                    ? "<tr><th>商品</th><th>价格</th><th>描述状态</th><th>状态</th></tr>"
                    : "<tr><th>网址</th><th>类型</th><th>状态</th></tr>"}
                </thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
            <p class="muted" style="margin: 12px 0 0;">原型只展示前 5 条；真实页面按任务分页。</p>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head"><div><h2>质量异常</h2><p>让用户知道缺什么，而不是自己解析 JSON。</p></div></div>
          <div class="panel-body">${quality}</div>
        </section>
      </div>

      <div class="stack">
        <section class="panel">
          <div class="panel-body">
            <div class="meta-grid" style="border-top: 0; grid-template-columns: 1fr;">
              <div class="meta-item"><span class="label">所属批次</span><span class="value"><a class="text-link" href="#/batches/${encodeURIComponent(batch.id)}">${esc(batch.name)}</a></span></div>
              <div class="meta-item"><span class="label">停止原因</span><span class="value">${esc(stopReasonLabel(site.stopReason))}</span></div>
              <div class="meta-item"><span class="label">覆盖</span><span class="value">${coverageText}${site.coverage === "UNKNOWN" ? "（不显示百分比）" : ""}</span></div>
              <div class="meta-item"><span class="label">更新时间</span><span class="value">${esc(site.updated)}</span></div>
            </div>
          </div>
        </section>

        <details class="technical">
          <summary>技术详情：规则包、任务与环境</summary>
          <div class="technical-body">
            <dl class="kv">
              <dt>规则包</dt><dd>${site.rule ? `${esc(site.rule.id)}@${esc(site.rule.version)}` : "—"}</dd>
              <dt>验证时间</dt><dd>${site.rule ? esc(site.rule.verified) : "—"}</dd>
              <dt>任务 ID</dt><dd>${esc(site.taskId || "—")}</dd>
              <dt>市场 / 语言</dt><dd>${esc(batch.market)} / ${esc(batch.language)}</dd>
              <dt>任务状态</dt><dd>${esc(site.taskState || "未开始")}</dd>
            </dl>
            <p class="muted" style="margin-bottom: 0;">规则包是站点背后的方案版本，不作为业务用户创建任务的第一入口。</p>
          </div>
        </details>
      </div>
    </div>
  `;
}

function renderTasks() {
  setTopbar("全部任务", "技术排查视图；业务用户通常从批次进入");
  const rows = batches.flatMap((batch) => batch.sites
    .filter((site) => site.taskState)
    .map((site) => ({ batch, site })))
    .map(({ batch, site }) => `
      <tr>
        <td>${taskStateBadge(site.taskState)}</td>
        <td class="site-cell"><a class="text-link" href="#/batches/${encodeURIComponent(batch.id)}/sites/${encodeURIComponent(site.domain)}">${esc(site.name)}</a><span>${esc(site.domain)}</span></td>
        <td><a class="text-link" href="#/batches/${encodeURIComponent(batch.id)}">${esc(batch.name)}</a></td>
        <td>${esc(batch.market)} / ${esc(batch.language)}</td>
        <td class="num">${site.counts.valid} / ${site.counts.failed}</td>
        <td>${esc(stopReasonLabel(site.stopReason))}</td>
        <td class="nowrap">${esc(site.updated)}</td>
      </tr>
    `).join("");

  view.innerHTML = `
    <div class="page-head">
      <div>
        <h1>全部任务</h1>
        <p>任务是一次站点 × 规则包版本 × 市场的执行。这里用于技术排查，不作为业务首页。</p>
      </div>
    </div>
    <section class="panel">
      <div class="panel-head"><div><h2>任务</h2><p>业务用户通常从批次详情下钻；技术角色可以在这里按任务查看。</p></div></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>状态</th><th>站点</th><th>批次</th><th>市场 / 语言</th><th class="num">有效 / 失败</th><th>停止原因</th><th>更新时间</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function renderRules() {
  setTopbar("规则包（技术）", "规则包是站点资产，不是业务创建入口");
  const usedBy = (domain) => batches
    .filter((batch) => batch.sites.some((site) => site.domain === domain))
    .map((batch) => batch.name);
  const rows = Object.entries(RULE_DATA).map(([domain, rule]) => {
    const names = usedBy(domain);
    return `
      <tr>
        <td class="site-cell"><strong>${esc(siteName(domain))}</strong><span>${esc(domain)}</span></td>
        <td><code>${esc(rule.id)}@${esc(rule.version)}</code></td>
        <td>${esc(rule.verified)}</td>
        <td>${names.length ? esc(names.join("、")) : "<span class=\"faint\">未被批次引用</span>"}</td>
      </tr>
    `;
  }).join("");

  view.innerHTML = `
    <div class="page-head">
      <div>
        <h1>规则包（技术）</h1>
        <p>规则包是某个站点的一套可执行采集方案版本。业务用户提交站点，系统匹配规则包；未匹配的站点进入待接入。</p>
      </div>
    </div>
    <div class="notice">
      <div>
        <strong>这不是业务首页</strong>
        <p>规则包不应出现在批次创建的第一步。这里只给技术角色查看版本、验证时间和被哪些批次引用。</p>
      </div>
    </div>
    <section class="panel">
      <div class="panel-head"><div><h2>受管规则包</h2><p>一个站点可以有多个版本；当前表只展示已接入的版本。</p></div></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>站点</th><th>规则包版本</th><th>验证时间</th><th>被批次引用</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function openDialog({ title, body, confirmLabel = "确认", tone = "primary", onConfirm }) {
  const dialogTitle = document.querySelector("#dialog-title");
  const dialogBody = document.querySelector("#dialog-body");
  const confirm = document.querySelector("#dialog-confirm");
  dialogTitle.textContent = title;
  dialogBody.innerHTML = body;
  confirm.textContent = confirmLabel;
  confirm.className = `button ${tone === "danger" ? "button-danger" : "button-primary"}`;
  confirm.onclick = (event) => {
    event.preventDefault();
    dialog.close();
    onConfirm?.();
  };
  dialog.showModal();
}

function toast(message) {
  toastEl.textContent = message;
  toastEl.classList.add("show");
  window.clearTimeout(toast._timer);
  toast._timer = window.setTimeout(() => toastEl.classList.remove("show"), 2600);
}

function startBatch(batch) {
  const startable = batch.sites.filter((site) => site.readiness === "ready" && (!site.taskState || site.taskState === "DRAFT"));
  if (!startable.length) {
    toast("没有待启动的可采站点。");
    return;
  }
  openDialog({
    title: "启动可采站点",
    body: `<p>将为 <strong>${startable.length}</strong> 个可采站点创建任务。</p>
      <p>${batch.sites.filter((site) => site.readiness !== "ready").length} 个待接入或无效站点会保留在批次中，不会被当成失败。</p>
      <p>这是静态原型：确认后只更新模拟状态，不连接后端。</p>`,
    confirmLabel: "启动",
    onConfirm: () => {
      startable.forEach((site) => { site.taskState = "QUEUED"; });
      batch.status = batch.sites.some((site) => site.readiness === "needs_onboarding") ? "partial" : "running";
      toast(`原型：已模拟启动 ${startable.length} 个站点任务。`);
      render();
    },
  });
}

function pauseBatch(batch) {
  const running = batch.sites.filter((site) => site.taskState === "RUNNING" || site.taskState === "QUEUED");
  openDialog({
    title: "暂停运行中任务",
    body: `<p>将暂停 <strong>${running.length}</strong> 个运行中或排队中的任务。已完成的站点不受影响。</p>
      <p>这是静态原型：确认后只更新模拟状态。</p>`,
    confirmLabel: "暂停",
    onConfirm: () => {
      running.forEach((site) => { site.taskState = "PAUSED"; });
      toast("原型：已模拟暂停运行中任务。");
      render();
    },
  });
}

function cancelBatch(batch) {
  const active = batch.sites.filter((site) => ["RUNNING", "QUEUED", "PAUSED"].includes(site.taskState));
  openDialog({
    title: "取消运行中任务",
    body: `<p>将取消 <strong>${active.length}</strong> 个运行中、排队或暂停的任务。已完成的站点结果保留。</p>
      <p>取消是终态，不能恢复；这是静态原型，不会影响真实任务。</p>`,
    confirmLabel: "取消任务",
    tone: "danger",
    onConfirm: () => {
      active.forEach((site) => { site.taskState = "CANCELLED"; });
      toast("原型：已模拟取消任务。");
      render();
    },
  });
}

function exportBatch(batch) {
  const stats = statsFor(batch);
  openDialog({
    title: "导出批次",
    body: `<p>将导出 <strong>${stats.finished}</strong> 个已完成站点的结果，运行中和失败站点会按实际状态标注。</p>
    <p>${stats.needs} 个待接入和 ${stats.invalid} 个无效站点不包含在导出中。</p>
    <p>导出结构为“批次清单 + 按站点目录”，不会把不同任务的商品数合并成一个总数。</p>
    <p>这是静态原型：不会生成真实 zip。</p>`,
    confirmLabel: "确认导出",
    onConfirm: () => toast("原型：导出未连接后端，未生成文件。"),
  });
}

function updateSite(batch, siteId, updater) {
  const site = batch.sites.find((item) => item.domain === siteId);
  if (!site) return;
  updater(site);
  render();
}

document.addEventListener("click", (event) => {
  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const batch = target.dataset.batchId
    ? batches.find((item) => item.id === target.dataset.batchId)
    : null;

  if (action === "filter-batches") {
    state.batchFilter = target.dataset.value;
    render();
  } else if (action === "filter-sites") {
    state.siteFilter = target.dataset.value;
    render();
  } else if (action === "item-tab") {
    state.itemTab = target.dataset.value;
    render();
  } else if (action === "wizard-next") {
    if (state.wizard.step === 1) {
      const name = document.querySelector("#wizard-name")?.value.trim();
      if (!name) {
        toast("先给批次起一个名字。");
        return;
      }
      state.wizard.name = name;
      state.wizard.country = document.querySelector("#wizard-country")?.value.trim() || "FR";
      state.wizard.language = document.querySelector("#wizard-language")?.value.trim() || "fr-FR";
      state.wizard.category = document.querySelector("#wizard-category")?.value.trim() || "手工／纺织";
      state.wizard.note = document.querySelector("#wizard-note")?.value.trim() || "";
      state.wizard.step = 2;
    } else if (state.wizard.step === 2) {
      state.wizard.sitesText = document.querySelector("#wizard-sites")?.value || "";
      state.wizard.parsed = parseSites(state.wizard.sitesText);
      if (!state.wizard.parsed.length) {
        toast("至少输入一个站点。");
        return;
      }
      state.wizard.step = 3;
    }
    render();
  } else if (action === "wizard-back") {
    state.wizard.step = Math.max(1, state.wizard.step - 1);
    render();
  } else if (action === "wizard-save") {
    const start = target.dataset.start === "true";
    saveNewBatch(start);
  } else if (action === "start-batch" && batch) {
    startBatch(batch);
  } else if (action === "pause-batch" && batch) {
    pauseBatch(batch);
  } else if (action === "cancel-batch" && batch) {
    cancelBatch(batch);
  } else if (action === "export-batch" && batch) {
    exportBatch(batch);
  } else if (action === "pause-site" && batch) {
    updateSite(batch, target.dataset.siteId, (site) => { site.taskState = "PAUSED"; });
    toast("原型：已模拟暂停站点任务。");
  } else if (action === "resume-site" && batch) {
    updateSite(batch, target.dataset.siteId, (site) => { site.taskState = "RUNNING"; });
    toast("原型：已模拟恢复站点任务。");
  } else if (action === "cancel-site" && batch) {
    updateSite(batch, target.dataset.siteId, (site) => { site.taskState = "CANCELLED"; });
    toast("原型：已模拟取消站点任务。");
  } else if (action === "export-site") {
    toast("原型：单站导出未连接后端。");
  }
});

function saveNewBatch(start) {
  const wizard = state.wizard;
  const parsed = wizard.parsed || [];
  const id = `batch-${Date.now()}`;
  const sites = parsed.map((item) => makeSite(
    item.domain,
    siteName(item.domain),
    item.readiness,
    start && item.readiness === "ready" ? "QUEUED" : null,
    {},
    { note: item.note, updated: "刚刚" },
  ));
  const status = start
    ? (sites.some((site) => site.readiness === "needs_onboarding") ? "partial" : "running")
    : "draft";
  batches.unshift({
    id,
    name: wizard.name,
    country: wizard.country,
    market: wizard.country || "FR",
    language: wizard.language,
    category: wizard.category,
    status,
    createdAt: "刚刚",
    note: wizard.note || "从原型新建批次。",
    sites,
  });
  state.wizard = freshWizard();
  state.siteFilter = "all";
  toast(start ? "原型：批次已保存，并模拟启动可采站点。" : "原型：批次已保存为草稿。");
  location.hash = `#/batches/${encodeURIComponent(id)}`;
}

window.addEventListener("hashchange", render);
if (!location.hash) {
  history.replaceState(null, "", "#/batches");
}
render();
