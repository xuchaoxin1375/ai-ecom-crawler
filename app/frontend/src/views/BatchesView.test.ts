import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BatchesView from "./BatchesView.vue";
import { getHealth, getTasks } from "../api";

vi.mock("../api", () => ({
  getHealth: vi.fn(),
  getTasks: vi.fn(),
}));

describe("BatchesView", () => {
  beforeEach(() => {
    vi.mocked(getHealth).mockResolvedValue({
      status: "ok",
      version: "0.1.0",
      tasks: 1,
      worker: "managed",
      max_tasks: 1,
      rules_configured: true,
    });
    vi.mocked(getTasks).mockResolvedValue({
      total: 1,
      items: [
        {
          task_id: "web-test",
          task_type: "product",
          state: "FINISHED",
          outcome: "COMPLETED",
          counts: { valid_products: 6 },
          updated_at: "2026-11-23T01:00:00Z",
        },
      ],
    });
  });

  it("renders real service status and task rows", async () => {
    const wrapper = mount(BatchesView, {
      global: {
        stubs: {
          RouterLink: { template: "<a><slot /></a>" },
        },
      },
    });
    await flushPromises();
    expect(wrapper.text()).toContain("托管 worker");
    expect(wrapper.text()).toContain("web-test");
    expect(wrapper.text()).toContain("6");
  });
});
