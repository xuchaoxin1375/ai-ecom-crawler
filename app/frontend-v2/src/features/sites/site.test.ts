import { describe, expect, it } from "vitest";
import type {
  BatchSite,
  BuildStatus,
  SiteRuleCandidate,
  TaskSummary,
} from "../../lib/api";
import {
  buildIsActive,
  buildServiceBlockReason,
  candidateActivationBlockedReason,
  hasPendingBuildApprovals,
  siteNextStep,
  taskIsActive,
} from "./site";

function task(overrides: Partial<TaskSummary> = {}): TaskSummary {
  return {
    task_id: "t-1",
    task_type: "product",
    plan_id: "p-1",
    plan_version: "1",
    site_key: "site.fr",
    domain_key: "site.fr",
    batch_id: "b-1",
    market: "FR",
    state: "RUNNING",
    outcome: null,
    stop_reason: null,
    counts: { valid_products: 0, failed_products: 0 },
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:00Z",
    started_at: "2026-11-23T10:00:00Z",
    finished_at: null,
    ...overrides,
  };
}

function site(overrides: Partial<BatchSite> = {}): BatchSite {
  return {
    site_key: "site.fr",
    domain: "www.site.fr",
    input_value: "https://www.site.fr/",
    readiness: "ready",
    note: null,
    rule: { rule_id: "site-fr", rule_version: "1", path: "rules/site.yaml" },
    task_id: null,
    task: null,
    build_id: null,
    build: null,
    proxy: null,
    proxy_configured: false,
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:00Z",
    ...overrides,
  };
}

function build(overrides: Partial<BuildStatus> = {}): BuildStatus {
  return {
    build_id: "build-1",
    batch_id: "b-1",
    site_key: "site.fr",
    state: "RUNNING",
    outcome: null,
    mode: "build",
    workspace: null,
    session_id: null,
    model: null,
    proxy: null,
    proxy_configured: false,
    error: null,
    rule: null,
    created_at: "2026-11-23T10:00:00Z",
    updated_at: "2026-11-23T10:00:00Z",
    started_at: "2026-11-23T10:00:00Z",
    finished_at: null,
    elapsed_seconds: 12,
    events: [],
    pending_permissions: [],
    pending_dependencies: [],
    trace_available: false,
    reasoning_capture_enabled: false,
    reasoning_live: false,
    reasoning_retained: false,
    repair_limit: 1,
    repair_round: 0,
    repairs: [],
    continuations: [],
    archive: null,
    archive_stats: null,
    catalog: null,
    ...overrides,
  };
}

function candidate(overrides: Partial<SiteRuleCandidate> = {}): SiteRuleCandidate {
  return {
    rule_version: "2026.11.24-2",
    sha256: "a".repeat(64),
    build_id: "build-1",
    validation_status: "PASSED",
    change_summary: null,
    validation: {
      status: "PASSED",
      candidate_smoke: {
        executed: true,
        valid_products: 6,
        failed_products: 0,
        excluded_products: 0,
        currencies: { EUR: 6 },
        product_samples: [{}, {}, {}],
      },
      issue_checks: [],
      regression: {
        executed: true,
        required: true,
        required_checked: 3,
        checked: 3,
        regressions: [],
      },
      content_audit: { products_checked: 6, description_gaps: 0 },
      diff: { changed_fields: [], discovery_changed: false },
      evidence_sha256: "b".repeat(64),
    },
    created_at: "2026-11-24T00:00:00Z",
    ...overrides,
  };
}

describe("candidateActivationBlockedReason", () => {
  it("allows a fully verified repair candidate", () => {
    expect(candidateActivationBlockedReason(candidate())).toBeNull();
  });

  it("blocks legacy evidence without a smoke record", () => {
    const legacy = candidate({
      validation: {
        ...candidate().validation!,
        candidate_smoke: undefined,
      },
    });
    expect(candidateActivationBlockedReason(legacy)).toContain("旧验证");
  });

  it("blocks incomplete or failed validation", () => {
    const incomplete = candidate({
      validation: {
        ...candidate().validation!,
        status: "INCOMPLETE",
      },
    });
    expect(candidateActivationBlockedReason(incomplete)).toContain("不完整");
    const failed = candidate({
      validation: { ...candidate().validation!, status: "FAILED" },
    });
    expect(candidateActivationBlockedReason(failed)).toContain("未通过");
  });

  it("blocks missing or short regression coverage", () => {
    const missing = candidate({
      validation: {
        ...candidate().validation!,
        regression: {
          ...candidate().validation!.regression,
          executed: false,
          checked: 0,
        },
      },
    });
    expect(candidateActivationBlockedReason(missing)).toContain("同页回归");
    const short = candidate({
      validation: {
        ...candidate().validation!,
        regression: {
          ...candidate().validation!.regression,
          checked: 1,
        },
      },
    });
    expect(candidateActivationBlockedReason(short)).toContain("覆盖不足");
  });

  it("blocks regression entries", () => {
    const regressed = candidate({
      validation: {
        ...candidate().validation!,
        regression: {
          ...candidate().validation!.regression,
          regressions: [
            {
              field: "price_amount",
              sample: "https://site.fr/p/1",
              before: "10.00",
              after: "9.00",
            },
          ],
        },
      },
    });
    expect(candidateActivationBlockedReason(regressed)).toContain("退化");
  });
});

describe("siteNextStep", () => {
  it("asks for a build when the site has no rule package", () => {
    const step = siteNextStep(
      site({ readiness: "needs_onboarding", rule: null }),
      null,
    );
    expect(step.action).toBe("build");
    expect(step.actionLabel).toBe("启动构建");
  });

  it("offers pause and resume while a build is active", () => {
    expect(siteNextStep(site(), build()).action).toBe("pause-build");
    expect(siteNextStep(site(), build({ state: "PAUSED" })).action).toBe(
      "resume-build",
    );
    expect(siteNextStep(site(), build({ state: "VALIDATING" })).action).toBe("none");
  });

  it("shows queued builds as waiting and offers cancel", () => {
    const queued = build({ state: "QUEUED", queue_position: 2 });
    expect(buildIsActive(queued)).toBe(true);
    const step = siteNextStep(site({ readiness: "building" }), queued);
    expect(step.title).toBe("构建排队中");
    expect(step.description).toContain("第 2 位");
    expect(step.action).toBe("cancel-build");
    expect(step.actionLabel).toBe("取消排队");
  });

  it("shows an interrupted build as resumable from its detail page", () => {
    const interrupted = build({ state: "FINISHED", outcome: "interrupted" });
    const step = siteNextStep(
      site({ readiness: "needs_onboarding", build: interrupted }),
      interrupted,
    );
    expect(step.title).toBe("最近构建已中断");
    expect(step.description).toContain("构建详情");
    expect(step.action).toBe("none");
  });

  it("offers task pause, resume and cancel for active tasks", () => {
    expect(
      siteNextStep(site({ task: task({ state: "RUNNING" }), task_id: "t-1" }), null)
        .action,
    ).toBe("pause-task");
    expect(
      siteNextStep(site({ task: task({ state: "PAUSED" }), task_id: "t-1" }), null)
        .action,
    ).toBe("resume-task");
    expect(
      siteNextStep(site({ task: task({ state: "QUEUED" }), task_id: "t-1" }), null)
        .action,
    ).toBe("cancel-task");
  });

  it("offers export for completed tasks and repair for partial tasks", () => {
    expect(
      siteNextStep(
        site({
          task: task({ state: "FINISHED", outcome: "COMPLETED" }),
          task_id: "t-1",
        }),
        null,
      ).action,
    ).toBe("export");
    expect(
      siteNextStep(
        site({
          task: task({ state: "FINISHED", outcome: "PARTIAL" }),
          task_id: "t-1",
        }),
        null,
      ).action,
    ).toBe("repair");
  });

  it("shows a cancelling task without offering another collection", () => {
    const step = siteNextStep(
      site({
        task_id: "t-1",
        task: task({ state: "CANCELLING" }),
      }),
      null,
    );
    expect(step.action).toBe("none");
    expect(step.title).toBe("正在取消任务");
  });

  it("offers a direct collection start for ready sites without a task", () => {
    const step = siteNextStep(site(), null);
    expect(step.action).toBe("start");
    expect(step.actionLabel).toBe("启动采集");
  });

  it("does not offer collection for invalid or duplicate entries", () => {
    expect(siteNextStep(site({ readiness: "invalid" }), null).action).toBe("none");
    expect(siteNextStep(site({ readiness: "duplicate" }), null).action).toBe("none");
  });
});

describe("build service availability", () => {
  const config = (available: boolean) => ({
    available,
    reasoning_capture_enabled: false,
    max_repair_rounds: 0,
  });

  it("allows build actions only when the service reports available", () => {
    expect(buildServiceBlockReason(config(true))).toBeNull();
  });

  it("distinguishes unavailable from a configuration read failure", () => {
    expect(buildServiceBlockReason(config(false))).toContain("未配置构建 Agent");
    expect(buildServiceBlockReason(null, { error: true })).toContain(
      "无法读取构建服务配置",
    );
  });

  it("explains read-only and disabled build services", () => {
    expect(
      buildServiceBlockReason({ ...config(false), unavailable_reason: "read_only" }),
    ).toContain("只读预览");
    expect(
      buildServiceBlockReason({ ...config(false), unavailable_reason: "disabled" }),
    ).toContain("服务端关闭");
  });

  it("does not treat a pending first read as unavailable", () => {
    const reason = buildServiceBlockReason(null, { loading: true });
    expect(reason).toContain("正在读取");
    expect(reason).not.toContain("未配置");
  });

  it("detects pending build approvals", () => {
    expect(hasPendingBuildApprovals(null)).toBe(false);
    expect(hasPendingBuildApprovals(build())).toBe(false);
    expect(
      hasPendingBuildApprovals(
        build({ pending_permissions: [{ id: "perm-1", action: "shell" }] }),
      ),
    ).toBe(true);
    expect(hasPendingBuildApprovals(build({ pending_dependencies: ["dep-1"] }))).toBe(
      true,
    );
  });
});

describe("active state helpers", () => {
  it("recognises active build and task states", () => {
    expect(buildIsActive(build({ state: "RUNNING" }))).toBe(true);
    expect(buildIsActive(build({ state: "QUEUED" }))).toBe(true);
    expect(buildIsActive(build({ state: "FINISHED" }))).toBe(false);
    expect(taskIsActive(task({ state: "PAUSED" }))).toBe(true);
    expect(taskIsActive(task({ state: "CANCELLING" }))).toBe(true);
    expect(taskIsActive(task({ state: "FINISHED" }))).toBe(false);
  });
});
