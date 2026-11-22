<script setup lang="ts">
import { RouterLink } from "vue-router";

defineProps<{ id: string }>();
</script>

<template>
  <div class="page-head">
    <div>
      <RouterLink to="/batches">← 返回批次列表</RouterLink>
      <h1>批次详情（占位）</h1>
      <p class="muted">批次 ID：<code>{{ id }}</code></p>
    </div>
  </div>

  <div class="notice">
    此页只验证 Vue Router 的 hash 路由和 <code>/batch</code> 托管。批次详情、
    站点清单、导入匹配和批次级操作将在下一步接入真实 API。
  </div>

  <section class="panel">
    <h2>下一步</h2>
    <ul>
      <li>批次／站点对象和账本迁移。</li>
      <li>导入站点、去重、无效项和规则包匹配预览。</li>
      <li>批次详情、部分启动、批次级暂停／取消和导出。</li>
    </ul>
  </section>
</template>
