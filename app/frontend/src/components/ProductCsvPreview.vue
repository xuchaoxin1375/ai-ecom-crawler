<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { getTaskCsv, type TaskCsvPage } from "../api";
import PreviewMediaModal from "./PreviewMediaModal.vue";

const props = defineProps<{
  taskId: string;
  live?: boolean;
}>();

const pageSize = 20;
const page = ref(0);
const payload = ref<TaskCsvPage | null>(null);
const loading = ref(false);
const error = ref("");
const activeRow = ref<Record<string, unknown> | null>(null);
const modalOpen = ref(false);
const modalTab = ref<"image" | "description">("image");
let timer: ReturnType<typeof setInterval> | null = null;

const COLUMN_LABELS: Record<string, string> = {
  name: "商品名",
  price_amount: "价格",
  price_currency: "币种",
  primary_image_url: "主图",
  description_html: "描述",
  category: "分类",
  brand: "品牌",
  attributes: "属性",
  source_url: "来源",
};

const columns = computed(() => payload.value?.columns || []);
const rows = computed(() => payload.value?.rows || []);
const total = computed(() => payload.value?.total || 0);
const pageCount = computed(() => Math.max(1, Math.ceil(total.value / pageSize)));

function columnLabel(column: string): string {
  return COLUMN_LABELS[column] || column;
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined) return "-";
  return String(value);
}

function stripHtml(value: unknown): string {
  const text = String(value || "");
  return text
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function imageUrl(value: unknown): string {
  const text = String(value || "");
  return /^https?:\/\//.test(text) ? text : "";
}

function openRow(row: Record<string, unknown>, tab: "image" | "description") {
  activeRow.value = row;
  modalTab.value = tab;
  modalOpen.value = true;
}

const modalTitle = computed(() => String(activeRow.value?.name || "商品预览"));
const modalImage = computed(() =>
  imageUrl(activeRow.value?.primary_image_url),
);
const modalDescription = computed(() =>
  String(activeRow.value?.description_html || ""),
);
const modalSource = computed(() => String(activeRow.value?.source_url || ""));
const modalMeta = computed(() =>
  [
    activeRow.value?.price_amount,
    activeRow.value?.price_currency,
    activeRow.value?.category,
    activeRow.value?.brand,
  ]
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map(String)
    .join(" · "),
);

async function load() {
  if (!props.taskId) {
    payload.value = null;
    return;
  }
  loading.value = true;
  error.value = "";
  try {
    const result = await getTaskCsv(
      props.taskId,
      pageSize,
      page.value * pageSize,
    );
    payload.value = result;
    if (page.value > 0 && result.rows.length === 0 && result.total > 0) {
      page.value = Math.max(0, Math.ceil(result.total / pageSize) - 1);
      await load();
    }
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    loading.value = false;
  }
}

function stopPolling() {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

function startPolling() {
  stopPolling();
  if (!props.live) return;
  timer = setInterval(() => {
    void load();
  }, 3000);
}

function go(delta: number) {
  const next = page.value + delta;
  if (next < 0 || next >= pageCount.value) return;
  page.value = next;
  void load();
}

watch(
  () => props.taskId,
  () => {
    page.value = 0;
    void load();
  },
);

watch(
  () => props.live,
  () => {
    startPolling();
  },
);

onMounted(async () => {
  await load();
  startPolling();
});

onUnmounted(stopPolling);
</script>

<template>
  <div class="csv-preview">
    <div class="csv-preview-head">
      <p class="muted">
        共 {{ total }} 行；数据源 {{ payload?.source || "-" }}。
        描述单元格去标签显示，下载 CSV 查看原值。
        <span v-if="live">任务运行中每 3 秒刷新。</span>
      </p>
      <div class="row-actions">
        <span v-if="loading" class="muted">读取中…</span>
        <button
          class="button button-sm"
          type="button"
          :disabled="loading"
          @click="load"
        >
          刷新
        </button>
        <button
          class="button button-sm"
          type="button"
          :disabled="page === 0 || loading"
          @click="go(-1)"
        >
          上一页
        </button>
        <span class="muted">{{ page + 1 }} / {{ pageCount }}</span>
        <button
          class="button button-sm"
          type="button"
          :disabled="page + 1 >= pageCount || loading"
          @click="go(1)"
        >
          下一页
        </button>
      </div>
    </div>
    <p v-if="error" class="notice danger">{{ error }}</p>
    <div v-if="rows.length" class="table-wrap">
      <table class="csv-table">
        <thead>
          <tr>
            <th v-for="column in columns" :key="column">
              {{ columnLabel(column) }}
            </th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, index) in rows" :key="index">
            <td v-for="column in columns" :key="column">
              <template v-if="column === 'primary_image_url' && imageUrl(row[column])">
                <button
                  class="csv-image-button"
                  type="button"
                  :title="`查看大图：${displayValue(row[column])}`"
                  @click="openRow(row, 'image')"
                >
                  <img
                    :src="imageUrl(row[column])"
                    alt=""
                    loading="lazy"
                    referrerpolicy="no-referrer"
                  />
                </button>
              </template>
              <div v-else-if="column === 'description_html'" class="csv-description">
                <span
                  class="csv-cell csv-cell-wide"
                  :title="displayValue(row[column])"
                >
                  {{ stripHtml(row[column]) || "-" }}
                </span>
                <button
                  v-if="row[column]"
                  class="csv-link-button"
                  type="button"
                  @click="openRow(row, 'description')"
                >
                  查看全文
                </button>
              </div>
              <span
                v-else
                class="csv-cell"
                :title="displayValue(row[column])"
              >
                {{ displayValue(row[column]) }}
              </span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-else class="muted">
      {{ live ? "还没有可预览的 CSV 行；任务运行中会自动刷新。" : "本次任务没有 CSV 数据。" }}
    </p>
    <PreviewMediaModal
      :open="modalOpen"
      :title="modalTitle"
      :image-url="modalImage"
      :description-html="modalDescription"
      :meta="modalMeta"
      :source-url="modalSource"
      :initial-tab="modalTab"
      @close="modalOpen = false"
    />
  </div>
</template>
