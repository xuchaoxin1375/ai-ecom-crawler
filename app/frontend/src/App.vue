<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <header class="topbar">
    <RouterLink class="brand" to="/batches">电商采集</RouterLink>
    <span class="badge">批次工作台</span>
    <span class="badge badge-warn">技术最小路径</span>
    <a class="top-link" href="/">内部任务控制台</a>
  </header>
  <main class="shell">
    <RouterView />
  </main>
</template>
