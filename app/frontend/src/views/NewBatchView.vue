<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { RouterLink, useRouter } from "vue-router";
import {
  createBatch,
  previewBatch,
  startBatch,
  type BatchPreviewResponse,
} from "../api";
import { READINESS_LABELS, readinessTone } from "../ui";

type Preview = BatchPreviewResponse["preview"];

const router = useRouter();
const form = reactive({
  name: "",
  country: "FR",
  market: "FR",
  language: "fr-FR",
  category: "",
  note: "",
  sitesText: "",
});
const preview = ref<Preview | null>(null);
const previewDirty = ref(false);
const busy = ref<"" | "preview" | "save" | "start">("");
const error = ref("");
const nameError = ref("");
const fileName = ref("");

const invalidItems = computed(
  () =>
    preview.value?.import.items.filter(
      (item) => item.readiness === "invalid" || item.readiness === "duplicate",
    ) || [],
);
const needsItems = computed(
  () =>
    preview.value?.import.items.filter(
      (item) => item.readiness === "needs_onboarding",
    ) || [],
);
const readyItems = computed(
  () =>
    preview.value?.import.items.filter((item) => item.readiness === "ready") ||
    [],
);

watch(
  form,
  () => {
    if (preview.value) previewDirty.value = true;
  },
  { deep: true },
);

function body() {
  const optional = (value: string) => value.trim() || null;
  return {
    name: form.name.trim(),
    country: optional(form.country),
    market: optional(form.market),
    language: optional(form.language),
    category: optional(form.category),
    note: optional(form.note),
    sites_text: form.sitesText,
  };
}

async function runPreview() {
  nameError.value = "";
  if (!form.name.trim()) {
    nameError.value = "先给批次起一个名称，再解析站点。";
    document.getElementById("batch-name")?.focus();
    return;
  }
  busy.value = "preview";
  error.value = "";
  try {
    const payload = await previewBatch(body());
    preview.value = payload.preview;
    previewDirty.value = false;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    busy.value = "";
  }
}

async function save(start: boolean) {
  if (!preview.value) return;
  busy.value = start ? "start" : "save";
  error.value = "";
  try {
    const created = await createBatch(body());
    const batchId = created.batch.batch_id;
    if (start) {
      try {
        const result = await startBatch(batchId);
        await router.push({
          path: `/batches/${batchId}`,
          query: {
            created: "1",
            started: String(result.accepted.length),
            skipped: String(result.skipped.length),
          },
        });
        return;
      } catch (exc) {
        await router.push({
          path: `/batches/${batchId}`,
          query: { created: "1", start_error: "1" },
        });
        error.value = exc instanceof Error ? exc.message : String(exc);
        return;
      }
    }
    await router.push({
      path: `/batches/${batchId}`,
      query: { created: "1" },
    });
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  } finally {
    busy.value = "";
  }
}

function readCsv(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file) return;
  void file.text().then((text) => {
    const lines = text.split(/\r?\n/);
    if (
      lines.length &&
      /^\s*(url|site|domain|website|网址|站点|域名)\s*(,|$)/i.test(lines[0])
    ) {
      lines.shift();
    }
    const cleaned = lines.join("\n").trim();
    form.sitesText = form.sitesText.trim()
      ? `${form.sitesText.trim()}\n${cleaned}`
      : cleaned;
    fileName.value = file.name;
    input.value = "";
  });
}
</script>

<template>
  <div class="page-head">
    <div>
      <RouterLink class="back-link" to="/batches">← 返回批次列表</RouterLink>
      <h1>新建采集批次</h1>
      <p class="muted">
        每行一个网址或域名；系统会去重、校验并匹配已有规则包。未匹配到规则包的站点进入“待接入”，不会阻塞其他站点。
      </p>
    </div>
  </div>

  <p v-if="error" class="notice danger" role="alert">{{ error }}</p>

  <div class="wizard-grid">
    <section class="panel">
      <div class="panel-head">
        <div>
          <h2>批次信息</h2>
          <p class="muted">默认值可修改；名称和站点列表是保存草稿的最低要求。</p>
        </div>
      </div>
      <div class="form-grid">
        <label class="field field-wide">
          <span>批次名称 <em>*</em></span>
          <input
            id="batch-name"
            v-model="form.name"
            maxlength="200"
            placeholder="如 法国手工纺织 2026-11"
            :aria-invalid="Boolean(nameError)"
            aria-describedby="batch-name-error"
          />
          <small v-if="nameError" id="batch-name-error" class="field-error">
            {{ nameError }}
          </small>
        </label>
        <label class="field">
          <span>国家</span>
          <input v-model="form.country" placeholder="如 FR" />
        </label>
        <label class="field">
          <span>市场</span>
          <input v-model="form.market" placeholder="如 FR" />
        </label>
        <label class="field">
          <span>语言</span>
          <input v-model="form.language" placeholder="如 fr-FR" />
        </label>
        <label class="field">
          <span>品类</span>
          <input v-model="form.category" placeholder="如 手工／纺织" />
        </label>
        <label class="field field-wide">
          <span>备注</span>
          <input v-model="form.note" maxlength="2000" placeholder="可选，用于交接说明" />
        </label>
        <label class="field field-wide">
          <span>站点列表</span>
          <textarea
            v-model="form.sitesText"
            rows="10"
            spellcheck="false"
            placeholder="https://exemple-boutique.fr/&#10;https://autre-atelier.fr/"
          ></textarea>
          <small class="hint">
            支持粘贴文本或上传 CSV；CSV 取第一列，表头会自动跳过。
          </small>
        </label>
        <div class="field field-wide file-row">
          <label class="button button-sm file-button">
            上传 CSV
            <input type="file" accept=".csv,.txt,text/csv,text/plain" @change="readCsv" />
          </label>
          <span v-if="fileName" class="muted">已追加 {{ fileName }}</span>
        </div>
      </div>
      <div class="form-actions">
        <button
          class="button button-primary"
          type="button"
          :disabled="Boolean(busy)"
          @click="runPreview"
        >
          {{ busy === "preview" ? "解析中…" : "解析并预览" }}
        </button>
      </div>
    </section>

    <section class="panel preview-panel">
      <div class="panel-head">
        <div>
          <h2>匹配预览</h2>
          <p class="muted">保存草稿和启动分离；预览不会创建批次。</p>
        </div>
      </div>

      <div v-if="!preview" class="empty compact">
        <strong>还没有解析结果</strong>
        <p class="muted">填写批次信息和站点后，点击“解析并预览”。</p>
      </div>

      <template v-else>
        <p v-if="previewDirty" class="notice warning" role="status">
          表单已修改，当前预览不再对应当前输入；请重新解析。
        </p>

        <div class="stat-line">
          <div class="stat-box">
            <span>可采</span>
            <strong>{{ preview.import.summary.ready }}</strong>
          </div>
          <div class="stat-box">
            <span>待接入</span>
            <strong>{{ preview.import.summary.needs_onboarding }}</strong>
          </div>
          <div class="stat-box">
            <span>重复</span>
            <strong>{{ preview.import.summary.duplicate }}</strong>
          </div>
          <div class="stat-box">
            <span>无效</span>
            <strong>{{ preview.import.summary.invalid }}</strong>
          </div>
        </div>

        <div v-if="invalidItems.length" class="notice danger" role="alert">
          <strong>{{ invalidItems.length }} 条无效／重复需要处理</strong>
          <ul class="issue-list">
            <li v-for="(item, index) in invalidItems" :key="`${item.input_value}-${index}`">
              <code>{{ item.input_value }}</code>：{{ item.reason }}
            </li>
          </ul>
          <p>这些条目不会进入采集；修正后重新解析即可。</p>
        </div>

        <div
          v-if="needsItems.length"
          class="notice warning"
          role="status"
        >
          <strong>{{ needsItems.length }} 个站点需要接入</strong>
          <p>
            它们没有匹配到受管规则包，会保留在批次中并显示“待接入”；可先启动可采站点，不阻塞整批。
          </p>
        </div>

        <div class="table-wrap">
          <table class="preview-table">
            <thead>
              <tr>
                <th>站点</th>
                <th>匹配</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(item, index) in preview.import.items" :key="`${item.input_value}-${index}`">
                <td>
                  <code>{{ item.domain }}</code>
                  <span
                    v-if="item.input_value !== item.domain"
                    class="cell-note"
                  >原始输入：{{ item.input_value }}</span>
                </td>
                <td>
                  <span class="badge" :class="readinessTone(item.readiness)">
                    {{ READINESS_LABELS[item.readiness] }}
                  </span>
                </td>
                <td>{{ item.reason }}</td>
              </tr>
              <tr v-if="!preview.import.items.length">
                <td colspan="3" class="muted">没有站点；可以保存一个空草稿，稍后再导入。</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="form-actions">
          <button
            class="button"
            type="button"
            :disabled="Boolean(busy) || previewDirty"
            @click="save(false)"
          >
            {{ busy === "save" ? "保存中…" : "保存草稿" }}
          </button>
          <button
            v-if="readyItems.length"
            class="button button-primary"
            type="button"
            :disabled="Boolean(busy) || previewDirty"
            @click="save(true)"
          >
            {{ busy === "start" ? "保存并启动…" : `保存并启动 ${readyItems.length} 个可采站点` }}
          </button>
        </div>
      </template>
    </section>
  </div>
</template>
