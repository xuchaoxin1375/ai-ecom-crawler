import { createRouter, createWebHashHistory } from "vue-router";
import BatchesView from "./views/BatchesView.vue";
import BatchDetailView from "./views/BatchDetailView.vue";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/batches" },
    { path: "/batches", name: "batches", component: BatchesView },
    {
      path: "/batches/:id",
      name: "batch",
      component: BatchDetailView,
      props: true,
    },
  ],
});
