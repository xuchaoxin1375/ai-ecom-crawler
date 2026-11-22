<script setup lang="ts">
import { onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { getHealth, getTasks, type Health, type TaskSummary } from "../api";

const health = ref<Health | null>(null);
const tasks = ref<TaskSummary[]>([]);
const total = ref(0);
const error = ref("");

async function load() {
  error.value = "";
  try {
    const [healthPayload, taskPayload] = await Promise.all([
      getHealth(),
      getTasks(),
    ]);
    health.value = healthPayload;
    tasks.value = taskPayload.items;
    total.value = taskPayload.total;
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc);
  }
}

function workerText(payload: Health | null): string {
  if (!payload) return "未知";
  if (payload.worker === "managed") return "托管 worker";
  if (payload.worker === "external") return "外部 worker";
  return payload.worker || "未检测到 worker";
}

onMounted(load);
</script>

<template>
  <div class="page-head">
    <div>
      <h1>采集批次</h1>
      <p class="muted">
        技术最小路径：验证 Vue 构建、hash 路由、FastAPI <code>/batch</code>
        托管和真实 API 连通。批次对象、导入匹配和部分启动尚未实现。
      </p>
    </div>
    <button type="button" @click="load">刷新</button>
  </div>

  <div class="notice">
    当前页不是最终批次列表；下一步实现批次／站点对象、导入预览和批次详情。
    这里只展示真实服务状态，不使用 mock 数据。
  </div>

  <p v-if="error" class="notice">读取失败：{{ error }}</p>

  <section class="cards" aria-label="服务状态">
    <div class="card">
      <span>服务</span>
      <strong>{{ health?.status || "读取中" }}</strong>
    </div>
    <div class="card">
      <span>worker</span>
      <strong>{{ workerText(health) }}</strong>
    </div>
    <div class="card">
      <span>账本任务</span>
      <strong>{{ health?.tasks ?? "-" }}</strong>
    </div>
    <div class="card">
      <span>规则目录</span>
      <strong>{{ health?.rules_configured ? "已配置" : "未配置" }}</strong>
    </div>
  </section>

  <section class="panel">
    <h2>真实 API 连通</h2>
    <p class="muted">
      下面是 <code>/api/tasks</code> 返回的真实任务，只用于验证接口；不是批次，
      也不代表最终信息架构。
    </p>
    <p class="muted">共 {{ total }} 个任务；显示前 {{ tasks.length }} 个。</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>任务</th>
            <th>类型</th>
            <th>状态</th>
            <th>结果</th>
            <th>有效商品</th>
            <th>更新时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in tasks" :key="task.task_id">
            <td>
              <RouterLink :to="`/batches/${task.task_id}`">
                {{ task.task_id }}
              </RouterLink>
            </td>
            <td>{{ task.task_type }}</td>
            <td>{{ task.state }}</td>
            <td>{{ task.outcome || "-" }}</td>
            <td>{{ task.counts.valid_products ?? 0 }}</td>
            <td>{{ task.updated_at }}</td>
          </tr>
          <tr v-if="!tasks.length">
            <td colspan="6" class="muted">暂无任务</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>
