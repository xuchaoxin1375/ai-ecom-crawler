import { createRouter, createWebHashHistory } from "vue-router";
import BatchesView from "./views/BatchesView.vue";
import NewBatchView from "./views/NewBatchView.vue";
import BatchDetailView from "./views/BatchDetailView.vue";
import SiteDetailView from "./views/SiteDetailView.vue";
import TasksView from "./views/TasksView.vue";
import TaskDetailView from "./views/TaskDetailView.vue";

export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", redirect: "/batches" },
    { path: "/batches", name: "batches", component: BatchesView },
    {
      path: "/batches/new",
      name: "new-batch",
      component: NewBatchView,
    },
    {
      path: "/batches/:id",
      name: "batch",
      component: BatchDetailView,
      props: true,
    },
    {
      path: "/batches/:id/sites/:siteKey",
      name: "site",
      component: SiteDetailView,
      props: true,
    },
    {
      path: "/tasks",
      name: "tasks",
      component: TasksView,
    },
    {
      path: "/tasks/:id",
      name: "task",
      component: TaskDetailView,
      props: true,
    },
  ],
});
