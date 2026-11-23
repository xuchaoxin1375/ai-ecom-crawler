<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import {
  archiveTask,
  cancelTask,
  getTask,
  getTaskItems,
  pauseTask,
  restoreTask,
  resumeTask,
  startTask,
  taskEventsUrl,
  taskExportUrl,
  type TaskItem,
  type TaskSummary,
} from "../api";
import {
  coverageLabel,
  descriptionStatusLabel,
  descriptionStatusTone,
  formatAmount,
  formatTime,
  itemStateLabel,
  outcomeLabel,
  stopReasonLabel,
  taskStateLabel,
  taskStateTone,
} from "../ui";
import ProductCsvPreview from "../components/ProductCsvPreview.vue";

const props = defineProps<{ id: string }>();

const task = ref<TaskSummary | null>(null);
const taskActive = computed(() =>
  ["DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"].includes(
    task.value?.state || "",
  ),
);
const loading = ref(false);
const error = ref("");
const actionNotice = ref("");
const busy = ref("");
const confirmCancel = ref(false);
const tab = ref<"product" | "url">("product");
const items = ref<TaskItem[]>([]);
const itemsTotal = ref(0);
const itemsLoading = ref(false);
const itemsError = ref("");
const page = ref(0);
const pageSize = 50;

let source: EventSource | null = null;
let refreshTimer: ReturnType<typeof setTimeout> | undefined;
let pollTimer: ReturnType<typeof setInterval> | undefined;
let unmounted = false;

const isTerminal = computed(
  () => task.value?.state === "FINISHED" || task.value?.state === "CANCELLED",
);
const canExport = computed(
  () =>
    Boolean(task.value) &&
    !["DRAFT", "QUEUED"].includes(task.value?.state || ""),
);
const canStart = computed(() => task.value?.state === "DRAFT");
const canPause = computed(() => task.value?.state === "RUNNING");
const canResume = computed(() => task.value?.state === "PAUSED");
const canCancel = computed(() =>
  ["DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"].includes(
    task.value?.state || "",
  ),
);
const canArchive = computed(
  () => Boolean(task.value && isTerminal.value && !task.value.archived_at),
);
const canRestore = computed(() => Boolean(task.value?.archived_at));
const qualityCount = computed(() =>
  Array.isArray(task.value?.quality_exceptions)
    ? task.value.quality_exceptions.length
    : 0,
);
const pageCount = computed(() =>
  Math.max(1, Math.ceil(itemsTotal.value / pageSize)),
);
const countEntries = computed(() =>
  Object.entries(task.value?.counts || {}).filter(
    ([, value]) => typeof value === "number",
  ),
);

const COUNT_LABELS: Record<string, string> = {
  navigation_urls: "导航 URL",
  discovered_urls: "发现 URL",
  product_candidates: "商品候选",
  processed_products: "已处理商品",
  valid_products: "有效商品",
  excluded_products: "排除商品",
  failed_products: "失败商品",
  partial_description_products: "部分描述商品",
  pending: "待处理",
  pending_products: "待处理商品",
  in_flight: "处理中",
  in_flight_products: "处理中商品",
  excluded: "排除",
  failed: "失败",
};

function countLabel(key: string): string {
  return COUNT_LABELS[key] || key;
}

function taskTypeLabel(type: string): string {
  return type === "discovery" ? "发现" : "商品";
}

async function loadTask(silent = false) {
  if (!silent) loading.value = true;
  error.value = "";
  try {
    task.value = await getTask(props.id);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    loading.value = false;
  }
}

async function loadItems() {
  itemsLoading.value = true;
  itemsError.value = "";
  try {
    const payload = await getTaskItems(
      props.id,
      tab.value,
      pageSize,
      page.value * pageSize,
    );
    items.value = payload.items;
    itemsTotal.value = payload.total;
    if (page.value > 0 && payload.items.length === 0 && payload.total > 0) {
      page.value = Math.max(0, Math.ceil(payload.total / pageSize) - 1);
      await loadItems();
    }
  } catch (exc) {
    itemsError.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    itemsLoading.value = false;
  }
}

function closeEvents() {
  if (source) {
    source.close();
    source = null;
  }
}

function scheduleRefresh() {
  if (refreshTimer !== undefined) clearTimeout(refreshTimer);
  refreshTimer = setTimeout(() => {
    refreshTimer = undefined;
    if (!unmounted) {
      void loadTask(true);
      void loadItems();
    }
  }, 350);
}

function openEvents() {
  closeEvents();
  if (typeof EventSource === "undefined") return;
  source = new EventSource(taskEventsUrl(props.id));
  source.addEventListener("snapshot", scheduleRefresh);
  source.addEventListener("update", scheduleRefresh);
  source.addEventListener("end", closeEvents);
  source.onerror = closeEvents;
}

async function control(
  action: "start" | "pause" | "resume" | "cancel" | "archive" | "restore",
) {
  const current = task.value;
  if (!current) return;
  busy.value = action;
  error.value = "";
  try {
    if (action === "start") await startTask(current.task_id);
    else if (action === "pause") await pauseTask(current.task_id);
    else if (action === "resume") await resumeTask(current.task_id);
    else if (action === "cancel") await cancelTask(current.task_id);
    else if (action === "archive") await archiveTask(current.task_id);
    else await restoreTask(current.task_id);
    const labels = {
      start: "启动",
      pause: "暂停",
      resume: "恢复",
      cancel: "取消",
      archive: "归档",
      restore: "还原",
    } as const;
    actionNotice.value = `${labels[action]}请求已受理；最终状态以任务账本为准。`;
    confirmCancel.value = false;
    await loadTask(true);
    await loadItems();
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    busy.value = "";
  }
}

function goPage(delta: number) {
  const next = page.value + delta;
  if (next < 0 || next >= pageCount.value) return;
  page.value = next;
  void loadItems();
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

function productRecord(item: TaskItem): Record<string, unknown> | null {
  const product = item.result.product_preview;
  return product && typeof product === "object"
    ? (product as Record<string, unknown>)
    : null;
}

function descriptionStatus(item: TaskItem): string {
  return productRecord(item)?.description_status
    ? String(productRecord(item)?.description_status)
    : "";
}

function missingText(item: TaskItem): string {
  const product = productRecord(item);
  const missing = product?.missing_reasons;
  if (!missing || typeof missing !== "object") return "";
  return Object.entries(missing)
    .filter(([, value]) => value)
    .map(([key, value]) => `${key}：${String(value)}`)
    .join("；");
}

function failureText(item: TaskItem): string {
  return (
    item.failure_class ||
    (item.result.failure_class ? String(item.result.failure_class) : "") ||
    (item.result.reason ? String(item.result.reason) : "") ||
    "-"
  );
}

function itemResultText(item: TaskItem): string {
  if (item.result.page) return `第 ${item.result.page} 页`;
  if (item.result.depth) return `深度 ${item.result.depth}`;
  if (item.result.reason) return String(item.result.reason);
  return "-";
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

function siteLink(): string | null {
  if (!task.value?.batch_id || !task.value.site_key) return null;
  return `/batches/${task.value.batch_id}/sites/${encodeURIComponent(task.value.site_key)}`;
}

watch(tab, () => {
  page.value = 0;
  void loadItems();
});

watch(
  () => props.id,
  async () => {
    closeEvents();
    page.value = 0;
    await loadTask();
    await loadItems();
    openEvents();
  },
);

onMounted(async () => {
  await loadTask();
  await loadItems();
  openEvents();
  pollTimer = setInterval(() => {
    if (
      !unmounted &&
      document.visibilityState === "visible" &&
      task.value &&
      ["QUEUED", "RUNNING", "PAUSING", "CANCELLING"].includes(task.value.state)
    ) {
      void loadTask(true);
    }
  }, 5000);
});

onBeforeUnmount(() => {
  unmounted = true;
  closeEvents();
  if (refreshTimer !== undefined) clearTimeout(refreshTimer);
  if (pollTimer !== undefined) clearInterval(pollTimer);
});
</script>

<template>
  <div v-if="error && !task" class="empty">
    <strong>读取任务失败</strong>
    <p class="notice danger">{{ error }}</p>
    <RouterLink class="button" to="/tasks">返回全部任务</RouterLink>
  </div>

  <template v-else-if="task">
    <div class="page-head">
      <div>
        <RouterLink class="back-link" to="/tasks">← 返回全部任务</RouterLink>
        <h1>{{ task.task_id }}</h1>
        <p class="muted">
          {{ task.site_key || "-" }} · {{ task.plan_id }}@{{ task.plan_version }} ·
          {{ task.market || "未设置市场" }}
        </p>
      </div>
      <div class="page-actions">
        <button
          v-if="canStart"
          class="button button-primary"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('start')"
        >
          启动任务
        </button>
        <button
          v-if="canPause"
          class="button"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('pause')"
        >
          暂停
        </button>
        <button
          v-if="canResume"
          class="button"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('resume')"
        >
          恢复
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
        <a
          v-if="canExport"
          class="button"
          :href="taskExportUrl(task.task_id, !isTerminal)"
          download
        >
          {{ isTerminal ? "导出 ZIP" : "部分导出 ZIP" }}
        </a>
        <button
          v-if="canArchive"
          class="button"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('archive')"
        >
          归档
        </button>
        <button
          v-if="canRestore"
          class="button"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('restore')"
        >
          还原
        </button>
      </div>
    </div>

    <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
    <p v-if="actionNotice" class="notice success" role="status">{{ actionNotice }}</p>

    <div v-if="confirmCancel" class="confirm-bar danger" role="alertdialog" aria-label="确认取消任务">
      <div>
        <strong>取消这个任务？</strong>
        <p>排队或运行中的任务会停止；已产生的结果保留，可继续导出。</p>
      </div>
      <div class="confirm-actions">
        <button class="button" type="button" @click="confirmCancel = false">返回</button>
        <button
          class="button button-danger"
          type="button"
          :disabled="Boolean(busy)"
          @click="control('cancel')"
        >
          确认取消
        </button>
      </div>
    </div>

    <section class="batch-hero">
      <div class="hero-badges">
        <span class="badge" :class="taskStateTone(task.state)">
          {{ taskStateLabel(task.state) }}
        </span>
        <span v-if="task.outcome" class="badge info">
          {{ outcomeLabel(task.outcome) }}
        </span>
        <span v-if="task.archived_at" class="badge muted">已归档</span>
        <span class="muted">
          停止：{{ stopReasonLabel(task.stop_reason) }} · 更新
          {{ formatTime(task.updated_at) }}
        </span>
      </div>
      <div class="page-actions">
        <RouterLink
          v-if="task.batch_id"
          class="button button-sm"
          :to="`/batches/${task.batch_id}`"
        >
          所属批次
        </RouterLink>
        <RouterLink
          v-if="siteLink()"
          class="button button-sm"
          :to="siteLink() || '/tasks'"
        >
          批次站点
        </RouterLink>
      </div>
    </section>

    <section class="cards six" aria-label="任务汇总">
      <div class="card">
        <span>状态</span>
        <strong class="value-text">{{ taskStateLabel(task.state) }}</strong>
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
        <small>排除 {{ task.counts.excluded_products ?? task.counts.excluded ?? 0 }}</small>
      </div>
      <div class="card">
        <span>失败商品</span>
        <strong>{{ task.counts.failed_products ?? task.counts.failed ?? 0 }}</strong>
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
        <strong>{{ qualityCount }}</strong>
        <small>正文不完整或非可选字段缺失</small>
      </div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>任务信息</h2>
          <p class="muted">技术元数据和账本时间。</p>
        </div>
      </div>
      <dl class="detail-grid">
        <dt>任务 ID</dt>
        <dd><code>{{ task.task_id }}</code></dd>
        <dt>站点</dt>
        <dd>{{ task.site_key || "-" }}</dd>
        <dt>方案</dt>
        <dd><code>{{ task.plan_id }}@{{ task.plan_version }}</code></dd>
        <dt>类型／市场</dt>
        <dd>{{ taskTypeLabel(task.task_type) }} · {{ task.market || "-" }}</dd>
        <dt>批次</dt>
        <dd>
          <RouterLink v-if="task.batch_id" :to="`/batches/${task.batch_id}`">
            {{ task.batch_id }}
          </RouterLink>
          <span v-else>-</span>
        </dd>
        <dt>创建</dt>
        <dd>{{ formatTime(task.created_at) }}</dd>
        <dt>更新</dt>
        <dd>{{ formatTime(task.updated_at) }}</dd>
        <dt>结束</dt>
        <dd>{{ formatTime(task.finished_at) }}</dd>
        <dt>归档</dt>
        <dd>{{ task.archived_at ? formatTime(task.archived_at) : "否" }}</dd>
      </dl>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>全部计数</h2>
          <p class="muted">计数来自任务账本／结果，不与其他任务相加。</p>
        </div>
      </div>
      <div v-if="countEntries.length" class="count-grid">
        <div v-for="[key, value] in countEntries" :key="key" class="count-item">
          <span>{{ countLabel(key) }}</span>
          <strong>{{ value }}</strong>
        </div>
      </div>
      <p v-else class="muted">任务还没有计数。</p>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>CSV 表格预览</h2>
          <p class="muted">
            按导出的 9 列结构显示；运行中读取 products.jsonl，结束后读取 products.csv。
          </p>
        </div>
      </div>
      <ProductCsvPreview :task-id="task.task_id" :live="taskActive" />
    </section>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>内容完整度</h2>
          <p class="muted">
            按规则声明的描述块检查页面内容是否进入 description_html；有缺口时任务会标记部分描述。
          </p>
        </div>
      </div>
      <div
        v-if="task.content_audit && task.content_audit.products_checked"
        class="count-grid"
      >
        <div class="card">
          <span>已审计商品</span>
          <strong>{{ task.content_audit.products_checked }}</strong>
          <small>声明了描述块审计并成功提取的商品</small>
        </div>
        <div class="card">
          <span>描述缺口</span>
          <strong>{{ task.content_audit.description_gaps ?? 0 }}</strong>
          <small>页面存在但未进入 description_html 的块</small>
        </div>
      </div>
      <ul
        v-if="task.content_audit?.samples?.length"
        class="quality-list"
      >
        <li v-for="(sample, index) in task.content_audit.samples" :key="index">
          <dl>
            <dt>来源</dt>
            <dd><code>{{ sample.source_url }}</code></dd>
            <dt>缺失块</dt>
            <dd>{{ sample.missing_blocks.join("、") }}</dd>
          </dl>
        </li>
      </ul>
      <p v-else-if="task.content_audit?.products_checked" class="muted">
        本次任务没有描述块缺口。
      </p>
      <p v-else class="muted">
        本次任务没有声明描述块审计；可对规则做一次重新验证来启用。
      </p>
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
          <p class="muted">
            共 {{ itemsTotal }} 条；第 {{ page + 1 }} / {{ pageCount }} 页。
          </p>
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
            {{ itemsLoading ? "读取中…" : "刷新明细" }}
          </button>
        </div>
      </div>
      <p v-if="itemsError" class="notice danger">{{ itemsError }}</p>
      <div class="table-wrap">
        <table class="item-table">
          <thead>
            <tr v-if="tab === 'product'">
              <th>URL</th>
              <th>商品</th>
              <th>状态</th>
              <th class="col-attempts">尝试</th>
              <th class="col-failure">失败</th>
            </tr>
            <tr v-else>
              <th>URL</th>
              <th>状态</th>
              <th class="col-attempts">尝试</th>
              <th class="col-failure">失败</th>
              <th>结果</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in items" :key="item.item_id">
              <td>
                <a :href="item.url" target="_blank" rel="noreferrer">{{ item.url }}</a>
              </td>
              <template v-if="tab === 'product'">
                <td>
                  <strong v-if="productPreview(item)">{{ productPreview(item) }}</strong>
                  <span v-if="missingText(item)" class="cell-note">
                    缺失：{{ missingText(item) }}
                  </span>
                </td>
                <td>
                  <span class="badge" :class="item.state === 'DONE' ? 'success' : item.state === 'FAILED' ? 'danger' : 'muted'">
                    {{ itemStateLabel(item.state) }}
                  </span>
                  <span
                    v-if="descriptionStatus(item) && descriptionStatus(item).toLowerCase() !== 'complete'"
                    class="badge"
                    :class="descriptionStatusTone(descriptionStatus(item))"
                  >
                    {{ descriptionStatusLabel(descriptionStatus(item)) }}
                  </span>
                </td>
                <td class="col-attempts">{{ item.attempts }}</td>
                <td class="col-failure">{{ failureText(item) }}</td>
              </template>
              <template v-else>
                <td>
                  <span class="badge" :class="item.state === 'DONE' ? 'success' : item.state === 'FAILED' ? 'danger' : 'muted'">
                    {{ itemStateLabel(item.state) }}
                  </span>
                </td>
                <td class="col-attempts">{{ item.attempts }}</td>
                <td class="col-failure">{{ failureText(item) }}</td>
                <td>{{ itemResultText(item) }}</td>
              </template>
            </tr>
            <tr v-if="!items.length && !itemsLoading">
              <td :colspan="tab === 'product' ? 5 : 5" class="muted">没有明细。</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pager">
        <button
          class="button button-sm"
          type="button"
          :disabled="page === 0 || itemsLoading"
          @click="goPage(-1)"
        >
          上一页
        </button>
        <span class="muted">第 {{ page + 1 }} / {{ pageCount }} 页</span>
        <button
          class="button button-sm"
          type="button"
          :disabled="page + 1 >= pageCount || itemsLoading"
          @click="goPage(1)"
        >
          下一页
        </button>
      </div>
    </section>

    <details class="panel technical">
      <summary>技术详情与兜底入口</summary>
      <dl class="detail-grid">
        <dt>任务 ID</dt>
        <dd><code>{{ task.task_id }}</code></dd>
        <dt>计划</dt>
        <dd><code>{{ task.plan_id }}@{{ task.plan_version }}</code></dd>
        <dt>站点键</dt>
        <dd><code>{{ task.site_key || "-" }}</code></dd>
        <dt>域名键</dt>
        <dd><code>{{ task.domain_key || "-" }}</code></dd>
        <dt>批次</dt>
        <dd><code>{{ task.batch_id || "-" }}</code></dd>
        <dt>创建</dt>
        <dd>{{ formatTime(task.created_at) }}</dd>
        <dt>结束</dt>
        <dd>{{ formatTime(task.finished_at) }}</dd>
      </dl>
      <p class="muted">
        旧版 `/` 控制台保留为技术兜底，仅在排查前端问题时使用。
        <a href="/" target="_blank" rel="noreferrer">打开旧版控制台</a>
      </p>
    </details>
  </template>

  <p v-else class="muted">正在读取任务…</p>
</template>
