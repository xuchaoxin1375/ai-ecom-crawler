<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";

const props = defineProps<{
  open: boolean;
  title?: string;
  imageUrl?: string;
  descriptionHtml?: string;
  descriptionText?: string;
  meta?: string;
  sourceUrl?: string;
  initialTab?: "image" | "description";
}>();

const emit = defineEmits<{ close: [] }>();

const tab = ref<"image" | "description">("image");
const zoom = ref(1);
const message = ref("");
let previousOverflow = "";

function stripHtml(value: string | undefined): string {
  return String(value || "")
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6])>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

const plainDescription = computed(() =>
  props.descriptionText?.trim() || stripHtml(props.descriptionHtml),
);

const hasImage = computed(() => Boolean(props.imageUrl));
const hasDescription = computed(() => Boolean(plainDescription.value));

function reset() {
  const preferred = props.initialTab || (hasImage.value ? "image" : "description");
  tab.value = preferred === "image" && !hasImage.value ? "description" : preferred;
  zoom.value = 1;
  message.value = "";
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      reset();
      previousOverflow = document.body.style.overflow;
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = previousOverflow;
    }
  },
);

function close() {
  emit("close");
}

function onKeydown(event: KeyboardEvent) {
  if (event.key === "Escape" && props.open) close();
}

async function copy(value: string | undefined, label: string) {
  const text = value || "";
  if (!text) return;
  try {
    await navigator.clipboard.writeText(text);
    message.value = `${label}已复制`;
  } catch {
    message.value = "复制失败，请手动选择文本";
  }
}

async function downloadImage() {
  if (!props.imageUrl) return;
  try {
    const response = await fetch(props.imageUrl);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `image-${Date.now()}.${blob.type.includes("png") ? "png" : "jpg"}`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    message.value = "图片已开始下载";
  } catch {
    message.value = "浏览器阻止了跨域下载，请使用“打开原图”";
  }
}

onMounted(() => window.addEventListener("keydown", onKeydown));
onUnmounted(() => {
  window.removeEventListener("keydown", onKeydown);
  document.body.style.overflow = previousOverflow;
});
</script>

<template>
  <Teleport to="body">
    <div
      v-if="open"
      class="media-modal-backdrop"
      role="presentation"
      @click.self="close"
    >
      <section
        class="media-modal"
        role="dialog"
        aria-modal="true"
        :aria-label="title || '商品预览'"
      >
        <header class="media-modal-head">
          <div>
            <h2>{{ title || "商品预览" }}</h2>
            <p v-if="meta" class="muted">{{ meta }}</p>
          </div>
          <button class="button button-sm" type="button" @click="close">
            关闭
          </button>
        </header>

        <div
          v-if="hasImage && hasDescription"
          class="media-modal-tabs"
          role="tablist"
        >
          <button
            class="filter-chip"
            :class="{ active: tab === 'image' }"
            type="button"
            role="tab"
            :aria-selected="tab === 'image'"
            @click="tab = 'image'"
          >
            图片
          </button>
          <button
            class="filter-chip"
            :class="{ active: tab === 'description' }"
            type="button"
            role="tab"
            :aria-selected="tab === 'description'"
            @click="tab = 'description'"
          >
            完整描述
          </button>
        </div>

        <div v-if="tab === 'image' && hasImage" class="media-modal-body">
          <div class="media-image-stage">
            <img
              :src="imageUrl"
              :alt="title || ''"
              :style="{ transform: `scale(${zoom})` }"
              referrerpolicy="no-referrer"
            />
          </div>
          <div class="media-actions">
            <button
              class="button button-sm"
              type="button"
              :disabled="zoom <= 1"
              @click="zoom = Math.max(1, zoom - 0.25)"
            >
              缩小
            </button>
            <button
              class="button button-sm"
              type="button"
              @click="zoom = Math.min(4, zoom + 0.25)"
            >
              放大
            </button>
            <button class="button button-sm" type="button" @click="zoom = 1">
              复位
            </button>
            <button
              class="button button-sm"
              type="button"
              @click="copy(imageUrl, '图片 URL')"
            >
              复制图片 URL
            </button>
            <button class="button button-sm" type="button" @click="downloadImage">
              下载图片
            </button>
            <a
              class="button button-sm"
              :href="imageUrl"
              target="_blank"
              rel="noreferrer"
            >
              打开原图
            </a>
          </div>
        </div>

        <div v-else-if="hasDescription" class="media-modal-body">
          <pre class="media-description">{{ plainDescription }}</pre>
          <div class="media-actions">
            <button
              class="button button-sm"
              type="button"
              @click="copy(plainDescription, '描述文本')"
            >
              复制文本
            </button>
            <button
              v-if="descriptionHtml"
              class="button button-sm"
              type="button"
              @click="copy(descriptionHtml, '描述 HTML')"
            >
              复制 HTML
            </button>
            <a
              v-if="sourceUrl"
              class="button button-sm"
              :href="sourceUrl"
              target="_blank"
              rel="noreferrer"
            >
              打开来源页
            </a>
          </div>
        </div>

        <p v-else class="muted">没有可展示的图片或描述。</p>
        <p v-if="message" class="notice success" role="status">{{ message }}</p>

        <footer class="media-modal-foot">
          <a
            v-if="sourceUrl"
            class="muted"
            :href="sourceUrl"
            target="_blank"
            rel="noreferrer"
          >
            {{ sourceUrl }}
          </a>
        </footer>
      </section>
    </div>
  </Teleport>
</template>
