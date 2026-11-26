const timelineEl = document.querySelector("#timeline");
const scrollEl = document.querySelector("#session-scroll");
const followButton = document.querySelector("#follow-button");
const followCount = document.querySelector("#follow-count");
const followCheckbox = document.querySelector("#follow-checkbox");
const liveBadge = document.querySelector("#live-badge");
const buildStateBadge = document.querySelector("#build-state-badge");
const chatValidation = document.querySelector("#chat-validation");
const chatElapsed = document.querySelector("#chat-elapsed");
const toast = document.querySelector("#toast");
const composerInput = document.querySelector("#composer-input");
const sendButton = document.querySelector("#send-button");
const composerStats = document.querySelector("#composer-stats");
const pauseButton = document.querySelector("#pause-button");
const traceBody = document.querySelector("#trace-body");
const tracePanel = document.querySelector("#trace-panel");
const chatTabs = document.querySelectorAll(".chat-tab");

const state = {
  scenario: "running",
  autoFollow: true,
  follow: true,
  unseen: 0,
  pendingApproval: null,
  parts: [],
  build: {
    id: "build-6e2e0388a6f9",
    site: "bennytex.com",
    state: "RUNNING",
    elapsed: "04:12",
    validation: "等待中",
  },
};

let streamTimer = null;
let actionTimers = [];
let appendIndex = 0;

function escapeHtml(value) {
  return String(value ?? "").replace(
    /[&<>"']/g,
    (char) =>
      ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
      })[char],
  );
}

function nowTime() {
  return new Date().toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function allTools() {
  return state.parts
    .filter((part) => part.kind === "activity")
    .flatMap((part) => part.tools);
}

function findTool(partId, toolId) {
  const part = state.parts.find((item) => item.id === partId);
  return part?.tools?.find((tool) => tool.id === toolId) ?? null;
}

function toolStatusLabel(status) {
  return (
    {
      pending: "等待中",
      running: "执行中",
      success: "成功",
      failed: "失败",
      cancelled: "已取消",
    }[status] ?? status
  );
}

function toolStatusClass(status) {
  if (status === "running") return "badge-info";
  if (status === "failed" || status === "cancelled") return "badge-warning";
  if (status === "pending") return "badge";
  return "badge-success";
}

function initialParts() {
  return [
    {
      id: "task-1",
      kind: "task",
      open: false,
      title: "构建任务",
      summary: "bennytex.com · FR · EUR · 单品规则",
      text:
        "目标：为新站接入单品采集规则。\n" +
        "范围：入口页、分类页和单品页；先验证 6 件，再按实际候选解释覆盖。\n" +
        "约束：只使用允许的访问方式；不抓取推荐商品；不把库存作为通过条件。\n" +
        "（原型中的任务说明已脱敏并截断。）",
    },
    {
      id: "context-1",
      kind: "context",
      open: false,
      summary: "任务简报 · 采集 Skill · 时间与市场",
      items: [
        { label: "任务简报", text: "站点、市场、目标与约束（已脱敏）" },
        {
          label: "采集 Skill",
          text: "product-crawl-workflow · resilient-browser-fetch",
        },
        { label: "时间与市场", text: "2026-11-26 · FR · EUR" },
      ],
    },
    { id: "turn-1", kind: "turn", label: "10:31 · 首次接入" },
    {
      id: "reasoning-1",
      kind: "reasoning",
      open: true,
      streaming: true,
      created_at: "10:31:02",
      text:
        "先确认入口页可访问，再检查商品 JSON-LD 和分页。价格优先取 offers.price，币种按批次市场映射；描述需要排除推荐商品块。",
    },
    {
      id: "activity-1",
      kind: "activity",
      open: true,
      tools: [
        {
          id: "tool-1",
          name: "webfetch",
          status: "success",
          summary: "GET https://bennytex.com/",
          duration: "1.4s",
          input: "GET https://bennytex.com/\nAccept: text/html",
          output: "HTTP 200 · 128 KB\n<title>Bennytex</title>\nProduct JSON-LD: 1 block",
          open: false,
        },
        {
          id: "tool-2",
          name: "read",
          status: "success",
          summary: "runtime/extract.py",
          duration: "0.2s",
          input: "path: runtime/extract.py\nlimit: 120",
          output: "已读取 120 行（原型省略正文）。",
          open: false,
        },
        {
          id: "tool-3",
          name: "shell",
          status: "running",
          summary: "python -m uv run --project app ...",
          duration: "—",
          input: "command: python -m uv run --project app ecom-crawler validate ...",
          output: "",
          open: false,
        },
      ],
    },
    {
      id: "text-1",
      kind: "text",
      role: "assistant",
      streaming: false,
      created_at: "10:31:18",
      text:
        "入口页可访问。已找到商品 JSON-LD，正在检查分页和价格字段。\n\n" +
        "```yaml\n" +
        "product_source: json_ld\n" +
        "price_path: offers.price\n" +
        "currency: market\n" +
        "```",
    },
    {
      id: "notice-1",
      kind: "notice",
      tone: "warning",
      title: "规则写入完成，等待主机验证",
      text: "主机将执行 6 件样本验证；结果会追加到时间线。",
      created_at: "10:31:22",
    },
  ];
}

function finishedParts() {
  const parts = initialParts();
  parts.splice(3, 0, {
    id: "work-1",
    kind: "work",
    open: false,
    duration: "03:36",
    steps: 4,
    tools: 3,
    validation: "通过 6/6",
    tokens: "12.4k",
  });
  const reasoning = parts.find((part) => part.id === "reasoning-1");
  reasoning.streaming = false;
  reasoning.open = false;
  reasoning.duration = "18s";
  reasoning.text +=
    " 入口页和分页确认完毕；价格、币种和描述块已覆盖，准备交给主机验证。";
  const activity = parts.find((part) => part.id === "activity-1");
  activity.open = false;
  activity.tools.forEach((tool) => {
    tool.status = "success";
    tool.duration = tool.duration === "—" ? "2.8s" : tool.duration;
    if (tool.id === "tool-3") {
      tool.output = "6/6 products valid\n0 failures\ncontent_audit: 0 gaps";
    }
  });
  const text = parts.find((part) => part.id === "text-1");
  text.text =
    "页面结构确认完毕，已写入候选规则并完成主机验证。\n\n" +
    "验证结果：6/6 有效，0 失败，价格与币种一致。候选 `2026.11.26-1` 已安装。";
  parts.push({
    id: "notice-2",
    kind: "notice",
    tone: "success",
    title: "主机验证通过 6/6",
    text: "0 失败，0 质量异常；候选规则 2026.11.26-1 已安装。",
    created_at: "10:34:48",
  });
  parts.push({
    id: "notice-3",
    kind: "notice",
    tone: "info",
    title: "构建已结束",
    text: "会话保留为只读复盘；完整内容可从 trace 下载。",
    created_at: "10:34:49",
  });
  return parts;
}

function approvalParts() {
  const parts = initialParts();
  const reasoning = parts.find((part) => part.id === "reasoning-1");
  reasoning.streaming = false;
  reasoning.open = false;
  reasoning.duration = "18s";
  reasoning.text += " 页面检查完成，下一步需要执行主机验证脚本。";
  const activity = parts.find((part) => part.id === "activity-1");
  activity.open = true;
  const shell = activity.tools.find((tool) => tool.id === "tool-3");
  shell.status = "pending";
  shell.output = "";
  const text = parts.find((part) => part.id === "text-1");
  text.text = "页面结构已确认。执行主机验证前需要一次审批，批准后才会运行命令。";
  parts.splice(parts.length - 1, 0, {
    id: "approval-1",
    kind: "approval",
    approval: {
      request_id: "per_demo_01",
      kind: "权限",
      action: "执行 shell 命令",
      resource: "python -m uv run --project app ecom-crawler validate ...",
      reason: "主机验证需要运行本地校验脚本；批准一次后执行。",
    },
  });
  return parts;
}

function resetScenario(name) {
  stopStreaming();
  clearActionTimers();
  state.scenario = name;
  state.pendingApproval = null;
  state.build.state = name === "finished" ? "FINISHED" : "RUNNING";
  state.build.validation = name === "finished" ? "通过 6/6" : "等待中";
  state.build.elapsed = name === "finished" ? "03:36" : "04:12";
  state.parts =
    name === "finished"
      ? finishedParts()
      : name === "approval"
        ? approvalParts()
        : initialParts();
  if (name === "approval") {
    state.pendingApproval =
      state.parts.find((part) => part.kind === "approval")?.approval ?? null;
  }
  state.follow = true;
  state.unseen = 0;
  state.autoFollow = true;
  followCheckbox.checked = true;
  composerInput.value = "";
  setSessionView("conversation");
  render({ reset: true });
  if (name === "running") startStreaming();
}

function startStreaming() {
  const phrases = [
    "入口页返回 200。",
    "商品 JSON-LD 存在，名称和价格可读。",
    "分页使用 /collections/all?page=2。",
    "价格字段在 offers.price，币种需要按市场映射。",
    "描述块需要合并两个节点，并排除推荐商品。",
    "正在检查变体和主图字段。",
  ];
  let index = 0;
  streamTimer = window.setInterval(() => {
    const reasoning = state.parts.find((part) => part.id === "reasoning-1");
    if (!reasoning || !reasoning.streaming) {
      stopStreaming();
      return;
    }
    if (index >= phrases.length) {
      reasoning.streaming = false;
      if (!state.parts.some((part) => part.id === "text-2")) {
        state.parts.push({
          id: "text-2",
          kind: "text",
          role: "assistant",
          streaming: false,
          created_at: nowTime(),
          text:
            "页面结构确认完毕，正在写入规则并准备主机验证。\n\n" +
            "```yaml\nstatus: candidate\nversion: 2026.11.26-1\n```",
        });
      }
      render({ newContent: true });
      stopStreaming();
      return;
    }
    reasoning.text += " " + phrases[index];
    index += 1;
    render({ newContent: true });
  }, 1200);
}

function stopStreaming() {
  if (streamTimer !== null) {
    window.clearInterval(streamTimer);
    streamTimer = null;
  }
}

function clearActionTimers() {
  actionTimers.forEach((timer) => window.clearTimeout(timer));
  actionTimers = [];
}

function schedule(fn, delay) {
  const timer = window.setTimeout(() => {
    actionTimers = actionTimers.filter((item) => item !== timer);
    fn();
  }, delay);
  actionTimers.push(timer);
}

function renderTextBody(text) {
  const chunks = escapeHtml(text).split("```");
  const output = chunks
    .map((chunk, index) => {
      if (index % 2 === 1) {
        const body = chunk.replace(/^\n/, "").replace(/\n$/, "");
        return `<pre><code>${body}</code></pre>`;
      }
      const body = chunk.replace(/\n/g, "<br>");
      return body.trim() ? `<p>${body}</p>` : "";
    })
    .filter(Boolean)
    .join("");
  return output || "<p></p>";
}

function toolIcon(name) {
  if (name === "shell") return "$";
  if (name === "webfetch") return "↧";
  if (name === "read") return "≡";
  if (name === "write" || name === "edit" || name === "patch") return "✎";
  if (name === "grep" || name === "glob") return "⌕";
  return "⌘";
}

function renderTask(part) {
  const open = Boolean(part.open);
  return `<li class="row">
    <button class="row-head" type="button" data-action="toggle-part" data-id="${part.id}" aria-expanded="${open}">
      <span class="row-icon" aria-hidden="true">☰</span>
      <span class="row-title">${escapeHtml(part.title)}</span>
      <span class="row-subject">${escapeHtml(part.summary)}</span>
      <span class="row-meta"><span class="badge">已发送</span></span>
      <span class="row-chevron" aria-hidden="true">▸</span>
    </button>
    ${open ? `<div class="row-content task-text">${escapeHtml(part.text)}</div>` : ""}
  </li>`;
}

function renderReasoning(part) {
  const open = Boolean(part.open);
  const streaming = Boolean(part.streaming);
  return `<li class="row">
    <button class="row-head" type="button" data-action="toggle-part" data-id="${part.id}" aria-expanded="${open}">
      <span class="row-icon row-icon-thinking" aria-hidden="true">✦</span>
      <span class="row-title">思考</span>
      <span class="row-subject">${streaming ? "正在思考…" : "已完成"}</span>
      <span class="row-meta">
        ${streaming ? '<span class="spinner" aria-hidden="true"></span>' : part.duration ? `<span>${escapeHtml(part.duration)}</span>` : ""}
        ${part.created_at ? `<span>${escapeHtml(part.created_at)}</span>` : ""}
      </span>
      <span class="row-chevron" aria-hidden="true">▸</span>
    </button>
    ${
      open
        ? `<div class="row-content reasoning-text">${escapeHtml(part.text)}${
            streaming ? '<span class="cursor" aria-hidden="true"></span>' : ""
          }</div>`
        : ""
    }
  </li>`;
}

function renderTool(tool, partId) {
  const open = Boolean(tool.open);
  const running = tool.status === "running";
  return `<div class="tool-row">
    <button class="row-head tool-head" type="button" data-action="toggle-tool" data-part-id="${partId}" data-tool-id="${tool.id}" aria-expanded="${open}">
      <span class="row-icon" aria-hidden="true">${toolIcon(tool.name)}</span>
      <span class="row-title">${escapeHtml(tool.name)}</span>
      <span class="row-subject">${escapeHtml(tool.summary)}</span>
      <span class="row-meta">
        ${running ? '<span class="spinner" aria-hidden="true"></span>' : ""}
        <span class="badge ${toolStatusClass(tool.status)}">${toolStatusLabel(tool.status)}</span>
        ${tool.duration ? `<span>${escapeHtml(tool.duration)}</span>` : ""}
      </span>
      <span class="row-chevron" aria-hidden="true">▸</span>
    </button>
    ${
      open
        ? `<div class="row-content tool-detail">
            ${
              tool.input
                ? `<div class="tool-detail-block"><span class="tool-detail-label">入参</span><pre class="code">${escapeHtml(tool.input)}</pre></div>`
                : ""
            }
            ${
              tool.output
                ? `<div class="tool-detail-block"><span class="tool-detail-label">输出</span><pre class="code console">${escapeHtml(tool.output)}</pre></div>`
                : running
                  ? `<div class="tool-detail-block"><span class="tool-detail-label">输出</span><p class="muted small">等待工具返回…</p></div>`
                  : ""
            }
          </div>`
        : ""
    }
  </div>`;
}

function renderActivity(part) {
  const open = Boolean(part.open);
  const tools = part.tools;
  const running = tools.filter((tool) => tool.status === "running").length;
  const pending = tools.filter((tool) => tool.status === "pending").length;
  const failed = tools.filter((tool) => tool.status === "failed").length;
  const statusText = running
    ? `${running} 个执行中`
    : pending
      ? `${pending} 个等待中`
      : failed
        ? `${failed} 个失败`
        : "已完成";
  const statusClass = running
    ? "badge-info"
    : failed
      ? "badge-warning"
      : pending
        ? "badge"
        : "badge-success";
  return `<li class="row">
    <button class="row-head" type="button" data-action="toggle-part" data-id="${part.id}" aria-expanded="${open}">
      <span class="row-icon" aria-hidden="true">⌘</span>
      <span class="row-title">工具活动</span>
      <span class="row-subject">${escapeHtml(
        tools
          .slice(0, 3)
          .map((tool) => tool.name)
          .join(" · "),
      )}${tools.length > 3 ? " …" : ""}</span>
      <span class="row-meta">
        <span class="badge ${statusClass}">${statusText}</span>
        <span>${tools.length} 次</span>
      </span>
      <span class="row-chevron" aria-hidden="true">▸</span>
    </button>
    ${open ? `<div class="row-content activity-list">${tools.map((tool) => renderTool(tool, part.id)).join("")}</div>` : ""}
  </li>`;
}

function renderText(part) {
  if (part.role === "user") {
    return `<li class="user-row">
      <div class="user-bubble">${renderTextBody(part.text)}</div>
      <div class="user-meta">你${part.created_at ? ` · ${escapeHtml(part.created_at)}` : ""}</div>
    </li>`;
  }
  if (part.role === "system") {
    return `<li class="notice-line notice-info">
      <span class="notice-icon" aria-hidden="true">i</span>
      <div class="notice-copy">${renderTextBody(part.text)}</div>
    </li>`;
  }
  return `<li class="assistant-row">
    <div class="assistant-text">${renderTextBody(part.text)}${
      part.streaming ? '<span class="cursor" aria-hidden="true"></span>' : ""
    }</div>
  </li>`;
}

function renderNotice(part) {
  const icon = part.tone === "success" ? "✓" : part.tone === "danger" ? "!" : "i";
  return `<li class="notice-line notice-${part.tone}">
    <span class="notice-icon" aria-hidden="true">${icon}</span>
    <div class="notice-copy">
      <strong>${escapeHtml(part.title)}</strong>
      ${part.text ? `<p>${escapeHtml(part.text)}</p>` : ""}
    </div>
    ${part.created_at ? `<span class="notice-time">${escapeHtml(part.created_at)}</span>` : ""}
  </li>`;
}

function renderApprovalPart(part) {
  const approval = part.approval;
  return `<li class="approval-line">
    <div class="approval-card">
      <div class="approval-head">
        <span class="approval-icon" aria-hidden="true">!</span>
        <div>
          <h2>等待审批</h2>
          <p>批准后才会执行；拒绝会取消本次请求。</p>
        </div>
      </div>
      <div class="approval-request">
        <span class="badge badge-warning">${escapeHtml(approval.kind)}</span>
        <div class="request-copy">
          <strong>${escapeHtml(approval.action)}</strong>
          <span>${escapeHtml(approval.resource ?? "")}</span>
          <span>${escapeHtml(approval.reason ?? "")}</span>
        </div>
        <div class="request-actions">
          <button class="button button-sm button-primary" type="button" data-approval="approve">批准一次</button>
          <button class="button button-sm button-danger" type="button" data-approval="reject">拒绝</button>
        </div>
      </div>
    </div>
  </li>`;
}

function renderContext(part) {
  const open = Boolean(part.open);
  return `<li class="row">
    <button class="row-head" type="button" data-action="toggle-part" data-id="${part.id}" aria-expanded="${open}">
      <span class="row-icon" aria-hidden="true">◈</span>
      <span class="row-title">上下文</span>
      <span class="row-subject">${escapeHtml(part.summary)}</span>
      <span class="row-meta">${part.items.length} 项</span>
      <span class="row-chevron" aria-hidden="true">▸</span>
    </button>
    ${
      open
        ? `<div class="row-content context-list">${part.items
            .map(
              (item) =>
                `<div class="context-item"><span class="context-chip">${escapeHtml(item.label)}</span><span>${escapeHtml(item.text)}</span></div>`,
            )
            .join("")}</div>`
        : ""
    }
  </li>`;
}

function renderWork(part) {
  const open = Boolean(part.open);
  return `<li class="row">
    <button class="row-head" type="button" data-action="toggle-part" data-id="${part.id}" aria-expanded="${open}">
      <span class="row-icon row-icon-success" aria-hidden="true">✓</span>
      <span class="row-title">已完成</span>
      <span class="row-subject">用时 ${escapeHtml(part.duration)}</span>
      <span class="row-meta">${part.steps} 步 · ${part.tools} 工具</span>
      <span class="row-chevron" aria-hidden="true">▸</span>
    </button>
    ${open ? `<div class="row-content work-detail">验证 ${escapeHtml(part.validation)} · ${escapeHtml(part.tokens)} tokens</div>` : ""}
  </li>`;
}

function renderPart(part) {
  if (part.kind === "task") return renderTask(part);
  if (part.kind === "context") return renderContext(part);
  if (part.kind === "turn") return `<li class="turn-separator">${escapeHtml(part.label)}</li>`;
  if (part.kind === "work") return renderWork(part);
  if (part.kind === "reasoning") return renderReasoning(part);
  if (part.kind === "activity") return renderActivity(part);
  if (part.kind === "text") return renderText(part);
  if (part.kind === "notice") return renderNotice(part);
  if (part.kind === "approval") return renderApprovalPart(part);
  return "";
}

function computeStatus() {
  if (state.build.state === "FINISHED") {
    return { label: "构建已结束 · 只读复盘", className: "", spinner: false };
  }
  if (state.pendingApproval) {
    return { label: "等待审批 · 需要你确认", className: "is-warning", spinner: false };
  }
  const runningTool = allTools().find((tool) => tool.status === "running");
  if (runningTool) {
    return {
      label: `工具执行中 · ${runningTool.name}`,
      className: "is-accent",
      spinner: true,
    };
  }
  if (state.build.validation === "通过 6/6") {
    return {
      label: "主机验证通过 · 正在写入候选规则",
      className: "is-accent",
      spinner: true,
    };
  }
  if (state.build.validation === "验证中") {
    return { label: "主机验证中…", className: "is-accent", spinner: true };
  }
  const reasoning = state.parts.find(
    (part) => part.kind === "reasoning" && part.streaming,
  );
  if (reasoning) {
    return { label: "模型正在思考…", className: "is-accent", spinner: true };
  }
  const text = state.parts.find((part) => part.kind === "text" && part.streaming);
  if (text) {
    return { label: "模型正在输出…", className: "is-accent", spinner: true };
  }
  return { label: "等待模型输出…", className: "", spinner: true };
}

function updateComposer() {
  const finished = state.build.state === "FINISHED";
  const blocked = Boolean(state.pendingApproval);
  composerInput.disabled = finished || blocked;
  composerInput.placeholder = finished
    ? "构建已结束，只读复盘"
    : blocked
      ? "先处理待审批请求…"
      : "发消息或继续当前构建…";
  sendButton.disabled = finished || blocked || !composerInput.value.trim();
}

function renderStatusLine() {
  if (state.build.state === "FINISHED") return "";
  const status = computeStatus();
  return `<li class="status-line ${status.className}">
    ${status.spinner ? '<span class="spinner" aria-hidden="true"></span>' : '<span class="status-icon" aria-hidden="true">·</span>'}
    <span>${status.label}</span>
    <span class="status-elapsed">${escapeHtml(state.build.elapsed)}</span>
  </li>`;
}

function renderTrace() {
  const rows = [];
  for (const part of state.parts) {
    if (part.kind === "task") {
      rows.push({ time: "", type: "任务", text: part.title });
    } else if (part.kind === "activity") {
      for (const tool of part.tools) {
        rows.push({
          time: tool.created_at || "",
          type: "工具",
          text: `${tool.name} · ${tool.summary} · ${toolStatusLabel(tool.status)}`,
        });
      }
    } else if (part.kind === "text") {
      rows.push({
        time: part.created_at || "",
        type: part.role === "user" ? "用户" : "文本",
        text: part.text.replace(/\s+/g, " ").slice(0, 180),
      });
    } else if (part.kind === "reasoning") {
      rows.push({
        time: part.created_at || "",
        type: "思考",
        text: part.text.replace(/\s+/g, " ").slice(0, 180),
      });
    } else if (part.kind === "notice") {
      rows.push({ time: part.created_at || "", type: "通知", text: part.title });
    } else if (part.kind === "approval") {
      rows.push({ time: "", type: "审批", text: part.approval.action });
    } else if (part.kind === "work") {
      rows.push({
        time: "",
        type: "完成",
        text: `用时 ${part.duration} · ${part.steps} 步 · ${part.tools} 工具`,
      });
    } else if (part.kind === "context") {
      rows.push({
        time: "",
        type: "上下文",
        text: part.items.map((item) => item.label).join(" · "),
      });
    }
  }
  traceBody.innerHTML = rows.length
    ? rows
        .map(
          (row) =>
            `<tr><td>${escapeHtml(row.time || "—")}</td><td>${escapeHtml(row.type)}</td><td>${escapeHtml(row.text)}</td></tr>`,
        )
        .join("")
    : `<tr><td colspan="3" class="muted">暂无轨迹</td></tr>`;
}

function updateHeader() {
  const finished = state.build.state === "FINISHED";
  liveBadge.textContent = finished ? "已结束" : "实时";
  liveBadge.className = `badge ${finished ? "" : "badge-info"}`;
  buildStateBadge.textContent = finished ? "已完成" : "运行中";
  buildStateBadge.className = `badge ${finished ? "badge-success" : "badge-info"}`;
  chatValidation.textContent = state.build.validation;
  chatElapsed.textContent = state.build.elapsed;
  composerStats.textContent = finished
    ? `1 轮 · 4 步 · 3 工具 · 12.4k tok · 验证 ${state.build.validation}`
    : "1 轮 · 4 步 · 3 工具 · 12.4k tok · 缓存命中 75%";
  pauseButton.disabled = finished;
  updateComposer();
}

function updateFollowButton() {
  if (scrollEl.hidden) {
    followButton.hidden = true;
    return;
  }
  const atBottom = isAtBottom();
  const show = !state.follow && !atBottom;
  followButton.hidden = !show;
  followCount.textContent = state.unseen > 0 ? `· ${state.unseen} 条更新` : "";
}

function isAtBottom() {
  return scrollEl.scrollHeight - scrollEl.scrollTop - scrollEl.clientHeight < 48;
}

function scrollToBottom() {
  state.follow = true;
  state.unseen = 0;
  scrollEl.scrollTop = scrollEl.scrollHeight;
  updateFollowButton();
}

function handleScroll() {
  const atBottom = isAtBottom();
  state.follow = state.autoFollow && atBottom;
  if (atBottom) state.unseen = 0;
  updateFollowButton();
}

function setAutoFollow(value) {
  state.autoFollow = value;
  followCheckbox.checked = value;
  if (value) {
    state.follow = true;
    scrollToBottom();
  } else {
    state.follow = false;
    updateFollowButton();
  }
}

function setSessionView(view) {
  chatTabs.forEach((tab) => {
    tab.setAttribute("aria-selected", String(tab.dataset.sessionView === view));
  });
  scrollEl.hidden = view !== "conversation";
  tracePanel.hidden = view !== "trace";
  if (view === "trace") renderTrace();
  updateFollowButton();
}

function render(options = {}) {
  const previousTop = scrollEl.scrollTop;
  timelineEl.innerHTML =
    state.parts.map(renderPart).join("") + renderStatusLine();
  updateHeader();
  renderTrace();

  if (options.reset) {
    scrollToBottom();
    return;
  }

  if (state.follow && state.autoFollow) {
    scrollToBottom();
    return;
  }

  scrollEl.scrollTop = previousTop;
  if (options.newContent) {
    state.unseen += 1;
  }
  updateFollowButton();
}

function afterToggle() {
  if (!isAtBottom()) {
    state.follow = false;
  }
  render();
  updateFollowButton();
}

function removeApprovalPart() {
  state.parts = state.parts.filter((part) => part.kind !== "approval");
  state.pendingApproval = null;
}

function approve() {
  const approval = state.pendingApproval;
  if (!approval) return;
  removeApprovalPart();
  state.build.validation = "验证中";
  state.parts.push({
    id: `notice-approve-${Date.now()}`,
    kind: "notice",
    tone: "success",
    title: `已批准 · ${approval.action}`,
    text: "主机将执行一次；结果会追加到时间线。",
    created_at: nowTime(),
  });
  const shell = findTool("activity-1", "tool-3");
  if (shell) {
    shell.status = "running";
    shell.duration = "—";
    shell.open = true;
  }
  render({ newContent: true });

  schedule(() => {
    const tool = findTool("activity-1", "tool-3");
    if (tool) {
      tool.status = "success";
      tool.duration = "2.8s";
      tool.output = "6/6 products valid\n0 failures\ncontent_audit: 0 gaps";
      tool.open = false;
    }
    state.build.state = "FINISHED";
    state.build.validation = "通过 6/6";
    if (!state.parts.some((part) => part.kind === "work")) {
      state.parts.splice(3, 0, {
        id: "work-1",
        kind: "work",
        open: false,
        duration: "04:12",
        steps: 4,
        tools: 3,
        validation: "通过 6/6",
        tokens: "12.4k",
      });
    }
    state.parts.push({
      id: `text-verified-${Date.now()}`,
      kind: "text",
      role: "assistant",
      streaming: false,
      created_at: nowTime(),
      text: "主机验证完成：6/6 有效，0 失败，价格和币种一致。候选规则已经写入并安装。",
    });
    state.parts.push({
      id: `notice-verified-${Date.now()}`,
      kind: "notice",
      tone: "success",
      title: "主机验证通过 6/6",
      text: "候选规则 2026.11.26-1 已安装；可以回到站点详情查看。",
      created_at: nowTime(),
    });
    render({ newContent: true });
  }, 1800);
}

function reject() {
  const approval = state.pendingApproval;
  if (!approval) return;
  removeApprovalPart();
  const shell = findTool("activity-1", "tool-3");
  if (shell) {
    shell.status = "cancelled";
    shell.output = "请求被用户拒绝，未执行。";
  }
  state.parts.push({
    id: `notice-reject-${Date.now()}`,
    kind: "notice",
    tone: "danger",
    title: `已拒绝 · ${approval.action}`,
    text: "命令没有执行；模型会收到拒绝结果并调整方案。",
    created_at: nowTime(),
  });
  render({ newContent: true });
  schedule(() => {
    state.parts.push({
      id: `text-reject-${Date.now()}`,
      kind: "text",
      role: "assistant",
      streaming: false,
      created_at: nowTime(),
      text: "已收到拒绝，不会执行该命令。我会改用不需要主机命令的方式来继续检查。",
    });
    render({ newContent: true });
  }, 800);
}

function appendEvent() {
  if (state.build.state === "FINISHED") {
    showToast("构建已结束；追加事件只用于运行中演示。");
    return;
  }
  appendIndex += 1;
  const activity = state.parts.find((part) => part.kind === "activity");
  if (!activity) return;

  if (appendIndex % 3 === 1) {
    const tool = {
      id: `tool-append-${Date.now()}`,
      name: "webfetch",
      status: "running",
      summary: `GET https://bennytex.com/products/${appendIndex}`,
      duration: "—",
      input: `GET https://bennytex.com/products/${appendIndex}\nAccept: text/html`,
      output: "",
      open: false,
    };
    activity.tools.push(tool);
    activity.open = true;
    render({ newContent: true });
    schedule(() => {
      tool.status = "success";
      tool.duration = "1.1s";
      tool.output = "HTTP 200 · 84 KB\nprice: 24.90 EUR\ncurrency: EUR";
      render({ newContent: true });
    }, 1500);
    return;
  }

  if (appendIndex % 3 === 2) {
    state.parts.push({
      id: `text-append-${Date.now()}`,
      kind: "text",
      role: "assistant",
      streaming: false,
      created_at: nowTime(),
      text:
        "又抽查了一件商品：名称、价格、币种和主图都可以从 JSON-LD 读取。\n" +
        '```json\n{"name":"...","price":"24.90","currency":"EUR"}\n```',
    });
    render({ newContent: true });
    return;
  }

  state.parts.push({
    id: `notice-append-${Date.now()}`,
    kind: "notice",
    tone: "info",
    title: "发现 158 个商品链接",
    text: "当前只抽查少量样本；正式采集范围由批次和规则目标决定。",
    created_at: nowTime(),
  });
  render({ newContent: true });
}

function sendMessage() {
  const text = composerInput.value.trim();
  if (!text || state.build.state === "FINISHED") return;
  composerInput.value = "";
  updateComposer();
  state.parts.push({
    id: `user-${Date.now()}`,
    kind: "text",
    role: "user",
    streaming: false,
    created_at: nowTime(),
    text,
  });
  render({ newContent: true });
  schedule(() => {
    const reply = state.pendingApproval
      ? "已收到补充说明。当前仍在等待审批，批准后才会执行命令。"
      : "已收到补充指令。原型会沿用当前构建会话继续处理，不会创建新的构建记录。";
    state.parts.push({
      id: `assistant-${Date.now()}`,
      kind: "text",
      role: "assistant",
      streaming: false,
      created_at: nowTime(),
      text: reply,
    });
    render({ newContent: true });
  }, 900);
}

let toastTimer = null;
function showToast(message) {
  toast.textContent = message;
  toast.hidden = false;
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toast.hidden = true;
    toastTimer = null;
  }, 2400);
}

timelineEl.addEventListener("click", (event) => {
  const approvalButton = event.target.closest("button[data-approval]");
  if (approvalButton) {
    if (approvalButton.dataset.approval === "approve") approve();
    if (approvalButton.dataset.approval === "reject") reject();
    return;
  }
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  if (button.dataset.action === "toggle-part") {
    const part = state.parts.find((item) => item.id === button.dataset.id);
    if (!part) return;
    part.open = !part.open;
    afterToggle();
    return;
  }
  if (button.dataset.action === "toggle-tool") {
    const tool = findTool(button.dataset.partId, button.dataset.toolId);
    if (!tool) return;
    tool.open = !tool.open;
    afterToggle();
  }
});

document.querySelectorAll("[data-scenario]").forEach((button) => {
  button.addEventListener("click", () => resetScenario(button.dataset.scenario));
});

chatTabs.forEach((tab) => {
  tab.addEventListener("click", () => setSessionView(tab.dataset.sessionView));
});

document.querySelector("#append-event").addEventListener("click", appendEvent);
document.querySelector("#reset").addEventListener("click", () => resetScenario("running"));
document.querySelector("#trace-button").addEventListener("click", () => {
  showToast("原型不下载文件；生产从构建详情下载 trace。");
});
document.querySelector("#pause-button").addEventListener("click", () => {
  showToast("原型不发送控制请求。");
});
document.querySelector("#more-button").addEventListener("click", () => {
  showToast("更多菜单不在本原型范围。");
});
document.querySelector("#send-button").addEventListener("click", sendMessage);
document.querySelector("#attach-button").addEventListener("click", () => {
  showToast("原型不打开文件选择器；生产接现有文件或调用指令入口。");
});

composerInput.addEventListener("input", updateComposer);
composerInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

followCheckbox.addEventListener("change", () => setAutoFollow(followCheckbox.checked));
followButton.addEventListener("click", () => {
  setAutoFollow(true);
  scrollToBottom();
});
scrollEl.addEventListener("scroll", handleScroll);

const resizeObserver = new ResizeObserver(() => {
  if (state.follow && state.autoFollow) scrollToBottom();
});
resizeObserver.observe(timelineEl);

resetScenario("running");
