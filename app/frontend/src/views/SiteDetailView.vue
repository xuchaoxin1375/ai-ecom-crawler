<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import {
  cancelBuild,
  cancelTask,
  getBatch,
  getBuild,
  getBuildConfig,
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
  type BuildConfig,
  type BuildEvent,
  type BuildMessages,
  type BuildStatus,
  type BuildTimelineItem,
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
import ProductCsvPreview from "../components/ProductCsvPreview.vue";
import PreviewMediaModal from "../components/PreviewMediaModal.vue";

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
const repairReason = ref("");
const captureReasoning = ref(false);
const detailMode = ref(true);
const autoRepair = ref(true);
const catalogFull = ref(false);
const archiveSample = ref(true);
const buildConfig = ref<BuildConfig | null>(null);
const buildOutput = ref<BuildMessages | null>(null);
const previewItems = ref<TaskItem[]>([]);
const previewLoading = ref(false);
const previewError = ref("");
const cardModalOpen = ref(false);
const cardModalTab = ref<"image" | "description">("image");
const cardModalItem = ref<TaskItem | null>(null);
let buildTimer: ReturnType<typeof setInterval> | null = null;
let taskTimer: ReturnType<typeof setInterval> | null = null;

const site = computed<BatchSite | null>(
  () => batch.value?.sites?.find((item) => item.site_key === props.siteKey) || null,
);
const task = computed(() => site.value?.task || null);
const taskActive = computed(() =>
  ["DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"].includes(
    task.value?.state || "",
  ),
);
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
const canRepairRule = computed(
  () =>
    !taskActive.value &&
    !buildActive.value &&
    site.value?.readiness === "ready" &&
    Boolean(site.value?.rule),
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
    ensureTaskPolling();
    await Promise.all([loadItems(), loadPreview()]);
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

async function loadBuildConfig() {
  try {
    buildConfig.value = await getBuildConfig();
  } catch {
    buildConfig.value = null;
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

const timeline = computed<BuildTimelineItem[]>(
  () => buildOutput.value?.timeline || [],
);

const activeRepair = computed(() => {
  if (!buildActive.value) return null;
  const rounds = build.value?.repairs || [];
  const last = rounds[rounds.length - 1];
  return last && !last.finished_at ? last : null;
});

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
      max_seconds: catalogFull.value ? 900 : 600,
      proxy: buildProxy.value.trim() || undefined,
      capture_reasoning: captureReasoning.value,
      repair_rounds: autoRepair.value ? 1 : 0,
      catalog_scope: catalogFull.value ? "full" : "sample",
      catalog_products: 3000,
      archive_mode: archiveSample.value ? "sample" : "off",
      archive_sample_limit: 20,
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

async function startRepair() {
  buildBusy.value = "repair";
  buildError.value = "";
  try {
    const payload = await startSiteBuild(props.id, props.siteKey, {
      mode: "repair",
      reason:
        repairReason.value.trim() ||
        "检查并补齐产品描述块、规格和缺失字段",
      max_products: 6,
      max_seconds: 600,
      proxy: buildProxy.value.trim() || undefined,
      capture_reasoning: captureReasoning.value,
      repair_rounds: autoRepair.value ? 1 : 0,
      archive_mode: archiveSample.value ? "sample" : "off",
      archive_sample_limit: 20,
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

function toolStatusLabel(status: string | undefined): string {
  if (!status) return "未知";
  if (status === "completed" || status === "success") return "完成";
  if (status === "failed" || status === "error") return "失败";
  if (status === "running") return "运行中";
  return status;
}

function toolStatusTone(status: string | undefined): string {
  if (status === "completed" || status === "success") return "success";
  if (status === "failed" || status === "error") return "danger";
  if (status === "running") return "warning";
  return "muted";
}

function timelineTime(item: BuildTimelineItem): string {
  return item.created_at ? formatTime(item.created_at) : "";
}

function formatBytes(value: number | null | undefined): string {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatTimelineValue(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function reasoningSummary(item: BuildTimelineItem): string {
  const length = item.text?.length || 0;
  const time = timelineTime(item);
  return `思考${time ? ` · ${time}` : ""} · ${length} 字`;
}

function permissionItems(): Array<Record<string, unknown>> {
  return (build.value?.pending_permissions || []).filter(
    (item) => item && typeof item.id === "string",
  );
}

onUnmounted(stopBuildPolling);
onUnmounted(stopTaskPolling);

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

async function loadPreview() {
  const taskId = task.value?.task_id;
  if (!taskId) {
    previewItems.value = [];
    return;
  }
  previewLoading.value = true;
  previewError.value = "";
  try {
    const payload = await getTaskItems(taskId, "product", 10, 0, "DONE", "desc");
    previewItems.value = payload.items.filter(
      (item) => item.result.product_preview,
    );
  } catch (exc) {
    previewError.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    previewLoading.value = false;
  }
}

function stopTaskPolling() {
  if (taskTimer !== null) {
    clearInterval(taskTimer);
    taskTimer = null;
  }
}

function scheduleTaskPolling() {
  stopTaskPolling();
  if (!taskActive.value) return;
  taskTimer = setInterval(() => {
    void load();
  }, 3000);
}

function ensureTaskPolling() {
  if (!taskActive.value) {
    stopTaskPolling();
    return;
  }
  if (taskTimer === null) scheduleTaskPolling();
}

function previewProduct(item: TaskItem): Record<string, unknown> {
  const value = item.result.product_preview;
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function previewImage(item: TaskItem): string {
  return String(previewProduct(item).primary_image_url || "");
}

function previewName(item: TaskItem): string {
  return String(previewProduct(item).name || item.url);
}

function previewPrice(item: TaskItem): string {
  const product = previewProduct(item);
  if (product.price_amount == null) return "价格未提供";
  const amount = formatAmount(product.price_amount);
  return `${amount} ${product.price_currency || ""}`.trim();
}

function previewMeta(item: TaskItem): string {
  const product = previewProduct(item);
  return [product.brand, product.category]
    .filter(Boolean)
    .map(String)
    .join(" · ");
}

function openCardModal(item: TaskItem, tab: "image" | "description") {
  cardModalItem.value = item;
  cardModalTab.value = tab;
  cardModalOpen.value = true;
}

const cardModalTitle = computed(() =>
  cardModalItem.value ? previewName(cardModalItem.value) : "商品预览",
);
const cardModalImage = computed(() =>
  cardModalItem.value ? previewImage(cardModalItem.value) : "",
);
const cardModalMeta = computed(() => {
  const item = cardModalItem.value;
  if (!item) return "";
  const product = previewProduct(item);
  return [
    product.price_amount != null
      ? `${formatAmount(product.price_amount)} ${product.price_currency || ""}`.trim()
      : "",
    previewMeta(item),
  ]
    .filter(Boolean)
    .join(" · ");
});

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
  await Promise.all([load(), loadBuildConfig()]);
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
      v-if="site.readiness === 'ready' || (!task && (site.readiness === 'needs_onboarding' || site.readiness === 'building' || build))"
      class="panel build-panel"
      aria-label="方案构建与规则维护"
    >
      <div class="panel-head">
        <div>
          <h2>{{ build?.mode === "repair" ? "规则修复与重新验证" : "方案构建与规则维护" }}</h2>
          <p v-if="site.readiness === 'ready'" class="muted">
            当前规则 <code>{{ site.rule?.rule_id }}@{{ site.rule?.rule_version }}</code>。
            可对已安装规则重新验证并修复描述块、规格和缺失字段；不删除已有采集数据。
          </p>
          <p v-else class="muted">
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
            v-if="canRepairRule"
            class="button button-primary"
            type="button"
            :disabled="Boolean(buildBusy)"
            @click="startRepair"
          >
            {{ buildBusy === "repair" ? "启动中…" : "重新验证／修复规则" }}
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

      <div v-if="canRepairRule || build?.mode === 'repair'" class="field">
        <label for="repair-reason">修复原因（可选）</label>
        <input
          id="repair-reason"
          v-model="repairReason"
          type="text"
          placeholder="例如：产品描述只采到成分，缺少规格块"
          autocomplete="off"
        />
        <small class="muted">
          会作为修复 brief 发给构建 Agent；留空使用默认的“检查并补齐描述块和缺失字段”。
        </small>
      </div>

      <div class="build-trace-options">
        <label class="check">
          <input
            v-model="captureReasoning"
            type="checkbox"
            :disabled="Boolean(buildConfig && !buildConfig.reasoning_capture_enabled)"
          />
          保留思考过程（仅本地复盘，默认关闭）
        </label>
        <small class="muted">
          需服务端以 <code>ECOM_BUILD_CAPTURE_REASONING=1</code> 启动；保留内容会截断并跳过私有推理之外的页面全文。
        </small>
        <small v-if="buildConfig && !buildConfig.reasoning_capture_enabled" class="muted">
          当前服务端未开启思考保留，勾选不会生效。
        </small>
        <label class="check">
          <input
            v-model="autoRepair"
            type="checkbox"
            :disabled="Boolean(buildConfig && buildConfig.max_repair_rounds < 1)"
          />
          验证失败后自动修复 1 轮
        </label>
        <small class="muted">
          预检规则选择器；验证失败时把精确错误回给同一模型会话修复一次，再重新验证。
          会多一次模型调用。
        </small>
        <small v-if="buildConfig && buildConfig.max_repair_rounds < 1" class="muted">
          当前服务端未启用自动修复（<code>ECOM_BUILD_MAX_REPAIR_ROUNDS=0</code>）。
        </small>
        <template v-if="site.readiness !== 'ready'">
          <label class="check">
            <input v-model="catalogFull" type="checkbox" />
            全量目录（按顶层分类和分页生成发现源；验证仍用少量商品）
          </label>
          <small class="muted">
            目标商品数按 3000 写入规则；构建仍只验证 6 个商品，通过后再从批次详情启动全量任务。
          </small>
        </template>
        <label class="check">
          <input v-model="archiveSample" type="checkbox" />
          归档样例页面（入口／分类／商品页，最多 20 页）
        </label>
        <small class="muted">
          主机在验证前抓取规则声明的样例并保存到本地 archive；后续规则复验优先复用，减少重复请求。
        </small>
        <label class="check">
          <input v-model="detailMode" type="checkbox" />
          详细模式（时间线，显示思考与工具调用）
        </label>
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
        <span
          v-if="build.repair_round"
          class="badge"
          :class="build.repairs.some((item) => item.resolved) ? 'success' : 'muted'"
        >
          自动修复 {{ build.repair_round }}/{{ build.repair_limit }}
        </span>
        <span v-if="build.catalog?.catalog_scope === 'full'" class="muted">
          全量目标 {{ build.catalog.catalog_products }}
        </span>
        <span v-if="build.archive_stats" class="muted">
          样例存档 {{ build.archive_stats.pages }} 页 /
          {{ formatBytes(build.archive_stats.bytes) }}
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

      <div v-if="activeRepair" class="notice warning">
        <strong>
          自动修复第 {{ activeRepair.round }}/{{ build?.repair_limit }} 轮
        </strong>
        <p class="muted">上次验证失败：{{ activeRepair.error }}</p>
      </div>

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
        <template v-if="site.readiness === 'ready'">
          当前没有修复记录。点击“重新验证／修复规则”会把已安装规则和样例页交给构建 Agent，
          只做定向修复并重新验证；失败保留原规则和已有采集数据。
        </template>
        <template v-else>
          当前没有构建记录。开始构建会调用模型分析站点并生成规则，产生模型费用；
          构建完成后自动做一次有界验证，通过后站点变为可采。
        </template>
      </p>

      <ol v-if="buildEvents.length" class="build-events">
        <li v-for="(event, index) in buildEvents" :key="`${event.created_at}-${index}`">
          <span class="badge" :class="buildEventTone(event)">
            {{ buildEventText(event) }}
          </span>
          <span class="muted">{{ formatTime(event.created_at) }}</span>
        </li>
      </ol>

      <section
        v-if="buildOutput && (outputText || reasoningText || timeline.length)"
        class="build-output"
      >
        <header class="build-output-head">
          <strong>模型输出（{{ buildOutput.live ? "流式" : "阶段性" }}）</strong>
        </header>
        <template v-if="detailMode">
          <p v-if="buildOutput.live" class="muted">
            模型正在输出，时间线会随轮询追加；构建结束后补全工具入参和输出。
          </p>
          <p v-if="!buildOutput.reasoning_retained" class="muted">
            本次构建未保留思考过程；构建前勾选“保留思考过程”且服务端开启
            <code>ECOM_BUILD_CAPTURE_REASONING=1</code> 才会显示。
          </p>
          <p v-if="!timeline.length" class="muted">还没有可见模型输出。</p>
          <div v-else class="build-timeline">
            <template
              v-for="(item, index) in timeline"
              :key="`${item.kind}-${index}-${item.created_at || ''}`"
            >
              <details v-if="item.kind === 'reasoning'" class="trace-entry reasoning">
                <summary>{{ reasoningSummary(item) }}</summary>
                <pre class="build-output-text">{{ item.text }}</pre>
              </details>
              <details v-else-if="item.kind === 'tool'" class="trace-entry tool">
                <summary>
                  工具 {{ item.name || "unknown" }}
                  <span class="badge" :class="toolStatusTone(item.status)">
                    {{ toolStatusLabel(item.status) }}
                  </span>
                  <span class="muted">{{ timelineTime(item) }}</span>
                  <span v-if="item.duration_ms != null" class="muted">
                    {{ item.duration_ms }} ms
                  </span>
                </summary>
                <div v-if="formatTimelineValue(item.input)" class="trace-detail">
                  <span class="trace-label">入参</span>
                  <pre class="build-output-text">{{ formatTimelineValue(item.input) }}</pre>
                </div>
                <div v-if="item.output" class="trace-detail">
                  <span class="trace-label">输出</span>
                  <pre class="build-output-text">{{ item.output }}</pre>
                </div>
                <p
                  v-if="!formatTimelineValue(item.input) && !item.output"
                  class="muted"
                >
                  工具完成后可在 trace 查看输出。
                </p>
              </details>
              <div v-else class="trace-entry text">
                <div class="trace-entry-head">
                  <span class="badge muted">
                    {{ item.role === "user" ? "用户" : "模型" }}
                  </span>
                  <span class="muted">{{ timelineTime(item) }}</span>
                </div>
                <pre class="build-output-text">{{ item.text }}</pre>
              </div>
            </template>
          </div>
          <p v-if="buildOutput.timeline_truncated" class="muted">
            时间线只显示最近 200 条记录；完整内容请下载 trace。
          </p>
        </template>
        <template v-else>
          <pre v-if="outputText" class="build-output-text">{{ outputText }}</pre>
          <p v-else class="muted">还没有可见模型输出。</p>
          <details v-if="reasoningText" class="build-reasoning">
            <summary>思考过程（已保留，仅本地复盘）</summary>
            <pre class="build-output-text">{{ reasoningText }}</pre>
          </details>
        </template>
      </section>
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

      <section class="panel data-preview-panel">
        <div class="panel-head">
          <div>
            <h2>已采数据预览</h2>
            <p class="muted">
              显示最近 {{ previewItems.length }} 条有效商品；共
              {{ task.counts.valid_products ?? 0 }} 条有效。
              <span v-if="taskActive">任务运行中每 3 秒刷新。</span>
            </p>
          </div>
          <div class="row-actions">
            <span v-if="previewLoading" class="muted">读取中…</span>
            <button
              class="button button-sm"
              type="button"
              :disabled="previewLoading"
              @click="loadPreview"
            >
              刷新预览
            </button>
            <RouterLink class="button button-sm" :to="`/tasks/${task.task_id}`">
              任务详情
            </RouterLink>
          </div>
        </div>
        <p v-if="previewError" class="notice danger">{{ previewError }}</p>
        <div v-if="previewItems.length" class="preview-grid">
          <article
            v-for="item in previewItems"
            :key="item.item_id"
            class="preview-card"
          >
            <button
              v-if="previewImage(item)"
              class="preview-image-button"
              type="button"
              :title="`查看大图：${previewName(item)}`"
              @click="openCardModal(item, 'image')"
            >
              <img
                :src="previewImage(item)"
                :alt="previewName(item)"
                loading="eager"
                referrerpolicy="no-referrer"
              />
            </button>
            <div class="preview-body">
              <strong>{{ previewName(item) }}</strong>
              <span class="preview-price">{{ previewPrice(item) }}</span>
              <small v-if="previewMeta(item)" class="muted">
                {{ previewMeta(item) }}
              </small>
              <a :href="item.url" target="_blank" rel="noreferrer">
                {{ item.url }}
              </a>
            </div>
          </article>
        </div>
        <p v-else class="muted">
          {{ taskActive ? "还没有完成的有效商品；任务运行中，预览会自动刷新。" : "本次任务没有可预览的有效商品。" }}
        </p>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div>
            <h2>CSV 表格预览</h2>
            <p class="muted">
              按导出的 9 列结构显示。任务运行中读取 products.jsonl，结束后读取 products.csv。
            </p>
          </div>
        </div>
        <ProductCsvPreview :task-id="task.task_id" :live="taskActive" />
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

    <PreviewMediaModal
      :open="cardModalOpen"
      :title="cardModalTitle"
      :image-url="cardModalImage"
      :meta="cardModalMeta"
      :source-url="cardModalItem?.url || ''"
      :initial-tab="cardModalTab"
      @close="cardModalOpen = false"
    />
  </template>

  <div v-else-if="batch" class="empty">
    <strong>批次中找不到这个站点</strong>
    <p class="muted">站点可能已被移除，或链接不完整。</p>
    <RouterLink class="button" :to="`/batches/${batch.batch_id}`">返回批次详情</RouterLink>
  </div>

  <p v-else class="muted">正在读取站点…</p>
</template>
