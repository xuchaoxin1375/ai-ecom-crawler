import { runs } from "./data.js";

const page = document.querySelector("#page");
const toast = document.querySelector("#toast");

const numberFormat = new Intl.NumberFormat("zh-CN");
const decimalFormat = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});
const percentFormat = new Intl.NumberFormat("zh-CN", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const params = new URLSearchParams(location.search);
let stateKey = runs[params.get("state")] ? params.get("state") : "finished";
let activeView = ["data", "quality", "analysis", "detail"].includes(params.get("view"))
  ? params.get("view")
  : "analysis";
let windowMode = stateKey === "running" ? "15" : "full";
let bucketMode = "1";
let chartMode = "rate";
let frozen = false;
let visibleSeries = new Set(["processed", "valid", "failed"]);
let charts = new Map();
let toastTimer = 0;

const TABS = [
  { key: "data", label: "数据明细" },
  { key: "quality", label: "质量与验收" },
  { key: "analysis", label: "运行分析" },
  { key: "detail", label: "运行明细" },
];

const SERIES = {
  processed: { label: "处理", color: "var(--accent)" },
  valid: { label: "有效", color: "var(--success)" },
  failed: { label: "失败", color: "var(--danger)" },
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatNumber(value) {
  return numberFormat.format(Math.max(0, Number(value) || 0));
}

function formatDecimal(value) {
  return decimalFormat.format(Number(value) || 0);
}

function formatPercent(value) {
  return `${percentFormat.format((Number(value) || 0) * 100)}%`;
}

function formatDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const rest = total % 60;
  if (hours > 0) return `${hours} 小时 ${minutes} 分`;
  return `${minutes} 分 ${String(rest).padStart(2, "0")} 秒`;
}

function formatDateTime(iso) {
  if (!iso) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
    .format(new Date(iso))
    .replaceAll("/", "-");
}

function formatClock(value) {
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function stateTone(run) {
  if (run.state === "RUNNING") return "info";
  if (run.state === "FINISHED") return run.outcome === "COMPLETED" ? "success" : "warning";
  return "neutral";
}

function stateLabel(run) {
  return (
    {
      RUNNING: "运行中",
      FINISHED: "已结束",
      PAUSED: "已暂停",
      QUEUED: "排队中",
      CANCELLED: "已取消",
    }[run.state] || run.state
  );
}

function taskTypeLabel(run) {
  return run.taskType === "discovery" ? "网址发现任务" : "商品任务";
}

function visibleBucketCount(run) {
  if (windowMode === "full") return run.processed.length;
  return Math.min(run.processed.length, Number(windowMode));
}

function sourceRows(run) {
  return run.processed.map((processed, index) => ({
    index,
    ts: new Date(run.start).getTime() + index * 60_000,
    processed,
    valid: run.valid[index] || 0,
    failed: run.failed[index] || 0,
    excluded: run.excluded[index] || 0,
  }));
}

function aggregateRows(rows, size) {
  if (size <= 1) {
    return rows.map((row) => ({
      ...row,
      startTs: row.ts,
      endTs: row.ts + 60_000,
      lastIndex: row.index,
    }));
  }
  const groups = [];
  for (let index = 0; index < rows.length; index += size) {
    const group = rows.slice(index, index + size);
    if (!group.length) continue;
    const first = group[0];
    const last = group[group.length - 1];
    groups.push({
      index: first.index,
      lastIndex: last.index,
      ts: last.ts,
      startTs: first.ts,
      endTs: last.ts + 60_000,
      processed: group.reduce((sum, row) => sum + row.processed, 0),
      valid: group.reduce((sum, row) => sum + row.valid, 0),
      failed: group.reduce((sum, row) => sum + row.failed, 0),
      excluded: group.reduce((sum, row) => sum + row.excluded, 0),
    });
  }
  return groups;
}

function displayedRows(run) {
  const all = sourceRows(run);
  let cumulative = { processed: 0, valid: 0, failed: 0, excluded: 0 };
  const cumulativeByIndex = all.map((row) => {
    cumulative = {
      processed: cumulative.processed + row.processed,
      valid: cumulative.valid + row.valid,
      failed: cumulative.failed + row.failed,
      excluded: cumulative.excluded + row.excluded,
    };
    return { ...cumulative };
  });

  const count = visibleBucketCount(run);
  const start = Math.max(0, all.length - count);
  const rows = aggregateRows(all.slice(start), Number(bucketMode));

  return rows.map((row) => ({
    ...row,
    cumulative: cumulativeByIndex[row.lastIndex] || cumulative,
    count: Number(bucketMode),
  }));
}

function rangeLabel(run, rows) {
  if (!rows.length) return "尚无时间桶";
  const first = new Date(rows[0].startTs);
  const last = new Date(rows[rows.length - 1].endTs);
  return `${formatClock(first)}–${formatClock(last)} · ${rows.length} 个 ${
    bucketMode === "5" ? "5 分钟" : "1 分钟"
  }桶`;
}

function analysisKpis(run) {
  const rows = displayedRows(run);
  const total = Math.max(0, run.counts.processed);
  const yieldRate = total ? run.counts.valid / total : 0;
  const failureRate = total ? run.counts.failed / total : 0;
  const throughput = run.runSeconds > 0 ? (total / run.runSeconds) * 60 : 0;
  const recent = rows.slice(-5);
  const recentProcessed = recent.reduce((sum, row) => sum + row.processed, 0);
  const recentMinutes = Math.max(1, recent.length);
  const recentThroughput = recentProcessed / recentMinutes;

  return `
    <div class="analysis-kpi">
      <span>运行时长</span>
      <strong>${formatDuration(run.runSeconds)}</strong>
      <small>${run.state === "RUNNING" ? "截至最近检查点" : "按运行检查点累计"}</small>
    </div>
    <div class="analysis-kpi">
      <span>平均吞吐</span>
      <strong>${formatDecimal(throughput)} <small style="display:inline;font-size:11px;font-weight:600">件/分钟</small></strong>
      <small>${run.state === "RUNNING" ? `最近 ${recentMinutes} 分钟 ${formatDecimal(recentThroughput)} 件/分钟` : "按运行时长计算，排除暂停"}</small>
    </div>
    <div class="analysis-kpi">
      <span>有效率</span>
      <strong>${formatPercent(yieldRate)}</strong>
      <small>${formatNumber(run.counts.valid)} / ${formatNumber(total)} 件</small>
    </div>
    <div class="analysis-kpi">
      <span>失败率</span>
      <strong>${formatPercent(failureRate)}</strong>
      <small>${formatNumber(run.counts.failed)} / ${formatNumber(total)} 件 · 失败项可下钻</small>
    </div>
  `;
}

function renderTaskHeader(run) {
  const primaryLabel =
    run.state === "RUNNING" ? "暂停任务" : run.state === "QUEUED" ? "取消任务" : "导出 ZIP";
  const primaryIcon =
    run.state === "QUEUED"
      ? '<path d="M4 4l8 8M12 4l-8 8" stroke-linecap="round" />'
      : run.state === "RUNNING"
        ? '<path d="M6 3.5v9M10 3.5v9" stroke-linecap="round" />'
        : '<path d="M8 2.5v8M5 7.5 8 10.5l3-3M3 13.5h10" stroke-linecap="round" stroke-linejoin="round" />';
  return `
    <a class="back-link" href="#/tasks" data-static-action="返回全部任务">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
        <path d="M13 8H3M7 4 3 8l4 4" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      返回全部任务
    </a>

    <header class="task-header">
      <div class="task-header-top">
        <span class="task-id">${escapeHtml(run.taskId)}</span>
        <span class="badge badge-info">${taskTypeLabel(run)}</span>
      </div>
      <div class="task-header-main">
        <div class="task-title-block">
          <div class="task-title-row">
            <h1 class="task-title">${escapeHtml(run.site)}</h1>
            <span class="badge badge-${stateTone(run)}">${stateLabel(run)}</span>
            ${
              run.outcomeLabel
                ? `<span class="badge badge-${run.outcome === "COMPLETED" ? "success" : "warning"}">${escapeHtml(run.outcomeLabel)}</span>`
                : ""
            }
          </div>
          <p class="task-meta">
            <span>规则 <code>${escapeHtml(run.rule)}</code></span>
            <span>市场 <strong>${escapeHtml(run.market)}</strong></span>
            <span>开始 <strong class="tabular">${formatDateTime(run.start)}</strong></span>
            <span>${run.end ? "结束" : "更新"} <strong class="tabular">${formatDateTime(run.end || run.observedAt)}</strong></span>
          </p>
        </div>
        <div class="task-actions">
          <button type="button" class="button button-primary" data-static-action="${primaryLabel}">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              ${primaryIcon}
            </svg>
            ${primaryLabel}
          </button>
          <button type="button" class="button button-icon" aria-label="更多操作" data-static-action="更多操作">
            <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
              <circle cx="3" cy="8" r="1.2" /><circle cx="8" cy="8" r="1.2" /><circle cx="13" cy="8" r="1.2" />
            </svg>
          </button>
        </div>
      </div>
    </header>
  `;
}

function renderSummary(run) {
  return `
    <dl class="summary-strip" aria-label="任务概览">
      <div class="summary-item">
        <dt>有效商品</dt>
        <dd>${formatNumber(run.counts.valid)}</dd>
        <small>处理后进入有效集</small>
      </div>
      <div class="summary-item">
        <dt>失败／排除</dt>
        <dd>${formatNumber(run.counts.failed)} / ${formatNumber(run.counts.excluded)}</dd>
        <small>技术失败与业务排除分开</small>
      </div>
      <div class="summary-item">
        <dt>覆盖</dt>
        <dd style="font-size:16px">${escapeHtml(run.coverage.label)}</dd>
        <small>${run.coverage.status === "PARTIAL" ? "不代表整站总量" : "尚未开始"}</small>
      </div>
      <div class="summary-item">
        <dt>质量异常</dt>
        <dd>0</dd>
        <small>本原型不展开质量反馈</small>
      </div>
    </dl>
  `;
}

function renderTabs(run) {
  const counts = {
    data: run.taskType === "discovery" ? run.counts.discovered : run.counts.valid + run.counts.failed,
    quality: 0,
    analysis: "",
    detail: "",
  };
  return `
    <div class="tabs-desktop" role="tablist" aria-label="任务视图">
      ${TABS.map(
        (tab) => `
        <button
          type="button"
          class="tab-button"
          role="tab"
          id="tab-${tab.key}"
          aria-selected="${activeView === tab.key}"
          aria-controls="panel-${tab.key}"
          tabindex="${activeView === tab.key ? "0" : "-1"}"
          data-view="${tab.key}"
        >
          ${tab.label}
          ${counts[tab.key] ? `<span class="tab-count">${formatNumber(counts[tab.key])}</span>` : ""}
        </button>
      `,
      ).join("")}
    </div>
    <div class="tabs-mobile">
      <label for="view-select">切换任务视图</label>
      <select class="select" id="view-select">
        ${TABS.map(
          (tab) => `<option value="${tab.key}" ${activeView === tab.key ? "selected" : ""}>${tab.label}</option>`,
        ).join("")}
      </select>
    </div>
  `;
}

function renderScope(run) {
  const live = run.state === "RUNNING";
  const statusText = live
    ? frozen
      ? "已冻结 · 3 个新时间桶"
      : "实时跟随"
    : run.state === "FINISHED"
      ? `数据截至 ${formatDateTime(run.observedAt)}`
      : "运行尚未开始";
  return `
    <div class="analysis-scope">
      <div class="scope-main">
        <div class="scope-kicker">
          <span class="live-dot ${frozen ? "is-frozen" : ""}" aria-hidden="true"></span>
          本次运行 · ${stateLabel(run)}
        </div>
        <div class="scope-title">
          <strong>运行分析</strong>
          <span>${statusText}</span>
        </div>
        <div class="scope-meta">
          <span>任务 <code>${escapeHtml(run.taskId)}</code></span>
          <span>规则 <code>${escapeHtml(run.rule)}</code></span>
          <span>数据源 <code>events.ndjson</code> · <code>task-result.json</code></span>
          <span>口径：单次运行，不合并历史任务</span>
        </div>
      </div>
      <div class="scope-controls">
        <label class="control-group">
          <span>窗口</span>
          <select class="select" data-window aria-label="分析时间窗口">
            <option value="full" ${windowMode === "full" ? "selected" : ""}>全程</option>
            <option value="30" ${windowMode === "30" ? "selected" : ""}>最近 30 分钟</option>
            <option value="15" ${windowMode === "15" ? "selected" : ""}>最近 15 分钟</option>
            <option value="5" ${windowMode === "5" ? "selected" : ""}>最近 5 分钟</option>
          </select>
        </label>
        <label class="control-group">
          <span>粒度</span>
          <select class="select" data-bucket aria-label="时间桶粒度">
            <option value="1" ${bucketMode === "1" ? "selected" : ""}>1 分钟</option>
            <option value="5" ${bucketMode === "5" ? "selected" : ""}>5 分钟</option>
          </select>
        </label>
        <div class="control-group">
          <span>显示</span>
          <div class="segmented" role="group" aria-label="曲线数值模式">
            <button type="button" data-chart-mode="rate" aria-pressed="${chartMode === "rate"}">速率</button>
            <button type="button" data-chart-mode="cumulative" aria-pressed="${chartMode === "cumulative"}">累计</button>
          </div>
        </div>
        ${
          live
            ? `<button type="button" class="button button-ghost" data-freeze>${frozen ? "回到实时" : "冻结视图"}</button>`
            : ""
        }
        <button type="button" class="icon-button" aria-label="刷新分析数据" data-refresh>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
            <path d="M13 8a5 5 0 1 1-1.5-3.5M13 3.5V7h-3.5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  `;
}

function renderDataNotice(run) {
  if (run.dataQuality.level !== "legacy") return "";
  return `
    <div class="notice is-info">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
        <circle cx="8" cy="8" r="6" /><path d="M8 7.2v4M8 4.8v.1" stroke-linecap="round" />
      </svg>
      <div>
        <strong>${escapeHtml(run.dataQuality.label)}</strong>
        <span>${escapeHtml(run.dataQuality.note)}</span>
      </div>
    </div>
  `;
}

function renderDiagnostic(run) {
  const item = run.diagnostics?.[0];
  if (!item) return "";
  return `
    <div class="notice ${item.tone === "info" ? "is-info" : ""}">
      ${
        item.tone === "info"
          ? `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="8" cy="8" r="6" /><path d="M8 7.2v4M8 4.8v.1" stroke-linecap="round" /></svg>`
          : `<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M8 2.5 14 13H2z" stroke-linejoin="round" /><path d="M8 6.2v3M8 11.4v.1" stroke-linecap="round" /></svg>`
      }
      <div>
        <strong>${escapeHtml(item.title)}</strong>
        <span>${escapeHtml(item.detail)}</span>
        ${item.action ? `<a href="#/tasks" data-static-action="${escapeHtml(item.action)}">${escapeHtml(item.action)} →</a>` : ""}
      </div>
    </div>
  `;
}

function renderLegend(run) {
  const totals = {
    processed: run.counts.processed,
    valid: run.counts.valid,
    failed: run.counts.failed,
  };
  return `
    <div class="legend-row" aria-label="曲线系列">
      ${Object.entries(SERIES)
        .map(
          ([key, meta]) => `
        <button
          type="button"
          class="legend-chip"
          style="color:${meta.color}"
          data-legend="${key}"
          aria-pressed="${visibleSeries.has(key)}"
        >
          <span class="swatch" aria-hidden="true"></span>
          <span>${meta.label}</span>
          <span class="legend-total">${formatNumber(totals[key])}</span>
        </button>
      `,
        )
        .join("")}
    </div>
  `;
}

function renderThroughputCard(run) {
  return `
    <article class="panel chart-panel" aria-labelledby="throughput-title">
      <div class="panel-head">
        <div class="panel-title">
          <h2 id="throughput-title">产出与失败</h2>
          <p>按时间桶聚合任务事件；失败包含商品校验、访问和传输失败。</p>
        </div>
        <div class="panel-actions">
          <span class="panel-stat">峰值 <strong data-peak>—</strong></span>
          <button type="button" class="text-button" data-table-toggle aria-expanded="false">数据表</button>
        </div>
      </div>
      ${renderLegend(run)}
      <div class="chart-wrap">
        <div class="chart" id="throughput-chart" role="img" aria-label="产出与失败随时间变化的曲线"></div>
      </div>
      <div class="chart-foot">
        <span data-range>—</span>
        <span><strong>速率</strong> 为每个时间桶的事件数；<strong>累计</strong> 为当前窗口结束时的累计值</span>
      </div>
      <div class="data-table-wrap" id="throughput-table-wrap" hidden>
        <table class="data-table" id="throughput-table">
          <caption>主图数据表；每行一个时间桶，作为图表的可访问替代。</caption>
        </table>
      </div>
    </article>
  `;
}

function renderFailureCard(run) {
  const total = run.counts.failed;
  const rows = run.failureReasons || [];
  const max = Math.max(1, ...rows.map((row) => row.count));
  const peaks = run.processed
    .map((_, index) => ({
      index,
      failed: run.failed[index] || 0,
      ts: new Date(run.start).getTime() + index * 60_000,
    }))
    .filter((row) => row.failed >= 4)
    .sort((left, right) => right.failed - left.failed)
    .slice(0, 3);
  return `
    <article class="panel chart-panel" aria-labelledby="failure-title">
      <div class="panel-head">
        <div class="panel-title">
          <h2 id="failure-title">失败构成</h2>
          <p>按商品级终态归纳；失败类别和原因来自任务事件与结果明细。</p>
        </div>
        <a class="text-button" href="#/tasks" data-static-action="查看失败项">查看失败项</a>
      </div>
      ${
        total
          ? `<div class="failure-list">
              ${rows
                .map(
                  (row) => `
                <div class="failure-row">
                  <div class="failure-label">
                    <span>${escapeHtml(row.label)}</span>
                    <code>${escapeHtml(row.code)}</code>
                  </div>
                  <span class="failure-count">${formatNumber(row.count)} · ${formatPercent(row.share)}</span>
                  <div class="failure-bar"><span style="width:${(row.count / max) * 100}%"></span></div>
                  <span class="failure-sample">样例：${escapeHtml(row.sampleUrl)}</span>
                </div>
              `,
                )
                .join("")}
            </div>`
          : `<p class="failure-empty">本次运行没有失败项。</p>`
      }
      ${
        peaks.length
          ? `<div class="failure-peaks">
              <span class="failure-peaks-label">失败高峰</span>
              ${peaks
                .map(
                  (peak) =>
                    `<span><strong>${formatClock(peak.ts)}</strong> · ${formatNumber(peak.failed)} 件</span>`,
                )
                .join("")}
            </div>`
          : ""
      }
      <div class="failure-foot">
        <span>失败 ${formatNumber(run.counts.failed)} / 处理 ${formatNumber(run.counts.processed)} · ${formatPercent(
          run.counts.processed ? run.counts.failed / run.counts.processed : 0,
        )}</span>
        <span>${run.dataQuality.level === "legacy" ? "旧运行：原因可能只保留到类别" : "原因来自 item 级终态"}</span>
      </div>
    </article>
  `;
}

function renderBudgetCard(run) {
  const counts = run.counts;
  const denominator = Math.max(1, counts.discovered || counts.candidates || 1);
  const rows = [
    { label: "发现网址", value: counts.discovered, className: "" },
    { label: "商品候选", value: counts.candidates, className: "" },
    { label: "已处理", value: counts.processed, className: "" },
    { label: "有效", value: counts.valid, className: "is-success" },
    { label: "失败", value: counts.failed, className: "is-danger" },
  ];
  const budgetRows = [
    {
      label: "商品数",
      used: run.budget.usedProducts,
      max: run.budget.maxProducts,
      format: formatNumber,
    },
    {
      label: "运行时长",
      used: run.budget.usedSeconds,
      max: run.budget.maxSeconds,
      format: formatDuration,
    },
    {
      label: "网址数",
      used: run.budget.usedUrls,
      max: run.budget.maxUrls,
      format: formatNumber,
    },
  ];
  return `
    <article class="panel chart-panel" aria-labelledby="budget-title">
      <div class="panel-head">
        <div class="panel-title">
          <h2 id="budget-title">发现与预算</h2>
          <p>漏斗使用本次运行的持久计数；覆盖只代表声明来源，不代表整站总量。</p>
        </div>
        <span class="badge ${run.coverage.status === "PARTIAL" ? "badge-warning" : "badge"}" style="align-self:center">${escapeHtml(run.coverage.label)}</span>
      </div>
      <div class="funnel">
        ${rows
          .map(
            (row) => `
          <div class="funnel-row">
            <span>${row.label}</span>
            <div class="funnel-track ${row.className}"><span style="width:${Math.min(100, (row.value / denominator) * 100)}%"></span></div>
            <strong>${formatNumber(row.value)}</strong>
          </div>
        `,
          )
          .join("")}
      </div>
      <div class="funnel-legend">
        <span style="color:var(--accent)"><i></i>发现与候选</span>
        <span style="color:var(--success)"><i></i>有效</span>
        <span style="color:var(--danger)"><i></i>失败</span>
        <span>处理 ${formatNumber(run.counts.processed)} / 候选 ${formatNumber(run.counts.candidates)}</span>
      </div>
      <div class="budget-list">
        ${budgetRows
          .map((row) => {
            const unlimited = row.max == null;
            const ratio = unlimited ? 0 : Math.min(1, row.used / Math.max(1, row.max));
            return `
            <div class="budget-row">
              <span>${row.label}</span>
              <div class="budget-track ${unlimited ? "is-unlimited" : ratio >= 0.9 ? "is-warning" : ""}"><span style="width:${ratio * 100}%"></span></div>
              <strong>${row.format(row.used)}${unlimited ? " / 不设限" : ` / ${row.format(row.max)}`}</strong>
            </div>
          `;
          })
          .join("")}
      </div>
      <p class="budget-note">${
        run.state === "RUNNING"
          ? `待采 ${formatNumber(run.counts.pending)} 件；吞吐按运行检查点计算，不提供 ETA。`
          : "本次运行已结束；预算不设限时按规则声明范围自然结束。"
      }</p>
    </article>
  `;
}

function renderAnalysisPanel(run) {
  if (run.state === "QUEUED") {
    return `
      <section class="analysis-panel" id="panel-analysis" role="tabpanel" aria-labelledby="tab-analysis">
        <div class="empty-state">
          <span class="empty-icon" aria-hidden="true">
            <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6">
              <path d="M3 16.5h14M4.5 14V9l3 2 2.5-5 2.5 4 3-3v7" stroke-linecap="round" stroke-linejoin="round" />
              <circle cx="10" cy="10" r="8" opacity=".25" />
            </svg>
          </span>
          <h2>运行尚未开始</h2>
          <p>排队中的任务还没有可分析的时间桶。启动并产生第一批结果后，这里会显示产出、失败、发现和预算。</p>
          <button type="button" class="button button-primary" data-static-action="返回工作台">返回工作台</button>
        </div>
      </section>
    `;
  }

  return `
    <section class="analysis-panel" id="panel-analysis" role="tabpanel" aria-labelledby="tab-analysis">
      ${renderScope(run)}
      <div class="analysis-kpis" aria-label="分析摘要">${analysisKpis(run)}</div>
      ${renderDataNotice(run)}
      ${renderDiagnostic(run)}
      ${renderThroughputCard(run)}
      <div class="analysis-grid">
        ${renderFailureCard(run)}
        ${renderBudgetCard(run)}
      </div>
    </section>
  `;
}

function renderPlaceholder(view) {
  const labels = {
    data: "数据明细",
    quality: "质量与验收",
    detail: "运行明细",
  };
  return `
    <section class="analysis-panel" id="panel-${view}" role="tabpanel" aria-labelledby="tab-${view}">
      <div class="empty-state">
        <span class="empty-icon" aria-hidden="true">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M4 4.5h12v11H4zM7 8h6M7 11h4" stroke-linecap="round" />
          </svg>
        </span>
        <h2>${labels[view]}</h2>
        <p>本原型只展开「运行分析」；这个视图沿用当前任务详情的现有内容，不在本轮调整范围内。</p>
        <button type="button" class="button button-primary" data-view="analysis">查看运行分析</button>
      </div>
    </section>
  `;
}

function render() {
  disposeCharts();
  const run = runs[stateKey];
  const main = activeView === "analysis" ? renderAnalysisPanel(run) : renderPlaceholder(activeView);
  page.innerHTML = `
    ${renderTaskHeader(run)}
    ${renderSummary(run)}
    ${renderTabs(run)}
    ${main}
  `;

  document.querySelectorAll("[data-run-state]").forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.runState === stateKey));
  });

  bindPageEvents();
  if (activeView === "analysis" && run.state !== "QUEUED") {
    requestAnimationFrame(() => {
      initCharts(run);
      updateChartPresentation(run);
    });
  }
}

function bindPageEvents() {
  page.onclick = (event) => {
    const target = event.target.closest("button, a");
    if (!target) return;
    const view = target.dataset.view;
    if (view) {
      activeView = view;
      updateUrl();
      render();
      return;
    }
    if (target.dataset.staticAction) {
      event.preventDefault();
      showToast(`${target.dataset.staticAction}：静态原型不执行写入。`);
      return;
    }
    if (target.dataset.chartMode) {
      chartMode = target.dataset.chartMode;
      document.querySelectorAll("[data-chart-mode]").forEach((button) => {
        button.setAttribute("aria-pressed", String(button.dataset.chartMode === chartMode));
      });
      updateCharts(runs[stateKey]);
      return;
    }
    if (target.dataset.legend) {
      const key = target.dataset.legend;
      if (visibleSeries.has(key) && visibleSeries.size === 1) {
        showToast("至少保留一条曲线；用图例切换其他系列。");
        return;
      }
      if (visibleSeries.has(key)) visibleSeries.delete(key);
      else visibleSeries.add(key);
      target.setAttribute("aria-pressed", String(visibleSeries.has(key)));
      updateCharts(runs[stateKey]);
      return;
    }
    if (target.dataset.tableToggle !== undefined) {
      const wrap = document.querySelector("#throughput-table-wrap");
      if (!wrap) return;
      const next = wrap.hidden;
      wrap.hidden = !next;
      target.setAttribute("aria-expanded", String(next));
      target.textContent = next ? "收起数据表" : "数据表";
      return;
    }
    if (target.dataset.freeze !== undefined) {
      frozen = !frozen;
      renderScopeOnly(runs[stateKey]);
      return;
    }
    if (target.dataset.refresh !== undefined) {
      target.disabled = true;
      target.classList.add("is-loading");
      window.setTimeout(() => {
        target.disabled = false;
        target.classList.remove("is-loading");
        showToast("分析数据已刷新（原型）。");
      }, 420);
      return;
    }
  };

  page.onchange = (event) => {
    const target = event.target;
    if (target.matches("[data-window]")) {
      windowMode = target.value;
      updateCharts(runs[stateKey]);
      return;
    }
    if (target.matches("[data-bucket]")) {
      bucketMode = target.value;
      updateCharts(runs[stateKey]);
      return;
    }
    if (target.id === "view-select") {
      activeView = target.value;
      updateUrl();
      render();
    }
  };
}

function renderScopeOnly(run) {
  const scope = document.querySelector(".analysis-scope");
  if (!scope) return;
  scope.outerHTML = renderScope(run);
  bindPageEvents();
}

function updateCharts(run) {
  const rows = displayedRows(run);
  const throughput = charts.get("throughput");
  if (throughput) {
    throughput.setOption(throughputOption(run, rows), { notMerge: true, lazyUpdate: true });
  }
  updateChartPresentation(run, rows);
}

function updateChartPresentation(run, rows = displayedRows(run)) {
  const range = document.querySelector("[data-range]");
  if (range) range.textContent = rangeLabel(run, rows);
  const peak = document.querySelector("[data-peak]");
  if (peak) {
    const values = rows.map((row) => row.processed);
    peak.textContent = values.length ? `${formatNumber(Math.max(...values))} 件/分钟` : "—";
  }
  const table = document.querySelector("#throughput-table");
  if (table) renderTable(table, rows);
}

function renderTable(table, rows) {
  table.innerHTML = `
    <caption>主图数据表；每行一个时间桶，作为图表的可访问替代。</caption>
    <thead>
      <tr>
        <th scope="col">时间</th>
        <th scope="col">处理</th>
        <th scope="col">有效</th>
        <th scope="col">失败</th>
        <th scope="col">失败率</th>
      </tr>
    </thead>
    <tbody>
      ${rows
        .map(
          (row) => `
        <tr>
          <td>${formatDateTime(new Date(row.ts).toISOString())}</td>
          <td>${formatNumber(chartMode === "cumulative" ? row.cumulative.processed : row.processed)}</td>
          <td>${formatNumber(chartMode === "cumulative" ? row.cumulative.valid : row.valid)}</td>
          <td>${formatNumber(chartMode === "cumulative" ? row.cumulative.failed : row.failed)}</td>
          <td>${formatPercent(
            (chartMode === "cumulative" ? row.cumulative.processed : row.processed)
              ? (chartMode === "cumulative" ? row.cumulative.failed : row.failed) /
                  (chartMode === "cumulative" ? row.cumulative.processed : row.processed)
              : 0,
          )}</td>
        </tr>
      `,
        )
        .join("")}
    </tbody>
  `;
}

function themeColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name) => style.getPropertyValue(name).trim();
  return {
    ink: read("--ink"),
    ink2: read("--ink-2"),
    ink3: read("--ink-3"),
    line: read("--line"),
    lineStrong: read("--line-strong"),
    surface: read("--surface"),
    accent: read("--accent"),
    success: read("--success"),
    danger: read("--danger"),
    warning: read("--warning"),
    info: read("--info"),
  };
}

function chartBase() {
  return {
    animation: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    animationDuration: 220,
    animationDurationUpdate: 120,
    textStyle: {
      fontFamily: getComputedStyle(document.body).fontFamily,
      color: themeColors().ink3,
      fontSize: 11,
    },
  };
}

function xAxisBase(rows) {
  const colors = themeColors();
  return {
    type: "time",
    boundaryGap: false,
    axisLine: { lineStyle: { color: colors.lineStrong } },
    axisTick: { show: false },
    axisLabel: {
      color: colors.ink3,
      fontSize: 10,
      hideOverlap: true,
      showMinLabel: true,
      showMaxLabel: true,
      formatter: (value) => formatClock(value),
    },
    splitLine: { show: false },
    min: rows.length ? rows[0].startTs : undefined,
    max: rows.length ? rows[rows.length - 1].endTs : undefined,
  };
}

function yAxisBase(name) {
  const colors = themeColors();
  return {
    type: "value",
    name,
    nameTextStyle: { color: colors.ink3, fontSize: 10, padding: [0, 0, 0, 4] },
    min: 0,
    minInterval: 1,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: {
      color: colors.ink3,
      fontSize: 10,
      formatter: (value) => (value >= 1000 ? `${Math.round(value / 1000)}k` : value),
    },
    splitLine: {
      lineStyle: { color: colors.line, type: [3, 3] },
    },
  };
}

function tooltipBase() {
  const colors = themeColors();
  return {
    trigger: "axis",
    confine: true,
    backgroundColor: colors.surface,
    borderColor: colors.lineStrong,
    borderWidth: 1,
    padding: [8, 10],
    textStyle: { color: colors.ink, fontSize: 11, lineHeight: 18 },
    extraCssText: "border-radius:8px;box-shadow:0 10px 24px rgb(16 24 32 / 14%);",
    axisPointer: {
      type: "line",
      lineStyle: { color: colors.lineStrong, type: "dashed" },
    },
  };
}

function seriesData(rows, key) {
  return rows.map((row) => [
    row.ts,
    chartMode === "cumulative" ? row.cumulative[key] : row[key],
  ]);
}

function throughputOption(run, rows) {
  const colors = themeColors();
  const seriesColors = {
    processed: colors.accent,
    valid: colors.success,
    failed: colors.danger,
  };
  const compact = window.innerWidth < 700;
  const visible = Object.entries(SERIES).filter(([key]) => visibleSeries.has(key));
  const yName = chartMode === "cumulative" ? "累计件" : "件/分钟";

  return {
    ...chartBase(),
    color: visible.map(([key]) => seriesColors[key]),
    grid: {
      left: compact ? 42 : 50,
      right: 16,
      top: 18,
      bottom: rows.length > 24 && !compact ? 48 : 26,
    },
    tooltip: {
      ...tooltipBase(),
      formatter: (params) => {
        if (!params?.length) return "";
        const row = rows[params[0].dataIndex];
        if (!row) return "";
        const value = (key) =>
          chartMode === "cumulative" ? row.cumulative[key] : row[key];
        return [
          `<div style="margin-bottom:4px;color:${colors.ink3}">${formatDateTime(new Date(row.ts).toISOString())}</div>`,
          `<div style="display:flex;justify-content:space-between;gap:18px"><span><i style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${colors.accent};margin-right:6px"></i>处理</span><strong>${formatNumber(value("processed"))}</strong></div>`,
          `<div style="display:flex;justify-content:space-between;gap:18px"><span><i style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${colors.success};margin-right:6px"></i>有效</span><strong>${formatNumber(value("valid"))}</strong></div>`,
          `<div style="display:flex;justify-content:space-between;gap:18px"><span><i style="display:inline-block;width:7px;height:7px;border-radius:50%;background:${colors.danger};margin-right:6px"></i>失败</span><strong>${formatNumber(value("failed"))}</strong></div>`,
        ].join("");
      },
    },
    xAxis: xAxisBase(rows),
    yAxis: yAxisBase(yName),
    dataZoom:
      rows.length > 24 && !compact
        ? [
            {
              type: "slider",
              height: 20,
              bottom: 4,
              borderColor: "transparent",
              backgroundColor: colors.surface,
              fillerColor: "rgba(31, 92, 74, 0.12)",
              handleStyle: { color: colors.accent },
              moveHandleStyle: { color: colors.accent },
              showDetail: false,
              brushSelect: false,
            },
            { type: "inside", zoomOnMouseWheel: false, moveOnMouseMove: true },
          ]
        : [],
    series: visible.map(([key, meta]) => ({
      name: meta.label,
      type: "line",
      data: seriesData(rows, key),
      showSymbol: rows.length <= 32,
      symbol: "circle",
      symbolSize: 4,
      smooth: false,
      connectNulls: false,
      z: key === "valid" ? 4 : key === "failed" ? 3 : 2,
      lineStyle: {
        width: key === "valid" ? 2.4 : key === "failed" ? 1.8 : 0.8,
        type: key === "failed" ? [5, 4] : "solid",
        color: seriesColors[key],
      },
      itemStyle: { color: seriesColors[key] },
      areaStyle:
        key === "processed"
          ? { color: seriesColors[key], opacity: 0.075 }
          : undefined,
      emphasis: { focus: "series" },
    })),
  };
}

function initCharts(run) {
  if (!window.echarts) {
    document.querySelectorAll(".chart").forEach((node) => {
      node.innerHTML =
        '<div class="chart-fallback">图表库未加载。原型随仓库提供 ECharts 6.1.0 的本地构建，请检查 vendor/echarts.min.js。</div>';
    });
    return;
  }
  const throughput = document.querySelector("#throughput-chart");
  if (throughput) {
    const chart = window.echarts.init(throughput, null, {
      renderer: "canvas",
      useDirtyRect: true,
    });
    charts.set("throughput", chart);
    chart.setOption(throughputOption(run, displayedRows(run)), { notMerge: true });
  }
}

function disposeCharts() {
  charts.forEach((chart) => chart.dispose());
  charts.clear();
}

function updateUrl() {
  const next = new URLSearchParams(location.search);
  next.set("state", stateKey);
  next.set("view", activeView);
  if (document.documentElement.dataset.chrome === "0") next.set("chrome", "0");
  history.replaceState(null, "", `${location.pathname}?${next.toString()}${location.hash}`);
}

function showToast(message) {
  window.clearTimeout(toastTimer);
  toast.innerHTML = `<strong>${escapeHtml(message.split("：")[0])}</strong>${message.includes("：") ? `：${escapeHtml(message.split("：").slice(1).join("："))}` : ""}`;
  toast.hidden = false;
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
  }, 2600);
}

function bindGlobalControls() {
  document.querySelectorAll("[data-run-state]").forEach((button) => {
    button.addEventListener("click", () => {
      const next = button.dataset.runState;
      if (!runs[next]) return;
      stateKey = next;
      activeView = "analysis";
      frozen = false;
      windowMode = next === "running" ? "15" : "full";
      bucketMode = "1";
      chartMode = "rate";
      visibleSeries = new Set(["processed", "valid", "failed"]);
      updateUrl();
      render();
    });
  });

  document.querySelector("#hide-chrome").addEventListener("click", () => {
    document.documentElement.dataset.chrome = "0";
    updateUrl();
  });

  window.addEventListener("resize", () => {
    charts.forEach((chart) => chart.resize());
  });
}

bindGlobalControls();
render();
