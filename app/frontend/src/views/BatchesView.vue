<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import { RouterLink } from "vue-router";
import { getBatches, type BatchSummary } from "../api";
import {
  BATCH_STATUS_LABELS,
  batchStatusTone,
  formatTime,
} from "../ui";

const batches = ref<BatchSummary[]>([]);
const total = ref(0);
const loading = ref(false);
const error = ref("");
const filters = reactive({
  status: "",
  country: "",
  category: "",
  includeArchived: false,
});

const summary = computed(() => {
  const counts = { running: 0, attention: 0, ready: 0, needs: 0 };
  for (const batch of batches.value) {
    if (batch.status === "RUNNING") counts.running += 1;
    if (batch.status === "PARTIAL_READY" || batch.status === "PARTIAL") {
      counts.attention += 1;
    }
    counts.ready += batch.counts.ready;
    counts.needs += batch.counts.needs_onboarding + batch.counts.building;
  }
  return counts;
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const payload = await getBatches({
      status: filters.status || undefined,
      country: filters.country.trim() || undefined,
      category: filters.category.trim() || undefined,
      includeArchived: filters.includeArchived,
    });
    batches.value = payload.items;
    total.value = payload.total;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    loading.value = false;
  }
}

function resetFilters() {
  filters.status = "";
  filters.country = "";
  filters.category = "";
  filters.includeArchived = false;
  void load();
}

onMounted(load);
</script>

<template>
  <div class="page-head">
    <div>
      <h1>采集批次</h1>
      <p class="muted">
        按项目组织站点：先导入并匹配规则包，再启动可采站点。未接入站点保留在批次中，不计为失败。
      </p>
    </div>
    <RouterLink class="button button-primary" to="/batches/new">新建批次</RouterLink>
  </div>

  <section class="panel filter-panel" aria-label="批次筛选">
    <form class="filters" @submit.prevent="load">
      <label class="field field-inline">
        <span>状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option value="DRAFT">草稿</option>
          <option value="PARTIAL_READY">部分就绪</option>
          <option value="RUNNING">运行中</option>
          <option value="PARTIAL">部分完成</option>
          <option value="FINISHED">已完成</option>
          <option value="ARCHIVED">已归档</option>
        </select>
      </label>
      <label class="field field-inline">
        <span>国家／市场</span>
        <input v-model="filters.country" placeholder="如 FR" />
      </label>
      <label class="field field-inline">
        <span>品类</span>
        <input v-model="filters.category" placeholder="如 手工／纺织" />
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
          {{ loading ? "筛选…" : "应用筛选" }}
        </button>
      </div>
    </form>
  </section>

  <p v-if="error" class="notice danger" role="alert">
    读取批次失败：{{ error }}
    <button class="text-button" type="button" @click="load">重试</button>
  </p>

  <section class="cards" aria-label="当前筛选汇总">
    <div class="card">
      <span>批次</span>
      <strong>{{ total }}</strong>
    </div>
    <div class="card">
      <span>运行中</span>
      <strong>{{ summary.running }}</strong>
    </div>
    <div class="card">
      <span>需关注</span>
      <strong>{{ summary.attention }}</strong>
      <small>部分就绪／部分完成</small>
    </div>
    <div class="card">
      <span>可采／待接入</span>
      <strong>{{ summary.ready }} / {{ summary.needs }}</strong>
      <small>当前列表站点</small>
    </div>
  </section>

  <section class="panel">
    <div class="panel-head">
      <div>
        <h2>批次列表</h2>
        <p class="muted">共 {{ total }} 个批次；显示 {{ batches.length }} 个。</p>
      </div>
    </div>
    <p class="scroll-hint">表格可左右滚动查看完整内容。</p>
    <div class="table-wrap">
      <table class="batch-table">
        <thead>
          <tr>
            <th>批次</th>
            <th>国家／市场</th>
            <th>品类</th>
            <th>站点</th>
            <th>任务</th>
            <th>状态</th>
            <th class="col-updated">更新</th>
            <th class="col-action"></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="batch in batches" :key="batch.batch_id">
            <td>
              <RouterLink class="text-link strong" :to="`/batches/${batch.batch_id}`">
                {{ batch.name }}
              </RouterLink>
              <span class="cell-note"><code>{{ batch.batch_id }}</code></span>
            </td>
            <td>
              {{ batch.country || batch.market || "-" }}
              <span class="cell-note">{{ batch.language || "未设置语言" }}</span>
            </td>
            <td>{{ batch.category || "-" }}</td>
            <td>
              {{ batch.counts.sites }}
              <span class="cell-note">
                可采 {{ batch.counts.ready }} · 待接入
                {{ batch.counts.needs_onboarding + batch.counts.building }}
                <template v-if="batch.counts.invalid + batch.counts.duplicate">
                  · 无效／重复 {{ batch.counts.invalid + batch.counts.duplicate }}
                </template>
              </span>
            </td>
            <td>
              <template v-if="batch.counts.tasks">
                运行 {{ batch.counts.running }} · 完成 {{ batch.counts.finished }}
                <span class="cell-note">
                  排队 {{ batch.counts.queued }} · 失败／部分
                  {{ batch.counts.failed + batch.counts.partial_tasks }}
                </span>
              </template>
              <span v-else class="muted">未开始</span>
            </td>
            <td>
              <span class="badge" :class="batchStatusTone(batch.status)">
                {{ BATCH_STATUS_LABELS[batch.status] }}
              </span>
              <span v-if="batch.counts.startable" class="cell-note">
                可启动 {{ batch.counts.startable }}
              </span>
            </td>
            <td class="nowrap col-updated">{{ formatTime(batch.updated_at) }}</td>
            <td class="col-action">
              <RouterLink class="button button-sm" :to="`/batches/${batch.batch_id}`">
                查看
              </RouterLink>
            </td>
          </tr>
          <tr v-if="!batches.length && !loading">
            <td colspan="8">
              <div class="empty">
                <strong>还没有符合条件的批次</strong>
                <p class="muted">换一个筛选，或从一批站点开始新建批次。</p>
                <RouterLink class="button button-primary" to="/batches/new">
                  新建批次
                </RouterLink>
              </div>
            </td>
          </tr>
          <tr v-if="loading && !batches.length">
            <td colspan="8" class="muted">正在读取批次…</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
