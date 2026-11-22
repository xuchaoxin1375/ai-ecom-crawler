import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SiteDetailView from "./SiteDetailView.vue";
import {
  getBatch,
  getBuild,
  getBuildConfig,
  getBuildMessages,
  getTaskItems,
} from "../api";

vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api")>();
  return {
    ...actual,
    getBatch: vi.fn(),
    getBuild: vi.fn(),
    getBuildConfig: vi.fn(),
    getBuildMessages: vi.fn(),
    getTaskItems: vi.fn(),
  };
});

describe("SiteDetailView build timeline", () => {
  beforeEach(() => {
    vi.mocked(getBatch).mockResolvedValue({
      batch_id: "b-1",
      name: "Test batch",
      country: "FR",
      market: "FR",
      language: "fr-FR",
      category: "test",
      note: null,
      status: "READY",
      archived_at: null,
      created_at: "2026-11-23T01:00:00Z",
      updated_at: "2026-11-23T02:00:00Z",
      counts: {
        sites: 1,
        ready: 1,
        needs_onboarding: 0,
        building: 0,
        invalid: 0,
        duplicate: 0,
        startable: 1,
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
      sites: [
        {
          site_key: "example.fr",
          domain: "example.fr",
          input_value: "https://example.fr/",
          readiness: "ready",
          note: null,
          rule: { rule_id: "example", rule_version: "1", path: "example.yaml" },
          task_id: null,
          task: null,
          build_id: "build-1",
          proxy: null,
          created_at: "2026-11-23T01:00:00Z",
          updated_at: "2026-11-23T02:00:00Z",
        },
      ],
    } as any);
    vi.mocked(getBuild).mockResolvedValue({
      build: {
        build_id: "build-1",
        batch_id: "b-1",
        site_key: "example.fr",
        state: "FINISHED",
        outcome: "failed",
        workspace: null,
        session_id: null,
        model: { providerID: "test", id: "model", variant: "high" },
        proxy: null,
        proxy_configured: false,
        error: "BuildError: invalid CSS selector",
        rule: null,
        created_at: "2026-11-23T01:00:00Z",
        updated_at: "2026-11-23T02:00:00Z",
        started_at: "2026-11-23T01:00:00Z",
        finished_at: "2026-11-23T02:00:00Z",
        elapsed_seconds: 3600,
        events: [],
        pending_permissions: [],
        pending_dependencies: [],
        trace_available: true,
        reasoning_capture_enabled: false,
        reasoning_retained: true,
        repair_limit: 1,
        repair_round: 1,
        repairs: [
          {
            round: 1,
            error: "BuildError: invalid CSS selector",
            resolved: false,
            started_at: "2026-11-23T01:00:00Z",
            finished_at: "2026-11-23T02:00:00Z",
          },
        ],
      },
    } as any);
    vi.mocked(getBuildConfig).mockResolvedValue({
      available: true,
      reasoning_capture_enabled: false,
      max_repair_rounds: 1,
    });
    vi.mocked(getTaskItems).mockResolvedValue({ total: 0, items: [] } as any);
    vi.mocked(getBuildMessages).mockResolvedValue({
      build_id: "build-1",
      state: "FINISHED",
      live: false,
      messages: [{ created_at: "2026-11-23T01:00:03Z", text: "Files are written" }],
      reasoning: [{ created_at: "2026-11-23T01:00:01Z", text: "inspect" }],
      reasoning_retained: true,
      timeline: [
        {
          kind: "reasoning",
          created_at: "2026-11-23T01:00:01Z",
          text: "inspect",
        },
        {
          kind: "tool",
          created_at: "2026-11-23T01:00:02Z",
          name: "read",
          status: "completed",
          input: { path: "brief.md" },
          output: "ok",
          duration_ms: 12,
        },
        {
          kind: "text",
          role: "assistant",
          created_at: "2026-11-23T01:00:03Z",
          text: "Files are written",
        },
      ],
      timeline_truncated: false,
      truncated: false,
    });
  });

  it("renders reasoning, tool and text in detailed mode", async () => {
    const wrapper = mount(SiteDetailView, {
      props: { id: "b-1", siteKey: "example.fr" },
      global: {
        stubs: {
          RouterLink: { template: "<a><slot /></a>" },
        },
      },
    });
    await flushPromises();
    expect(getBuildMessages).toHaveBeenCalledWith("build-1");
    expect(wrapper.text()).toContain("详细模式（时间线，显示思考与工具调用）");
    expect(wrapper.text()).toContain("思考");
    expect(wrapper.text()).toContain("工具 read");
    expect(wrapper.text()).toContain("完成");
    expect(wrapper.text()).toContain("Files are written");
    expect(wrapper.text()).toContain("自动修复 1/1");
  });
});
