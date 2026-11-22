import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import BatchesView from "./BatchesView.vue";
import { getBatches } from "../api";

vi.mock("../api", () => ({
  getBatches: vi.fn(),
}));

describe("BatchesView", () => {
  beforeEach(() => {
    vi.mocked(getBatches).mockResolvedValue({
      total: 1,
      items: [
        {
          batch_id: "b-test",
          name: "法国手工纺织 2026-11",
          country: "FR",
          market: "FR",
          language: "fr-FR",
          category: "手工／纺织",
          note: null,
          status: "PARTIAL_READY",
          archived_at: null,
          created_at: "2026-11-23T01:00:00Z",
          updated_at: "2026-11-23T02:00:00Z",
          counts: {
            sites: 3,
            ready: 2,
            needs_onboarding: 1,
            building: 0,
            invalid: 0,
            duplicate: 0,
            startable: 2,
            tasks: 0,
            draft: 0,
            queued: 0,
            running: 0,
            paused: 0,
            finished: 0,
            cancelled: 0,
            failed: 0,
            partial_tasks: 0,
          },
          valid_products: 0,
          failed_products: 0,
        },
      ],
    });
  });

  it("renders real batch rows and status", async () => {
    const wrapper = mount(BatchesView, {
      global: {
        stubs: {
          RouterLink: { template: "<a><slot /></a>" },
        },
      },
    });
    await flushPromises();
    expect(getBatches).toHaveBeenCalled();
    expect(wrapper.text()).toContain("法国手工纺织 2026-11");
    expect(wrapper.text()).toContain("部分就绪");
    expect(wrapper.text()).toContain("可采 2");
    expect(wrapper.text()).toContain("待接入 1");
  });
});
