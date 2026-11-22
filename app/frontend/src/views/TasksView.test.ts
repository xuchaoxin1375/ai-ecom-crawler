import { flushPromises, mount } from "@vue/test-utils";
import { createMemoryHistory, createRouter } from "vue-router";
import { beforeEach, describe, expect, it, vi } from "vitest";
import TasksView from "./TasksView.vue";
import { getHealth, getRules, getTasks } from "../api";

vi.mock("../api", () => ({
  getHealth: vi.fn(),
  getRules: vi.fn(),
  getTasks: vi.fn(),
  createTask: vi.fn(),
  startTask: vi.fn(),
  archiveTask: vi.fn(),
  restoreTask: vi.fn(),
}));

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: "/tasks", component: { template: "<div />" } },
    { path: "/tasks/:id", component: { template: "<div />" } },
    { path: "/batches", component: { template: "<div />" } },
    { path: "/batches/:id", component: { template: "<div />" } },
  ],
});

describe("TasksView", () => {
  beforeEach(() => {
    vi.mocked(getHealth).mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      tasks: 1,
      worker: "managed",
      max_tasks: 1,
      rules_configured: true,
    });
    vi.mocked(getRules).mockResolvedValue({
      configured: true,
      items: [
        {
          path: "familidoo.yaml",
          rule_id: "familidoo-fr-d03",
          rule_version: "2026.11.21-1",
          task_types: ["product"],
          site: "Familidoo",
          domains: ["familidoo.fr"],
          status: "candidate",
          market: "FR",
          locale: "fr-FR",
          currency: "EUR",
          valid: true,
          errors: [],
        },
      ],
    });
    vi.mocked(getTasks).mockResolvedValue({
      total: 1,
      items: [
        {
          task_id: "web-test",
          task_type: "product",
          plan_id: "familidoo-fr-d03",
          plan_version: "2026.11.21-1",
          site_key: "familidoo.fr",
          domain_key: "familidoo.fr",
          batch_id: "b-test",
          market: "FR",
          state: "FINISHED",
          outcome: "COMPLETED",
          stop_reason: "NATURAL_END",
          counts: {
            valid_products: 6,
            excluded_products: 1,
            failed_products: 0,
            discovered_urls: 7,
          },
          coverage: { status: "KNOWN", covered: 6, denominator: 6 },
          quality_exceptions: [],
          archived_at: null,
          created_at: "2026-11-23T01:00:00Z",
          updated_at: "2026-11-23T02:00:00Z",
          started_at: "2026-11-23T01:01:00Z",
          finished_at: "2026-11-23T01:02:00Z",
        },
      ],
    });
  });

  it("renders task rows and preserves technical task context", async () => {
    await router.push("/tasks");
    await router.isReady();
    const wrapper = mount(TasksView, {
      global: { plugins: [router] },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("全部任务");
    expect(wrapper.text()).toContain("web-test");
    expect(wrapper.text()).toContain("有效 6");
    expect(wrapper.text()).toContain("所属批次");
    expect(wrapper.text()).toContain("创建任务（技术）");
    expect(wrapper.text()).toContain("Familidoo");
    wrapper.unmount();
  });
});
