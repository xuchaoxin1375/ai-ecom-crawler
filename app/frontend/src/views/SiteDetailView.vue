<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import {
  cancelBuild,
  cancelTask,
  getBatch,
  getBuild,
  getBuildMessages,
  getTaskItems,
  pauseBuild,
  pauseTask,
  replyBuildDependency,
  replyBuildPermission,
  resumeBuild,
  resumeTask,
  startSiteBuild,
  taskExportUrl,
  type BatchSite,
  type BatchSummary,
  type BuildEvent,
  type BuildMessages,
  type BuildStatus,
  type TaskItem,
} from "../api";
import {
  READINESS_LABELS,
  buildOutcomeLabel,
  buildStateLabel,
  buildStateTone,
  coverageLabel,
  descriptionStatusLabel,
  descriptionStatusTone,
  formatAmount,
  formatTime,
  itemStateLabel,
  outcomeLabel,
  readinessTone,
  siteStatusText,
  stopReasonLabel,
  taskStateLabel,
  taskStateTone,
} from "../ui";

const props = defineProps<{ id: string; siteKey: string }>();

const batch = ref<BatchSummary | null>(null);
const loading = ref(false);
const error = ref("");
const tab = ref<"product" | "url">("product");
const items = ref<TaskItem[]>([]);
const itemsTotal = ref(0);
const itemsLoading = ref(false);
const itemsError = ref("");
const busy = ref("");
const confirmCancel = ref(false);
const build = ref<BuildStatus | null>(null);
const buildError = ref("");
const buildBusy = ref("");
const buildProxy = ref("");
const captureReasoning = ref(false);
const buildOutput = ref<BuildMessages | null>(null);
let buildTimer: ReturnType<typeof setInterval> | null = null;

const site = computed<BatchSite | null>(
  () => batch.value?.sites?.find((item) => item.site_key === props.siteKey) || null,
);
const task = computed(() => site.value?.task || null);
const canPause = computed(() => task.value?.state === "RUNNING");
const canResume = computed(() => task.value?.state === "PAUSED");
const canCancel = computed(() =>
  ["DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"].includes(
    task.value?.state || "",
  ),
);

const buildActive = computed(() =>
  ["CREATED", "RUNNING", "PAUSING", "PAUSED", "CANCELLING", "VALIDATING"].includes(
    build.value?.state || "",
  ),
);
const canStartBuild = computed(
  () =>
    !task.value &&
    !buildActive.value &&
    Boolean(site.value) &&
    ["needs_onboarding", "building"].includes(site.value?.readiness || ""),
);
const canPauseBuild = computed(() => build.value?.state === "RUNNING");
const canResumeBuild = computed(() =>
  ["PAUSING", "PAUSED"].includes(build.value?.state || ""),
);
const canCancelBuild = computed(() =>
  ["CREATED", "RUNNING", "PAUSING", "PAUSED"].includes(build.value?.state || ""),
);
const buildEvents = computed(() =>
  (build.value?.events || [])
    .filter((event) =>
      [
        "tool_started",
        "tool_finished",
        "phase_changed",
        "permission_requested",
        "permission_replied",
        "finished",
        "error",
      ].includes(event.type),
    )
    .slice(-10),
);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    batch.value = await getBatch(props.id);
    const current = batch.value.sites?.find(
      (item) => item.site_key === props.siteKey,
    );
    if (current?.build_id && current.build_id !== build.value?.build_id) {
      await loadBuild(current.build_id);
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    loading.value = false;
  }
}

function stopBuildPolling() {
  if (buildTimer !== null) {
    clearInterval(buildTimer);
    buildTimer = null;
  }
}

function scheduleBuildPolling() {
  stopBuildPolling();
  if (!buildActive.value) return;
  buildTimer = setInterval(() => {
    void refreshBuild();
  }, 2000);
}

async function loadBuild(buildId: string) {
  try {
    const payload = await getBuild(buildId);
    build.value = payload.build;
    buildError.value = "";
    await loadBuildOutput(buildId);
    scheduleBuildPolling();
  } catch (exc) {
    buildError.value = exc instanceof Error ? exc.message : String(exc);
  }
}

async function loadBuildOutput(buildId: string) {
  try {
    buildOutput.value = await getBuildMessages(buildId);
  } catch {
    // The build status and trace remain usable if the output endpoint is
    // temporarily unavailable; do not replace the primary error with this.
  }
}

const outputText = computed(() => {
  if (!buildOutput.value) return "";
  const separator = buildOutput.value.live ? "" : "\n\n";
  return buildOutput.value.messages.map((item) => item.text).join(separator);
});

const reasoningText = computed(() =>
  (buildOutput.value?.reasoning || []).map((item) => item.text).join("\n\n"),
);

async function refreshBuild() {
  const buildId = build.value?.build_id;
  if (!buildId) return;
  try {
    const payload = await getBuild(buildId);
    build.value = payload.build;
    await loadBuildOutput(buildId);
    if (!buildActive.value) {
      stopBuildPolling();
      await load();
    } else {
      scheduleBuildPolling();
    }
  } catch (exc) {
    buildError.value = exc instanceof Error ? exc.message : String(exc);
    stopBuildPolling();
  }
}

async function startBuild() {
  buildBusy.value = "start";
  buildError.value = "";
  try {
    const payload = await startSiteBuild(props.id, props.siteKey, {
      max_products: 6,
      max_seconds: 600,
      proxy: buildProxy.value.trim() || undefined,
      capture_reasoning: captureReasoning.value,
    });
    build.value = payload.build;
    await load();
    await loadBuildOutput(payload.build.build_id);
    scheduleBuildPolling();
  } catch (exc) {
    buildError.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    buildBusy.value = "";
  }
}

async function controlBuild(action: "pause" | "resume" | "cancel") {
  const buildId = build.value?.build_id;
  if (!buildId) return;
  buildBusy.value = action;
  buildError.value = "";
  try {
    const payload =
      action === "pause"
        ? await pauseBuild(buildId)
        : action === "resume"
          ? await resumeBuild(buildId)
          : await cancelBuild(buildId);
    build.value = payload.build;
    if (action === "cancel" || !buildActive.value) {
      stopBuildPolling();
      await load();
    } else {
      scheduleBuildPolling();
    }
  } catch (exc) {
    buildError.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    buildBusy.value = "";
  }
}

async function decideDependency(requestId: string, decision: "once" | "reject") {
  const buildId = build.value?.build_id;
  if (!buildId) return;
  buildBusy.value = `dep-${requestId}`;
  try {
    const payload = await replyBuildDependency(buildId, requestId, decision);
    build.value = payload.build;
    scheduleBuildPolling();
  } catch (exc) {
    buildError.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    buildBusy.value = "";
  }
}

async function decidePermission(
  requestId: string,
  decision: "once" | "reject",
) {
  const buildId = build.value?.build_id;
  if (!buildId) return;
  buildBusy.value = `perm-${requestId}`;
  try {
    const payload = await replyBuildPermission(buildId, requestId, decision);
    build.value = payload.build;
    scheduleBuildPolling();
  } catch (exc) {
    buildError.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    buildBusy.value = "";
  }
}

function buildModelLabel(status: BuildStatus | null): string {
  if (!status?.model) return "";
  const provider = status.model.providerID ?? status.model.provider_id ?? "";
  const id = status.model.id ?? "";
  const variant = status.model.variant ?? status.model.reasoning ?? "";
  const base = [provider, id].filter(Boolean).join("/");
  return variant ? `${base} (variant ${variant})` : base;
}

function buildTraceUrl(buildId: string, format: "json" | "md" = "md"): string {
  return `/api/builds/${encodeURIComponent(buildId)}/trace?format=${format}`;
}

function buildEventText(event: BuildEvent): string {
  const data = event.data || {};
  const tool = String(data.tool || "");
  if (event.type === "tool_started") {
    return tool && !tool.startsWith("call_") ? `调用工具 ${tool}` : "调用工具";
  }
  if (event.type === "tool_finished") {
    return `工具${data.status === "success" ? "完成" : "失败"}`;
  }
  if (event.type === "phase_changed") {
    return data.phase === "executing" ? "模型开始执行" : `阶段：${data.phase || ""}`;
  }
  if (event.type === "permission_requested") {
    return `等待权限：${data.action || ""}`.trim();
  }
  if (event.type === "permission_replied") {
    return `权限已回复：${data.reply || ""}`.trim();
  }
  if (event.type === "finished") {
    return `模型结束：${buildOutcomeLabel(String(data.outcome || ""))}`;
  }
  if (event.type === "error") {
    return `错误：${data.error || data.message || ""}`.trim();
  }
  return event.source_type;
}

function buildEventTone(event: BuildEvent): string {
  if (event.type === "error") return "danger";
  if (event.type === "finished") return "success";
  if (event.type === "permission_requested") return "warning";
  return "muted";
}

function permissionItems(): Array<Record<string, unknown>> {
  return (build.value?.pending_permissions || []).filter(
    (item) => item && typeof item.id === "string",
  );
}

onUnmounted(stopBuildPolling);

async function loadItems() {
  if (!task.value?.task_id) {
    items.value = [];
    itemsTotal.value = 0;
    return;
  }
  itemsLoading.value = true;
  itemsError.value = "";
  try {
    const payload = await getTaskItems(task.value.task_id, tab.value, 20, 0);
    items.value = payload.items;
    itemsTotal.value = payload.total;
  } catch (exc) {
    itemsError.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    itemsLoading.value = false;
  }
}

async function control(action: "pause" | "resume" | "cancel") {
  if (!task.value?.task_id) return;
  busy.value = action;
  error.value = "";
  try {
    if (action === "pause") await pauseTask(task.value.task_id);
    else if (action === "resume") await resumeTask(task.value.task_id);
    else await cancelTask(task.value.task_id);
    confirmCancel.value = false;
    await load();
    await loadItems();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    busy.value = "";
  }
}

function productPreview(item: TaskItem): string {
  const product = item.result.product_preview as
    | Record<string, unknown>
    | undefined;
  if (!product) return "";
  const bits: string[] = [];
  if (product.name) bits.push(String(product.name));
  if (product.price_amount != null) {
    bits.push(
      `${formatAmount(product.price_amount)} ${product.price_currency || ""}`.trim(),
    );
  }
  if (product.brand) bits.push(String(product.brand));
  if (product.category) bits.push(String(product.category));
  return bits.join(" · ");
}

function descriptionStatus(item: TaskItem): string {
  const product = item.result.product_preview as
    | Record<string, unknown>
    | undefined;
  return product?.description_status ? String(product.description_status) : "";
}

function qualityValue(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join("、") : "无";
  if (value && typeof value === "object") {
    return Object.keys(value).length ? JSON.stringify(value) : "无";
  }
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function missingReasonsText(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    return qualityValue(value);
  }
  const entries = Object.entries(value as Record<string, unknown>).filter(
    ([, reason]) => reason,
  );
  return entries.length
    ? entries.map(([field, reason]) => `${field}：${String(reason)}`).join("；")
    : "无";
}

function detailRows(exception: Record<string, unknown>): Array<[string, string]> {
  const labels: Record<string, string> = {
    source_url: "来源",
    description_status: "描述状态",
    partial_reason: "不完整原因",
    missing_reasons: "缺失字段",
  };
  return Object.entries(exception).map(([key, value]) => {
    let shown: string;
    if (key === "description_status") {
      shown = descriptionStatusLabel(String(value)) || "-";
    } else if (key === "missing_reasons") {
      shown = missingReasonsText(value);
    } else {
      shown = qualityValue(value);
    }
    return [labels[key] || key, shown];
  });
}

watch(tab, loadItems);

onMounted(async () => {
  await load();
  await loadItems();
});
</script>

<template>
  <div v-if="error && !batch" class="empty">
    <strong>读取站点失败</strong>
    <p class="notice danger">{{ error }}</p>
    <RouterLink class="button" to="/batches">返回批次列表</RouterLink>
  </div>

  <template v-else-if="batch && site">
    <div class="page-head">
      <div>
        <RouterLink class="back-link" :to="`/batches/${batch.batch_id}`">
          ← 返回 {{ batch.name }}
        </RouterLink>
        <h1>{{ site.domain }}</h1>
        <p class="muted">
          {{ site.input_value }}
          <span v-if="site.note"> · {{ site.note }}</span>
        </p>
      </div>
      <div class="page-actions">
        <button
          v-if="canPause"
          class="button"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('pause')"
        >
          暂停任务
        </button>
        <button
          v-if="canResume"
          class="button"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('resume')"
        >
          继续任务
        </button>
        <button
          v-if="canCancel"
          class="button button-danger"
          type="button"
          :disabled="Boolean(busy)"
          @click="confirmCancel = true"
        >
          取消任务
        </button>
        <RouterLink
          v-if="task"
          class="button"
          :to="`/tasks/${task.task_id}`"
        >
          在全部任务中打开
        </RouterLink>
        <a v-if="task" class="button" :href="taskExportUrl(task.task_id, true)" download>
          导出任务 ZIP
        </a>
      </div>
    </div>

    <p v-if="error" class="notice danger" role="alert">{{ error }}</p>

    <div v-if="confirmCancel" class="confirm-bar danger" role="alertdialog" aria-label="确认取消任务">
      <div>
        <strong>取消这个任务？</strong>
        <p>排队或运行中的任务会停止；已产生的部分结果保留，可继续导出。</p>
      </div>
      <div class="confirm-actions">
        <button class="button" type="button" @click="confirmCancel = false">返回</button>
        <button
          class="button button-danger"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('cancel')"
        >
          确认取消任务
        </button>
      </div>
    </div>

    <section class="batch-hero">
      <div class="hero-badges">
        <span class="badge" :class="readinessTone(site.readiness)">
          {{ READINESS_LABELS[site.readiness] }}
        </span>
        <span v-if="task" class="badge" :class="taskStateTone(task.state)">
          {{ taskStateLabel(task.state) }}
        </span>
        <span class="muted">
          {{ siteStatusText(site.readiness, task?.state || null) }}
        </span>
      </div>
      <div v-if="site.rule" class="muted">
        规则包 <code>{{ site.rule.rule_id }}@{{ site.rule.rule_version }}</code>
      </div>
    </section>

    <section
      v-if="!task && (site.readiness === 'needs_onboarding' || site.readiness === 'building' || build)"
      class="panel build-panel"
      aria-label="方案构建"
    >
      <div class="panel-head">
        <div>
          <h2>方案构建</h2>
          <p class="muted">
            新站由构建 Agent 生成候选规则；主机完成有界验证后站点才变为可采。
            构建会话与采集任务分开，默认只运行一个构建。
          </p>
        </div>
        <div class="row-actions">
          <button
            v-if="canStartBuild"
            class="button button-primary"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="startBuild"
          >
            {{ buildBusy === "start" ? "启动中…" : "开始构建方案" }}
          </button>
          <button
            v-if="canPauseBuild"
            class="button"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="controlBuild('pause')"
          >
            暂停构建
          </button>
          <button
            v-if="canResumeBuild"
            class="button"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="controlBuild('resume')"
          >
            继续构建
          </button>
          <button
            v-if="canCancelBuild"
            class="button button-danger"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="controlBuild('cancel')"
          >
            取消构建
          </button>
        </div>
      </div>

      <div class="field build-proxy-field">
        <label for="build-proxy">出口代理（可选）</label>
        <input
          id="build-proxy"
          v-model="buildProxy"
          type="text"
          placeholder="http://127.0.0.1:17211"
          autocomplete="off"
          spellcheck="false"
        />
        <small class="muted">
          构建和主机验证使用同一出口；留空使用服务默认或直连。市场本地化价格请按批次市场选择出口。
        </small>
      </div>

      <div class="build-trace-options">
        <label class="check">
          <input v-model="captureReasoning" type="checkbox" />
          保留思考过程（仅本地复盘，默认关闭）
        </label>
        <small class="muted">
          需服务端以 <code>ECOM_BUILD_CAPTURE_REASONING=1</code> 启动；保留内容会截断并跳过私有推理之外的页面全文。
        </small>
      </div>

      <p v-if="buildError" class="notice danger" role="alert">{{ buildError }}</p>

      <div v-if="build" class="build-status">
        <span class="badge" :class="buildStateTone(build.state)">
          {{ buildStateLabel(build.state) }}
        </span>
        <span
          v-if="build.outcome"
          class="badge"
          :class="build.outcome === 'failed' ? 'danger' : build.outcome === 'succeeded' ? 'success' : 'muted'"
        >
          {{ buildOutcomeLabel(build.outcome) }}
        </span>
        <code>{{ build.build_id }}</code>
        <span v-if="buildModelLabel(build)" class="muted">
          模型 {{ buildModelLabel(build) }}
        </span>
        <span v-if="build.proxy" class="muted">出口 {{ build.proxy }}</span>
        <span v-if="build.elapsed_seconds !== null" class="muted">
          已运行 {{ Math.round(build.elapsed_seconds || 0) }} 秒
        </span>
        <span v-if="build.rule" class="muted">
          规则 {{ build.rule.rule_id }}@{{ build.rule.rule_version }}
        </span>
        <a
          v-if="build.trace_available"
          class="button button-sm"
          :href="buildTraceUrl(build.build_id, 'md')"
          download
        >
          下载构建过程
        </a>
        <a
          v-if="build.trace_available"
          class="button button-sm"
          :href="buildTraceUrl(build.build_id, 'json')"
          download
        >
          trace.json
        </a>
      </div>
      <p v-if="build?.reasoning_retained" class="muted">
        思考过程已保留在本地构建 trace；默认不包含在仓库证据中。
      </p>

      <p v-if="build?.error" class="notice danger">{{ build.error }}</p>

      <div v-if="build?.pending_dependencies?.length" class="notice warning">
        <strong>依赖审批</strong>
        <span
          v-for="requestId in build.pending_dependencies"
          :key="requestId"
          class="build-approval"
        >
          <code>{{ requestId }}</code>
          <button
            class="button button-sm"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="decideDependency(requestId, 'once')"
          >
            批准
          </button>
          <button
            class="button button-sm"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="decideDependency(requestId, 'reject')"
          >
            拒绝
          </button>
        </span>
      </div>

      <div v-if="permissionItems().length" class="notice warning">
        <strong>权限请求</strong>
        <span
          v-for="request in permissionItems()"
          :key="String(request.id)"
          class="build-approval"
        >
          <code>{{ String(request.action || 'permission') }}</code>
          <span v-if="request.resources" class="muted">
            {{ Array.isArray(request.resources) ? request.resources.join('、') : String(request.resources) }}
          </span>
          <button
            class="button button-sm"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="decidePermission(String(request.id), 'once')"
          >
            允许一次
          </button>
          <button
            class="button button-sm"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="decidePermission(String(request.id), 'reject')"
          >
            拒绝
          </button>
        </span>
      </div>

      <p v-if="!build" class="muted">
        当前没有构建记录。开始构建会调用模型分析站点并生成规则，产生模型费用；
        构建完成后自动做一次有界验证，通过后站点变为可采。
      </p>

      <ol v-if="buildEvents.length" class="build-events">
        <li v-for="(event, index) in buildEvents" :key="`${event.created_at}-${index}`">
          <span class="badge" :class="buildEventTone(event)">
            {{ buildEventText(event) }}
          </span>
          <span class="muted">{{ formatTime(event.created_at) }}</span>
        </li>
      </ol>

      <details
        v-if="buildOutput && (outputText || reasoningText)"
        class="build-output"
      >
        <summary>
          模型输出（{{ buildOutput.live ? "流式片段" : "阶段性" }}）
        </summary>
        <p v-if="buildOutput.live" class="muted">
          模型正在输出，片段会随轮询追加；构建结束后显示完整可见消息。
        </p>
        <pre v-if="outputText" class="build-output-text">{{ outputText }}</pre>
        <p v-else class="muted">还没有可见模型输出。</p>
        <details v-if="reasoningText" class="build-reasoning">
          <summary>思考过程（已保留，仅本地复盘）</summary>
          <pre class="build-output-text">{{ reasoningText }}</pre>
        </details>
      </details>
      <p v-else-if="build && !buildActive" class="muted">
        本次构建没有可见模型输出；可下载 trace 查看工具调用和错误。
      </p>

      <p v-if="build?.state === 'FINISHED' && build.outcome === 'succeeded'" class="notice success">
        构建完成，候选规则已安装。回到批次详情启动可采站点即可创建采集任务。
      </p>
      <p v-else-if="build?.state === 'VALIDATING'" class="muted">
        模型已结束，主机正在做有界验证和规则安装；此时站点还不能启动。
      </p>
      <p v-else-if="build?.state === 'CANCELLED'" class="muted">
        构建已取消，站点回到待接入；可以重新开始构建。
      </p>
    </section>

    <template v-if="task">
      <section class="cards six" aria-label="任务汇总">
        <div class="card">
          <span>任务状态</span>
          <strong>{{ taskStateLabel(task.state) }}</strong>
          <small>{{ task.outcome ? outcomeLabel(task.outcome) : "未结束" }}</small>
        </div>
        <div class="card">
          <span>停止原因</span>
          <strong class="value-text">{{ stopReasonLabel(task.stop_reason) }}</strong>
          <small>{{ task.stop_reason || "-" }}</small>
        </div>
        <div class="card">
          <span>有效商品</span>
          <strong>{{ task.counts.valid_products ?? 0 }}</strong>
          <small>排除 {{ task.counts.excluded_products ?? 0 }}</small>
        </div>
        <div class="card">
          <span>失败商品</span>
          <strong>{{ task.counts.failed_products ?? 0 }}</strong>
          <small>发现 URL {{ task.counts.discovered_urls ?? "-" }}</small>
        </div>
        <div class="card">
          <span>覆盖</span>
          <strong class="value-text">{{ coverageLabel(String(task.coverage.status || "")) }}</strong>
          <small>
            覆盖 {{ task.coverage.covered ?? "-" }} / 分母
            {{ task.coverage.denominator ?? "-" }}
          </small>
        </div>
        <div class="card">
          <span>质量异常</span>
          <strong>{{ task.quality_exceptions.length }}</strong>
          <small>正文不完整或非可选字段缺失</small>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>质量异常</h2>
            <p class="muted">
              仅列正文不完整或非可选字段缺失的商品；品牌、分类等可空字段缺失不算异常。
            </p>
          </div>
        </div>
        <ul v-if="task.quality_exceptions.length" class="quality-list">
          <li v-for="(exception, index) in task.quality_exceptions" :key="index">
            <dl>
              <template v-for="[label, value] in detailRows(exception)" :key="label">
                <dt>{{ label }}</dt>
                <dd>
                  <a
                    v-if="label === '来源' && value.startsWith('http')"
                    :href="value"
                    target="_blank"
                    rel="noreferrer"
                  >{{ value }}</a>
                  <span v-else>{{ value }}</span>
                </dd>
              </template>
            </dl>
          </li>
        </ul>
        <p v-else class="muted">本次没有质量异常。</p>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>任务明细</h2>
            <p class="muted">显示前 {{ items.length }} 条，共 {{ itemsTotal }} 条。</p>
          </div>
          <div class="row-actions">
            <button
              class="filter-chip"
              :class="{ active: tab === 'product' }"
              type="button"
              @click="tab = 'product'"
            >
              商品
            </button>
            <button
              class="filter-chip"
              :class="{ active: tab === 'url' }"
              type="button"
              @click="tab = 'url'"
            >
              网址
            </button>
            <button class="button button-sm" type="button" :disabled="itemsLoading" @click="loadItems">
              {{ itemsLoading ? "读取中…" : "刷新" }}
            </button>
          </div>
        </div>
        <p v-if="itemsError" class="notice danger">{{ itemsError }}</p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>{{ tab === "product" ? "商品" : "网址" }}</th>
                <th>状态</th>
                <th>尝试</th>
                <th>失败分类</th>
                <th>结果</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in items" :key="item.item_id">
                <td>
                  <span v-if="tab === 'product'">
                    <strong v-if="productPreview(item)">{{ productPreview(item) }}</strong>
                    <code v-else>{{ item.url }}</code>
                  </span>
                  <code v-else>{{ item.url }}</code>
                  <span v-if="item.url && tab === 'product' && productPreview(item)" class="cell-note">
                    {{ item.url }}
                  </span>
                </td>
                <td>
                  <span class="badge" :class="item.state === 'DONE' ? 'success' : item.state === 'FAILED' ? 'danger' : 'muted'">
                    {{ itemStateLabel(item.state) }}
                  </span>
                  <span
                    v-if="tab === 'product' && descriptionStatus(item) && descriptionStatus(item).toLowerCase() !== 'complete'"
                    class="badge"
                    :class="descriptionStatusTone(descriptionStatus(item))"
                  >
                    {{ descriptionStatusLabel(descriptionStatus(item)) }}
                  </span>
                </td>
                <td>{{ item.attempts }}</td>
                <td>{{ item.failure_class || "-" }}</td>
                <td>
                  <span v-if="item.result.reason" class="muted">{{ item.result.reason }}</span>
                  <span v-else-if="item.result.page">第 {{ item.result.page }} 页</span>
                  <span v-else>-</span>
                </td>
              </tr>
              <tr v-if="!items.length && !itemsLoading">
                <td colspan="5" class="muted">没有明细。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <details class="panel technical">
        <summary>技术详情</summary>
        <dl class="detail-grid">
          <dt>任务 ID</dt>
          <dd>
            <RouterLink :to="`/tasks/${task.task_id}`">
              <code>{{ task.task_id }}</code>
            </RouterLink>
          </dd>
          <dt>计划</dt>
          <dd><code>{{ task.plan_id }}@{{ task.plan_version }}</code></dd>
          <dt>规则包路径</dt>
          <dd><code>{{ site.rule?.path || "-" }}</code></dd>
          <dt>批次</dt>
          <dd><code>{{ task.batch_id || batch.batch_id }}</code></dd>
          <dt>市场</dt>
          <dd>{{ task.market || "-" }}</dd>
          <dt>创建</dt>
          <dd>{{ formatTime(task.created_at) }}</dd>
          <dt>更新</dt>
          <dd>{{ formatTime(task.updated_at) }}</dd>
        </dl>
      </details>
    </template>

    <section v-else class="panel empty">
      <strong>
        <template v-if="site.readiness === 'ready'">站点可采，但还没有任务</template>
        <template v-else-if="site.readiness === 'needs_onboarding'">站点待接入</template>
        <template v-else-if="site.readiness === 'building'">规则包构建中</template>
        <template v-else>该条目无效或重复，不进入采集</template>
      </strong>
      <p class="muted">
        <template v-if="site.readiness === 'ready'">
          回到批次详情，启动可采站点即可创建任务。
        </template>
        <template v-else-if="site.readiness === 'needs_onboarding'">
          没有匹配到受管规则包；可在上方启动构建 Agent，验证通过后站点自动变为可采。
        </template>
        <template v-else-if="site.readiness === 'building'">
          规则包正在构建或验证，页面不会把它显示成可启动。
        </template>
        <template v-else>
          无效和重复条目只保留在批次记录中，不创建任务、不计为失败。
        </template>
      </p>
      <RouterLink class="button" :to="`/batches/${batch.batch_id}`">
        返回批次详情
      </RouterLink>
    </section>
  </template>

  <div v-else-if="batch" class="empty">
    <strong>批次中找不到这个站点</strong>
    <p class="muted">站点可能已被移除，或链接不完整。</p>
    <RouterLink class="button" :to="`/batches/${batch.batch_id}`">返回批次详情</RouterLink>
  </div>

  <p v-else class="muted">正在读取站点…</p>
</template>
