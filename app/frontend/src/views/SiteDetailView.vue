<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink } from "vue-router";
import {
  cancelTask,
  getBatch,
  getTaskItems,
  pauseTask,
  resumeTask,
  taskExportUrl,
  type BatchSite,
  type BatchSummary,
  type TaskItem,
} from "../api";
import {
  READINESS_LABELS,
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

async function load() {
  loading.value = true;
  error.value = "";
  try {
    batch.value = await getBatch(props.id);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    loading.value = false;
  }
}

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
          没有匹配到受管规则包；需要技术角色在线下构建和复核后重新导入。
        </template>
        <template v-else-if="site.readiness === 'building'">
          规则包尚未可采，页面不会把它显示成可启动。
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
