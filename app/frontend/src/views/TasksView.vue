<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";
import {
  archiveTask,
  createTask,
  getHealth,
  getRules,
  getTasks,
  restoreTask,
  startTask,
  type Health,
  type RuleEntry,
  type TaskSummary,
} from "../api";
import {
  coverageLabel,
  formatTime,
  outcomeLabel,
  stopReasonLabel,
  taskStateLabel,
  taskStateTone,
} from "../ui";

const router = useRouter();
const health = ref<Health | null>(null);
const healthError = ref("");
const rules = ref<RuleEntry[]>([]);
const rulesConfigured = ref(false);
const rulesError = ref("");
const tasks = ref<TaskSummary[]>([]);
const total = ref(0);
const loading = ref(false);
const loadingMore = ref(false);
const error = ref("");
const actionNotice = ref("");
const busy = ref("");

const filters = reactive({
  state: "",
  taskType: "",
  includeArchived: false,
});
const createForm = reactive({
  ruleKey: "",
  taskType: "product" as "product" | "discovery",
  maxProducts: 20,
  maxUrls: 100,
  maxSeconds: 180,
  maxAttempts: 2,
});
const createBusy = ref(false);
const createStatus = ref("");
const createError = ref(false);

const pageSize = 50;
const offset = ref(0);
let refreshTimer: ReturnType<typeof setInterval> | undefined;

const validRules = computed(() =>
  rules.value.filter(
    (rule) =>
      rule.valid &&
      rule.rule_id &&
      rule.rule_version &&
      rule.task_types.length > 0,
  ),
);
const selectedRule = computed(() =>
  validRules.value.find(
    (rule) => `${rule.rule_id}@${rule.rule_version}` === createForm.ruleKey,
  ),
);
const taskTypeOptions = computed(() =>
  selectedRule.value?.task_types?.length
    ? selectedRule.value.task_types
    : ["product", "discovery"],
);
const ruleContext = computed(() => {
  const rule = selectedRule.value;
  if (!rule) return "选择规则包后显示站点、市场与语言。";
  return [
    rule.site,
    rule.market ? `市场 ${rule.market}` : "",
    rule.locale ? `语言 ${rule.locale}` : "",
    rule.currency ? rule.currency : "",
  ]
    .filter(Boolean)
    .join(" · ");
});
const hasActive = computed(() =>
  tasks.value.some((task) =>
    ["QUEUED", "RUNNING", "PAUSING", "CANCELLING"].includes(task.state),
  ),
);
const queuedCount = computed(
  () => tasks.value.filter((task) => task.state === "QUEUED").length,
);
const workerText = computed(() => {
  if (healthError.value) return "服务状态未知";
  if (!health.value) return "读取服务状态…";
  if (health.value.worker === "managed") {
    return `托管 worker（任务槽位 ${health.value.max_tasks ?? "-"}）`;
  }
  if (health.value.worker === "external") return "外部 worker";
  return "未检测到 worker";
});
const queueNote = computed(() => {
  if (!queuedCount.value) return "";
  if (healthError.value || !health.value) {
    return "有任务排队，但服务状态未知；若是只读或外部 worker 模式，需要独立 worker 领取。";
  }
  if (health.value.worker === "external") {
    return "有任务排队：当前服务未托管 worker，需要独立 worker 进程领取。";
  }
  if (health.value.worker === "managed") {
    return "有任务排队：托管 worker 会领取；若长时间不变，检查 worker 日志和任务锁。";
  }
  return "有任务排队：未检测到 worker，任务不会自动执行。";
});

watch(selectedRule, (rule) => {
  if (!rule) return;
  if (!rule.task_types.includes(createForm.taskType)) {
    createForm.taskType = (
      rule.task_types.includes("product")
        ? "product"
        : rule.task_types.includes("discovery")
          ? "discovery"
          : rule.task_types[0]
    ) as "product" | "discovery";
  }
});

function requestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function loadHealth() {
  try {
    health.value = await getHealth();
    healthError.value = "";
  } catch (exc) {
    healthError.value = exc instanceof Error ? exc.message : String(exc);
  }
}

async function loadRules() {
  rulesError.value = "";
  try {
    const payload = await getRules();
    rulesConfigured.value = payload.configured;
    rules.value = payload.items;
    if (!payload.configured) {
      rulesError.value = "服务未配置 --rules-dir，当前只能查看任务。";
      return;
    }
    if (
      !validRules.value.some(
        (rule) => `${rule.rule_id}@${rule.rule_version}` === createForm.ruleKey,
      )
    ) {
      const first = validRules.value[0];
      createForm.ruleKey = first
        ? `${first.rule_id}@${first.rule_version}`
        : "";
    }
  } catch (exc) {
    rulesError.value = exc instanceof Error ? exc.message : String(exc);
  }
}

async function loadList(reset = true) {
  if (reset) {
    offset.value = 0;
    loading.value = true;
  } else {
    loadingMore.value = true;
  }
  error.value = "";
  try {
    const page = await getTasks({
      states: filters.state ? [filters.state] : undefined,
      taskType: filters.taskType || undefined,
      includeArchived: filters.includeArchived,
      limit: pageSize,
      offset: offset.value,
    });
    tasks.value = reset ? page.items : [...tasks.value, ...page.items];
    total.value = page.total;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    loading.value = false;
    loadingMore.value = false;
  }
}

async function loadMore() {
  offset.value = tasks.value.length;
  await loadList(false);
}

function applyFilters() {
  void loadList(true);
}

function resetFilters() {
  filters.state = "";
  filters.taskType = "";
  filters.includeArchived = false;
  void loadList(true);
}

async function createAndStart() {
  const rule = selectedRule.value;
  if (!rule?.rule_id || !rule.rule_version) {
    createError.value = true;
    createStatus.value = "请选择可用的规则包。";
    return;
  }
  createBusy.value = true;
  createError.value = false;
  createStatus.value = "创建中…";
  let taskId = "";
  try {
    const created = await createTask({
      request_id: requestId(),
      rule_id: rule.rule_id,
      rule_version: rule.rule_version,
      task_type: createForm.taskType,
      limits: {
        max_products: Number(createForm.maxProducts) || 20,
        max_urls: Number(createForm.maxUrls) || 100,
        max_seconds: Number(createForm.maxSeconds) || 180,
        max_attempts: Number(createForm.maxAttempts) || 2,
      },
    });
    taskId = created.task.task_id;
    if (created.task.state === "DRAFT") {
      createStatus.value = `已创建 ${taskId}，正在启动…`;
      await startTask(taskId);
    }
    createStatus.value = `任务 ${taskId} 已进入队列。`;
    await router.push(`/tasks/${taskId}`);
  } catch (exc) {
    createError.value = true;
    createStatus.value = taskId
      ? `任务 ${taskId} 已创建，但启动或跳转失败：${exc instanceof Error ? exc.message : String(exc)}；请在任务详情重试。`
      : `创建失败：${exc instanceof Error ? exc.message : String(exc)}`;
    if (taskId) await router.push(`/tasks/${taskId}`);
  } finally {
    createBusy.value = false;
  }
}

async function archiveOrRestore(task: TaskSummary, action: "archive" | "restore") {
  busy.value = `${action}-${task.task_id}`;
  error.value = "";
  try {
    if (action === "archive") await archiveTask(task.task_id);
    else await restoreTask(task.task_id);
    actionNotice.value =
      action === "archive"
        ? `任务 ${task.task_id} 已归档。`
        : `任务 ${task.task_id} 已还原。`;
    await loadList(true);
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    busy.value = "";
  }
}

function canArchive(task: TaskSummary): boolean {
  return (
    !task.archived_at &&
    (task.state === "FINISHED" || task.state === "CANCELLED")
  );
}

function canRestore(task: TaskSummary): boolean {
  return Boolean(task.archived_at);
}

function taskTypeLabel(type: string): string {
  return type === "discovery" ? "发现" : "商品";
}

function countsText(task: TaskSummary): string {
  const counts = task.counts || {};
  if (task.task_type === "discovery") {
    return `发现 ${counts.discovered_urls ?? 0} · 失败 ${counts.failed_products ?? counts.failed ?? 0}`;
  }
  return `有效 ${counts.valid_products ?? 0} · 排除 ${counts.excluded_products ?? counts.excluded ?? 0} · 失败 ${counts.failed_products ?? counts.failed ?? 0}`;
}

function qualityCount(task: TaskSummary): number {
  return Array.isArray(task.quality_exceptions)
    ? task.quality_exceptions.length
    : 0;
}

onMounted(async () => {
  await Promise.all([loadHealth(), loadRules(), loadList(true)]);
  refreshTimer = setInterval(() => {
    if (document.visibilityState === "visible" && hasActive.value) {
      void loadHealth();
      void loadList(true);
    }
  }, 10_000);
});

onBeforeUnmount(() => {
  if (refreshTimer !== undefined) clearInterval(refreshTimer);
});
</script>

<template>
  <div class="page-head">
    <div>
      <h1>全部任务</h1>
      <p class="muted">
        技术视图：按任务账本查看状态、计数、质量、控制和导出；业务批次从“采集批次”进入。
      </p>
    </div>
    <div class="page-actions">
      <button class="button" type="button" :disabled="loading" @click="loadList(true)">
        {{ loading ? "刷新中…" : "刷新任务" }}
      </button>
      <RouterLink class="button" to="/batches">批次工作台</RouterLink>
    </div>
  </div>

  <p v-if="error" class="notice danger" role="alert">
    读取失败：{{ error }}
    <button class="text-button" type="button" @click="loadList(true)">重试</button>
  </p>
  <p v-if="actionNotice" class="notice success" role="status">{{ actionNotice }}</p>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>服务与 worker</h2>
        <p class="muted">
          {{ workerText }} · 账本 {{ health?.tasks ?? "-" }} 个任务
          <span v-if="queuedCount"> · {{ queuedCount }} 个排队</span>
        </p>
      </div>
      <span class="badge" :class="healthError ? 'danger' : health ? 'success' : 'muted'">
        {{ healthError ? "状态未知" : health ? "服务在线" : "读取中" }}
      </span>
    </div>
    <p v-if="queueNote" class="notice warning" role="status">{{ queueNote }}</p>
    <p v-else class="muted">页面关闭不停止后台；任务控制请求由服务账本确认。</p>
  </section>

  <details class="panel create-panel">
    <summary>创建任务（技术）</summary>
    <p v-if="rulesError" class="notice danger" role="alert">{{ rulesError }}</p>
    <form class="form-grid" @submit.prevent="createAndStart">
      <label class="field field-wide">
        <span>规则包</span>
        <select v-model="createForm.ruleKey" :disabled="!rulesConfigured || !validRules.length">
          <option value="">选择规则包</option>
          <option
            v-for="rule in validRules"
            :key="`${rule.rule_id}@${rule.rule_version}`"
            :value="`${rule.rule_id}@${rule.rule_version}`"
          >
            {{ rule.site || rule.rule_id }} · {{ rule.rule_id }}@{{ rule.rule_version }}
            <template v-if="rule.market"> · {{ rule.market }}</template>
          </option>
        </select>
        <small class="hint">{{ ruleContext }}</small>
      </label>
      <label class="field">
        <span>类型</span>
        <select v-model="createForm.taskType" :disabled="createBusy">
          <option v-for="type in taskTypeOptions" :key="type" :value="type">
            {{ taskTypeLabel(type) }}
          </option>
        </select>
      </label>
      <label class="field">
        <span>最大商品</span>
        <input v-model.number="createForm.maxProducts" type="number" min="1" />
      </label>
      <label class="field">
        <span>最大 URL</span>
        <input v-model.number="createForm.maxUrls" type="number" min="1" />
      </label>
      <label class="field">
        <span>最大秒数</span>
        <input v-model.number="createForm.maxSeconds" type="number" min="1" />
      </label>
      <label class="field">
        <span>最大尝试</span>
        <input v-model.number="createForm.maxAttempts" type="number" min="1" max="10" />
      </label>
      <div class="form-actions field-wide">
        <button
          class="button button-primary"
          type="submit"
          :disabled="createBusy || !rulesConfigured || !selectedRule"
        >
          {{ createBusy ? "创建中…" : "创建并启动" }}
        </button>
      </div>
    </form>
    <p
      v-if="createStatus"
      class="notice"
      :class="createError ? 'danger' : 'success'"
      role="status"
    >
      {{ createStatus }}
    </p>
  </details>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>任务列表</h2>
        <p class="muted">共 {{ total }} 个任务；显示 {{ tasks.length }} 个。</p>
      </div>
    </div>

    <form class="filters" @submit.prevent="applyFilters">
      <label class="field field-inline">
        <span>状态</span>
        <select v-model="filters.state">
          <option value="">全部</option>
          <option value="DRAFT">草稿</option>
          <option value="QUEUED">排队中</option>
          <option value="RUNNING">运行中</option>
          <option value="PAUSING">暂停中</option>
          <option value="PAUSED">已暂停</option>
          <option value="CANCELLING">取消中</option>
          <option value="CANCELLED">已取消</option>
          <option value="FINISHED">已结束</option>
        </select>
      </label>
      <label class="field field-inline">
        <span>类型</span>
        <select v-model="filters.taskType">
          <option value="">全部</option>
          <option value="product">商品</option>
          <option value="discovery">发现</option>
        </select>
      </label>
      <label class="check">
        <input v-model="filters.includeArchived" type="checkbox" />
        <span>包含归档</span>
      </label>
      <div class="filter-actions">
        <button class="button" type="button" :disabled="loading" @click="resetFilters">
          重置
        </button>
        <button class="button button-primary" type="submit" :disabled="loading">
          应用筛选
        </button>
      </div>
    </form>

    <p class="scroll-hint">表格可左右滚动查看完整内容。</p>
    <div class="table-wrap">
      <table class="task-table">
        <thead>
          <tr>
            <th>任务</th>
            <th>站点 / 方案</th>
            <th>状态</th>
            <th>结果 / 覆盖</th>
            <th class="col-counts">计数</th>
            <th class="col-updated">更新</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.task_id">
            <td>
              <RouterLink class="text-link strong" :to="`/tasks/${task.task_id}`">
                {{ task.task_id }}
              </RouterLink>
              <span v-if="task.archived_at" class="badge muted">归档</span>
              <span class="cell-note">
                {{ taskTypeLabel(task.task_type) }} · {{ task.market || "未设置市场" }}
              </span>
            </td>
            <td>
              {{ task.site_key || "-" }}
              <span class="cell-note">
                <code>{{ task.plan_id }}@{{ task.plan_version }}</code>
              </span>
              <RouterLink
                v-if="task.batch_id"
                class="cell-note text-link"
                :to="`/batches/${task.batch_id}`"
              >
                所属批次
              </RouterLink>
            </td>
            <td>
              <span class="badge" :class="taskStateTone(task.state)">
                {{ taskStateLabel(task.state) }}
              </span>
              <span v-if="task.outcome" class="cell-note">
                {{ outcomeLabel(task.outcome) }}
              </span>
            </td>
            <td>
              <div>{{ task.outcome ? outcomeLabel(task.outcome) : "-" }}</div>
              <div class="muted">停止：{{ stopReasonLabel(task.stop_reason) }}</div>
              <div class="muted">
                覆盖 {{ coverageLabel(String(task.coverage.status || "")) }}
              </div>
              <span v-if="qualityCount(task)" class="badge warning">
                质量异常 {{ qualityCount(task) }}
              </span>
            </td>
            <td class="col-counts">{{ countsText(task) }}</td>
            <td class="col-updated nowrap">{{ formatTime(task.updated_at) }}</td>
            <td>
              <div class="row-actions">
                <RouterLink class="button button-sm" :to="`/tasks/${task.task_id}`">
                  详情
                </RouterLink>
                <button
                  v-if="canArchive(task)"
                  class="button button-sm"
                  type="button"
                  :disabled="Boolean(busy)"
                  @click="archiveOrRestore(task, 'archive')"
                >
                  归档
                </button>
                <button
                  v-if="canRestore(task)"
                  class="button button-sm"
                  type="button"
                  :disabled="Boolean(busy)"
                  @click="archiveOrRestore(task, 'restore')"
                >
                  还原
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="!tasks.length && !loading">
            <td colspan="7" class="muted">没有符合条件的任务。</td>
          </tr>
          <tr v-if="loading && !tasks.length">
            <td colspan="7" class="muted">正在读取任务…</td>
          </tr>
        </tbody>
      </table>
    </div>
    <div v-if="tasks.length < total" class="form-actions">
      <button class="button" type="button" :disabled="loadingMore" @click="loadMore">
        {{ loadingMore ? "加载中…" : "加载更多" }}
      </button>
    </div>
  </section>
</template>
