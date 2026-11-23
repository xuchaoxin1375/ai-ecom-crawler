<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";
import {
  archiveBatch,
  batchExportUrl,
  cancelBatch,
  getBatch,
  importSites,
  pauseBatch,
  pauseTask,
  restoreBatch,
  resumeTask,
  startBatch,
  type BatchSite,
  type BatchSummary,
  type ImportReport,
} from "../api";
import {
  BATCH_STATUS_LABELS,
  READINESS_LABELS,
  batchStatusTone,
  formatTime,
  outcomeLabel,
  readinessTone,
  siteStatusText,
  stopReasonLabel,
  taskStateLabel,
  taskStateTone,
} from "../ui";

const props = defineProps<{ id: string }>();
const route = useRoute();
const router = useRouter();

type SiteFilter =
  | "all"
  | "ready"
  | "not_started"
  | "needs"
  | "running"
  | "paused"
  | "queued"
  | "finished"
  | "failed"
  | "invalid";

const batch = ref<BatchSummary | null>(null);
const loading = ref(false);
const error = ref("");
const busy = ref("");
const actionNotice = ref("");
const actionSkipped = ref<Array<{ domain: string; reason: string }>>([]);
const confirm = ref<"" | "cancel" | "archive">("");
const fullCatalog = ref(false);
const rerunFinished = ref(false);
const siteFilter = ref<SiteFilter>("all");
const importOpen = ref(false);
const importText = ref("");
const importReport = ref<ImportReport | null>(null);
let timer: ReturnType<typeof setInterval> | undefined;

const sites = computed(() => batch.value?.sites || []);
const counts = computed(() => batch.value?.counts);
const hasActive = computed(() => {
  const value = counts.value;
  if (!value) return false;
  return value.running + value.queued + value.draft > 0;
});
const canPause = computed(() => (counts.value?.running || 0) > 0);
const canStart = computed(
  () => (counts.value?.startable || 0) > 0 || rerunFinished.value,
);
const canCancel = computed(() => {
  const value = counts.value;
  if (!value) return false;
  return value.running + value.queued + value.paused + value.draft > 0;
});

function matches(site: BatchSite, filter: SiteFilter): boolean {
  const state = site.task?.state || "";
  const outcome = site.task?.outcome || "";
  if (filter === "all") return true;
  if (filter === "ready") return site.readiness === "ready";
  if (filter === "not_started") return site.readiness === "ready" && !site.task_id;
  if (filter === "needs") {
    return site.readiness === "needs_onboarding" || site.readiness === "building";
  }
  if (filter === "invalid") {
    return site.readiness === "invalid" || site.readiness === "duplicate";
  }
  if (filter === "running") {
    return state === "RUNNING" || state === "PAUSING" || state === "CANCELLING";
  }
  if (filter === "paused") return state === "PAUSED";
  if (filter === "queued") return state === "QUEUED";
  if (filter === "finished") return state === "FINISHED" && outcome === "COMPLETED";
  if (filter === "failed") {
    return state === "FINISHED" && outcome !== "COMPLETED";
  }
  return false;
}

const filterOptions = computed(() => {
  const options: Array<{ key: SiteFilter; label: string; count: number }> = [
    { key: "all", label: "全部", count: sites.value.length },
    { key: "ready", label: "可采", count: sites.value.filter((s) => s.readiness === "ready").length },
    {
      key: "not_started",
      label: "未开始",
      count: sites.value.filter((s) => s.readiness === "ready" && !s.task_id).length,
    },
    {
      key: "needs",
      label: "待接入",
      count: sites.value.filter(
        (s) => s.readiness === "needs_onboarding" || s.readiness === "building",
      ).length,
    },
    {
      key: "running",
      label: "运行",
      count: sites.value.filter((s) =>
        ["RUNNING", "PAUSING", "CANCELLING"].includes(s.task?.state || ""),
      ).length,
    },
    {
      key: "paused",
      label: "暂停",
      count: sites.value.filter((s) => s.task?.state === "PAUSED").length,
    },
    {
      key: "queued",
      label: "排队",
      count: sites.value.filter((s) => s.task?.state === "QUEUED").length,
    },
    {
      key: "finished",
      label: "已完成",
      count: sites.value.filter(
        (s) => s.task?.state === "FINISHED" && s.task?.outcome === "COMPLETED",
      ).length,
    },
    {
      key: "failed",
      label: "失败／部分",
      count: sites.value.filter(
        (s) => s.task?.state === "FINISHED" && s.task?.outcome !== "COMPLETED",
      ).length,
    },
    {
      key: "invalid",
      label: "无效／重复",
      count: sites.value.filter(
        (s) => s.readiness === "invalid" || s.readiness === "duplicate",
      ).length,
    },
  ];
  return options.filter((option) => option.key === "all" || option.count > 0);
});

const visibleSites = computed(() =>
  sites.value.filter((site) => matches(site, siteFilter.value)),
);

async function load(silent = false) {
  if (!silent) loading.value = true;
  error.value = "";
  try {
    batch.value = await getBatch(props.id);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    loading.value = false;
  }
}

function applyFlash() {
  if (route.query.created) {
    if (route.query.start_error) {
      actionNotice.value =
        "批次已保存，但启动可采站点失败；请重试或在站点详情中处理。";
    } else if (route.query.started !== undefined) {
      actionNotice.value = `批次已保存：受理 ${route.query.started} 个站点，跳过 ${route.query.skipped || 0} 个。`;
    } else {
      actionNotice.value = "批次已保存。";
    }
    void router.replace({ path: route.path });
  }
}

async function runAction(
  action: "start" | "pause" | "cancel" | "archive" | "restore",
) {
  busy.value = action;
  error.value = "";
  actionSkipped.value = [];
  try {
    if (action === "start") {
      const result = await startBatch(props.id, {
        ...(fullCatalog.value
          ? {
              limits: {
                max_urls: null,
                max_products: null,
                max_seconds: null,
                max_attempts: 2,
              },
              archive_mode: "sample",
              archive_sample_limit: 20,
            }
          : {}),
        rerun_finished: rerunFinished.value,
      });
      batch.value = result.batch;
      actionNotice.value = `已受理 ${result.accepted.length} 个站点，跳过 ${result.skipped.length} 个。`;
      actionSkipped.value = result.skipped.map((item) => ({
        domain: item.domain,
        reason: item.reason,
      }));
    } else if (action === "pause") {
      const result = await pauseBatch(props.id);
      batch.value = result.batch;
      actionNotice.value = `暂停请求已受理 ${result.accepted.length} 个，跳过 ${result.skipped.length} 个。`;
      actionSkipped.value = result.skipped.map((item) => ({
        domain: item.domain,
        reason: item.reason,
      }));
    } else if (action === "cancel") {
      const result = await cancelBatch(props.id);
      batch.value = result.batch;
      actionNotice.value = `取消请求已受理 ${result.accepted.length} 个，跳过 ${result.skipped.length} 个；已有结果保留。`;
      actionSkipped.value = result.skipped.map((item) => ({
        domain: item.domain,
        reason: item.reason,
      }));
    } else if (action === "archive") {
      const result = await archiveBatch(props.id);
      batch.value = result.batch;
      actionNotice.value = "批次已归档，可从“包含归档”列表恢复。";
    } else {
      const result = await restoreBatch(props.id);
      batch.value = result.batch;
      actionNotice.value = "批次已恢复。";
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    busy.value = "";
    confirm.value = "";
  }
}

async function quickTask(site: BatchSite, action: "pause" | "resume") {
  if (!site.task_id) return;
  busy.value = `${action}-${site.site_key}`;
  try {
    if (action === "pause") await pauseTask(site.task_id);
    else await resumeTask(site.task_id);
    await load(true);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    busy.value = "";
  }
}

async function runImport() {
  if (!importText.value.trim()) return;
  busy.value = "import";
  error.value = "";
  importReport.value = null;
  try {
    const result = await importSites(props.id, {
      name: batch.value?.name || "batch",
      sites_text: importText.value,
    });
    batch.value = result.batch;
    importReport.value = result.import;
    importText.value = "";
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    busy.value = "";
  }
}

onMounted(async () => {
  await load();
  applyFlash();
  timer = setInterval(() => {
    if (hasActive.value && document.visibilityState === "visible") {
      void load(true);
    }
  }, 5000);
});

onBeforeUnmount(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <div v-if="error && !batch" class="empty">
    <strong>读取批次失败</strong>
    <p class="notice danger">{{ error }}</p>
    <RouterLink class="button" to="/batches">返回批次列表</RouterLink>
  </div>

  <template v-else-if="batch">
    <div class="page-head">
      <div>
        <RouterLink class="back-link" to="/batches">← 返回批次列表</RouterLink>
        <h1>{{ batch.name }}</h1>
        <p class="muted">
          {{ batch.country || batch.market || "未设置国家" }} ·
          {{ batch.language || "未设置语言" }} ·
          {{ batch.category || "未设置品类" }}
          <span v-if="batch.note"> · {{ batch.note }}</span>
        </p>
      </div>
      <div class="page-actions">
        <button
          class="button button-primary"
          type="button"
          :disabled="!canStart || Boolean(busy)"
          :title="canStart ? '启动可采且未开始的站点；勾选复跑时也包含已完成站点' : '没有可启动的可采站点'"
          @click="runAction('start')"
        >
          {{ busy === "start"
            ? "启动中…"
            : rerunFinished
              ? `复跑可采站点 (${batch.counts.ready})`
              : `启动可采站点 (${batch.counts.startable})` }}
        </button>
        <button
          class="button"
          type="button"
          :disabled="!canPause || Boolean(busy)"
          :title="canPause ? '暂停运行中的任务' : '没有运行中的任务'"
          @click="runAction('pause')"
        >
          暂停
        </button>
        <button
          class="button button-danger"
          type="button"
          :disabled="!canCancel || Boolean(busy)"
          :title="canCancel ? '取消批次中排队或运行的任务' : '没有可取消的任务'"
          @click="confirm = 'cancel'"
        >
          取消批次
        </button>
        <a class="button" :href="batchExportUrl(batch.batch_id)" download>
          导出批次 ZIP
        </a>
      </div>
      <label class="check batch-full-catalog">
        <input v-model="fullCatalog" type="checkbox" />
        全量采集（不额外设服务层数量／时长上限；sample 存档 20 页）
      </label>
      <label class="check batch-full-catalog">
        <input v-model="rerunFinished" type="checkbox" />
        复跑已完成站点（保留旧任务，创建新任务）
      </label>
    </div>

    <p v-if="error" class="notice danger" role="alert">{{ error }}</p>
    <p v-if="actionNotice" class="notice success" role="status">
      {{ actionNotice }}
      <span v-if="actionSkipped.length" class="block">
        跳过原因：
        <span v-for="(item, index) in actionSkipped" :key="`${item.domain}-${index}`">
          {{ item.domain }}（{{ item.reason }}）<template v-if="index < actionSkipped.length - 1">；</template>
        </span>
      </span>
    </p>

    <div v-if="confirm === 'cancel'" class="confirm-bar danger" role="alertdialog" aria-label="确认取消批次">
      <div>
        <strong>取消整个批次？</strong>
        <p>将取消排队、运行和暂停中的任务；已经产生的部分结果保留，可继续导出。</p>
      </div>
      <div class="confirm-actions">
        <button class="button" type="button" @click="confirm = ''">返回</button>
        <button class="button button-danger" type="button" :disabled="Boolean(busy)" @click="runAction('cancel')">
          确认取消批次
        </button>
      </div>
    </div>

    <div v-if="confirm === 'archive'" class="confirm-bar" role="alertdialog" aria-label="确认归档批次">
      <div>
        <strong>归档这个批次？</strong>
        <p>归档只影响列表可见性，不删除任务和结果；可在“包含归档”中恢复。</p>
      </div>
      <div class="confirm-actions">
        <button class="button" type="button" @click="confirm = ''">返回</button>
        <button class="button button-primary" type="button" :disabled="Boolean(busy)" @click="runAction('archive')">
          确认归档
        </button>
      </div>
    </div>

    <section class="batch-hero">
      <div>
        <span class="badge" :class="batchStatusTone(batch.status)">
          {{ BATCH_STATUS_LABELS[batch.status] }}
        </span>
        <span class="muted">更新 {{ formatTime(batch.updated_at) }}</span>
      </div>
      <div class="batch-hero-actions">
        <button
          v-if="!batch.archived_at"
          class="text-button"
          type="button"
          @click="confirm = 'archive'"
        >
          归档批次
        </button>
        <button
          v-else
          class="text-button"
          type="button"
          :disabled="Boolean(busy)"
          @click="runAction('restore')"
        >
          恢复批次
        </button>
      </div>
    </section>

    <section class="cards six" aria-label="批次汇总">
      <div class="card">
        <span>站点</span>
        <strong>{{ batch.counts.sites }}</strong>
        <small>可采 {{ batch.counts.ready }} · 待接入 {{ batch.counts.needs_onboarding + batch.counts.building }}</small>
      </div>
      <div class="card">
        <span>可启动</span>
        <strong>{{ batch.counts.startable }}</strong>
        <small>可采且未开始</small>
      </div>
      <div class="card">
        <span>运行／排队</span>
        <strong>{{ batch.counts.running }} / {{ batch.counts.queued }}</strong>
        <small>暂停 {{ batch.counts.paused }}</small>
      </div>
      <div class="card">
        <span>已完成</span>
        <strong>{{ batch.counts.finished }}</strong>
        <small>部分 {{ batch.counts.partial_tasks }} · 失败 {{ batch.counts.failed }}</small>
      </div>
      <div class="card">
        <span>有效商品</span>
        <strong>{{ batch.valid_products }}</strong>
        <small>失败商品 {{ batch.failed_products }}</small>
      </div>
      <div class="card">
        <span>无效／重复</span>
        <strong>{{ batch.counts.invalid + batch.counts.duplicate }}</strong>
        <small>不进入采集</small>
      </div>
    </section>

    <p v-if="batch.counts.queued" class="notice warning" role="status">
      {{ batch.counts.queued }} 个任务在排队。若状态长时间不变，检查 worker 是否在运行；
      <a href="/">打开内部任务控制台</a> 查看服务与任务详情。
    </p>

    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>站点清单</h2>
          <p class="muted">
            共 {{ batch.counts.sites }} 个站点；未接入和无效条目保留在批次中，不计入任务失败。
          </p>
        </div>
        <div class="panel-head-actions">
          <button class="button button-sm" type="button" :disabled="loading" @click="load()">
            {{ loading ? "刷新中…" : "刷新" }}
          </button>
          <button class="button button-sm" type="button" @click="importOpen = !importOpen">
            {{ importOpen ? "收起导入" : "继续导入站点" }}
          </button>
        </div>
      </div>

      <div v-if="importOpen" class="import-box">
        <label class="field">
          <span>追加站点（每行一个网址或域名）</span>
          <textarea v-model="importText" rows="4" spellcheck="false"></textarea>
        </label>
        <div class="form-actions">
          <button
            class="button button-primary"
            type="button"
            :disabled="Boolean(busy) || !importText.trim()"
            @click="runImport"
          >
            {{ busy === "import" ? "导入中…" : "导入并匹配" }}
          </button>
        </div>
        <div v-if="importReport" class="notice" role="status">
          <strong>
            本次导入：可采 {{ importReport.summary.ready }} · 待接入
            {{ importReport.summary.needs_onboarding }} · 重复
            {{ importReport.summary.duplicate }} · 无效 {{ importReport.summary.invalid }}
          </strong>
          <ul
            v-if="importReport.items.some((item) => item.readiness === 'invalid' || item.readiness === 'duplicate')"
            class="issue-list"
          >
            <li
              v-for="(item, index) in importReport.items.filter(
                (entry) => entry.readiness === 'invalid' || entry.readiness === 'duplicate',
              )"
              :key="`${item.input_value}-${index}`"
            >
              <code>{{ item.input_value }}</code>：{{ item.reason }}
            </li>
          </ul>
        </div>
      </div>

      <div class="filter-chips" role="group" aria-label="站点筛选">
        <button
          v-for="option in filterOptions"
          :key="option.key"
          class="filter-chip"
          :class="{ active: siteFilter === option.key }"
          type="button"
          @click="siteFilter = option.key"
        >
          {{ option.label }} <span>{{ option.count }}</span>
        </button>
      </div>

      <p class="scroll-hint">表格可左右滚动查看完整内容。</p>
      <div class="table-wrap">
        <table class="site-table">
          <thead>
            <tr>
              <th>站点</th>
              <th>接入状态</th>
              <th>任务状态</th>
              <th>有效／失败</th>
              <th class="col-stop">停止原因</th>
              <th class="col-updated">更新</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="site in visibleSites" :key="site.site_key">
              <td>
                <RouterLink
                  class="text-link strong"
                  :to="`/batches/${batch.batch_id}/sites/${encodeURIComponent(site.site_key)}`"
                >
                  {{ site.domain }}
                </RouterLink>
                <span class="cell-note">{{ site.note || site.input_value }}</span>
              </td>
              <td>
                <span class="badge" :class="readinessTone(site.readiness)">
                  {{ READINESS_LABELS[site.readiness] }}
                </span>
                <span class="cell-note">{{ siteStatusText(site.readiness, site.task?.state || null) }}</span>
              </td>
              <td>
                <template v-if="site.task">
                  <span class="badge" :class="taskStateTone(site.task.state)">
                    {{ taskStateLabel(site.task.state) }}
                  </span>
                  <span v-if="site.task.outcome" class="cell-note">
                    {{ outcomeLabel(site.task.outcome) }}
                  </span>
                </template>
                <span v-else class="muted">-</span>
              </td>
              <td>
                <template v-if="site.task">
                  {{ site.task.counts.valid_products ?? 0 }} /
                  {{ site.task.counts.failed_products ?? 0 }}
                </template>
                <span v-else class="muted">-</span>
              </td>
              <td class="col-stop">{{ stopReasonLabel(site.task?.stop_reason) }}</td>
              <td class="nowrap col-updated">{{ formatTime(site.task?.updated_at || site.updated_at) }}</td>
              <td>
                <div class="row-actions">
                  <button
                    v-if="site.task?.state === 'RUNNING'"
                    class="button button-sm"
                    type="button"
                    :disabled="Boolean(busy)"
                    @click="quickTask(site, 'pause')"
                  >
                    暂停
                  </button>
                  <button
                    v-if="site.task?.state === 'PAUSED'"
                    class="button button-sm"
                    type="button"
                    :disabled="Boolean(busy)"
                    @click="quickTask(site, 'resume')"
                  >
                    继续
                  </button>
                  <RouterLink
                    class="button button-sm"
                    :to="`/batches/${batch.batch_id}/sites/${encodeURIComponent(site.site_key)}`"
                  >
                    详情
                  </RouterLink>
                </div>
              </td>
            </tr>
            <tr v-if="!visibleSites.length">
              <td colspan="7" class="muted">当前筛选没有站点。</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </template>

  <p v-else class="muted">正在读取批次…</p>
</template>
