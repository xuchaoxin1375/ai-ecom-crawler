import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { BuildMessages, BuildStatus, SiteRuleResponse } from "../../lib/api";
import { renderPage, type RenderEntry } from "../../test/renderPage";
import { BuildDetailPage } from "./BuildDetailPage";

const date = "2026-11-24T10:00:00Z";

function buildFixture(overrides: Partial<BuildStatus> = {}): BuildStatus {
  return {
    build_id: "build-1",
    batch_id: "b-fixture",
    site_key: "fixture.test",
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
    created_at: date,
    updated_at: date,
    started_at: date,
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

function messagesFixture(build: BuildStatus): BuildMessages {
  return {
    build_id: build.build_id,
    state: build.state,
    live: false,
    messages: [],
    reasoning: [],
    reasoning_retained: false,
    timeline: [],
    timeline_truncated: false,
    truncated: false,
  };
}

async function renderBuild(
  build: BuildStatus,
  config: Response | object,
  entry: RenderEntry = "/builds/build-1",
  siteRule?: SiteRuleResponse,
) {
  let currentSiteRule = siteRule;
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/builds/build-1") return Response.json({ build });
    if (path === "/api/builds/build-1/messages")
      return Response.json(messagesFixture(build));
    if (path === "/api/builds/config") {
      if (config instanceof Response) return config;
      return Response.json(config);
    }
    if (path === "/api/sites/fixture.test/rule" && currentSiteRule) {
      return Response.json(currentSiteRule);
    }
    if (/^\/api\/feedback\/[^/]+\/rerun$/.test(path) && init?.method === "POST") {
      return Response.json({
        accepted: true,
        created: true,
        task: { task_id: "web-rerun" },
        feedback: {},
        feedbacks: [{ feedback_id: "fb-1" }, { feedback_id: "fb-2" }],
      });
    }
    if (
      path === "/api/sites/fixture.test/rule/activate" &&
      init?.method === "POST" &&
      currentSiteRule
    ) {
      const body = JSON.parse(String(init.body));
      currentSiteRule = {
        ...currentSiteRule,
        active: {
          rule_version: body.rule_version,
          sha256: "a".repeat(64),
          path: "rules/fixture.yaml",
          activated_at: date,
        },
        candidates: [],
      };
      return Response.json({
        activated: true,
        site: {
          site_key: "fixture.test",
          active: currentSiteRule.active,
        },
        previous: { rule_version: "2026.11.27-1", sha256: "b".repeat(64) },
      });
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage("/builds/:buildId", entry, <BuildDetailPage />);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

it("does not render an empty approvals module", async () => {
  const build = buildFixture();
  await renderBuild(build, {
    available: true,
    reasoning_capture_enabled: false,
    max_repair_rounds: 0,
  });

  await screen.findByRole("heading", { name: "fixture.test" });
  expect(
    screen.queryByRole("region", { name: "构建等待审批" }),
  ).not.toBeInTheDocument();
});

it("puts pending approvals before the build summary", async () => {
  const build = buildFixture({
    pending_permissions: [
      { id: "perm-1", action: "shell", resources: ["npm install"] },
    ],
  });
  await renderBuild(build, {
    available: true,
    reasoning_capture_enabled: false,
    max_repair_rounds: 0,
  });

  const approvals = await screen.findByRole("region", {
    name: "构建等待审批",
  });
  const summary = screen.getByRole("region", { name: "构建概览" });
  expect(
    approvals.compareDocumentPosition(summary) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

it("blocks continuing an interrupted build when the service is unavailable", async () => {
  const build = buildFixture({ state: "FINISHED", outcome: "interrupted" });
  await renderBuild(build, {
    available: false,
    reasoning_capture_enabled: false,
    max_repair_rounds: 0,
  });

  const button = await screen.findByRole("button", { name: "发送并继续" });
  expect(button).toBeDisabled();
  expect((await screen.findAllByText(/未配置构建 Agent/)).length).toBeGreaterThan(0);
});

it("shows a retry when build configuration cannot be read", async () => {
  const build = buildFixture({ state: "FINISHED", outcome: "interrupted" });
  await renderBuild(build, new Response("unavailable", { status: 503 }));

  expect((await screen.findAllByText(/无法读取构建服务配置/)).length).toBeGreaterThan(
    0,
  );
  expect(
    (await screen.findAllByRole("button", { name: "重试读取配置" })).length,
  ).toBeGreaterThan(0);
  expect(screen.getByRole("button", { name: "发送并继续" })).toBeDisabled();
});

it("switches between build status, evidence, repairs and logs", async () => {
  const build = buildFixture({
    state: "FINISHED",
    outcome: "succeeded",
    validation: {
      status: "PASSED",
      candidate_smoke: {
        executed: true,
        valid_products: 6,
        failed_products: 0,
        excluded_products: 0,
        currencies: { GBP: 6 },
      },
      issue_checks: [],
      regression: {
        executed: true,
        required: false,
        required_checked: 0,
        checked: 0,
        regressions: [],
      },
      content_audit: { products_checked: 6, description_gaps: 0 },
      diff: { changed_fields: ["price_selector"], discovery_changed: false },
      evidence_sha256: "a".repeat(64),
    },
    repairs: [
      {
        round: 1,
        started_at: date,
        finished_at: date,
        error: "价格选择器为空",
        resolved: true,
      },
    ],
    trace_available: true,
  });
  await renderBuild(build, {
    available: true,
    reasoning_capture_enabled: false,
    max_repair_rounds: 1,
  });

  expect(await screen.findByRole("heading", { name: "构建事实" })).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: /验证证据/ }));
  expect(await screen.findByRole("heading", { name: "验证证据" })).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: /修复轮次/ }));
  expect(await screen.findByRole("heading", { name: "自动修复轮次" })).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: /日志与 Trace/ }));
  expect(await screen.findByRole("heading", { name: "构建时间线" })).toBeVisible();
  expect(
    within(screen.getByRole("tabpanel")).getByRole("button", {
      name: "下载构建过程",
    }),
  ).toBeVisible();
});

it("keeps build list filters on the back link", async () => {
  await renderBuild(
    buildFixture({ state: "FINISHED", outcome: "succeeded" }),
    {
      available: true,
      reasoning_capture_enabled: false,
      max_repair_rounds: 0,
    },
    {
      pathname: "/builds/build-1",
      state: {
        listReturn: {
          href: "/builds?state=active&mode=repair",
          label: "构建记录",
          scrollTop: 300,
          focusKey: "build-1",
        },
      },
    },
  );

  const back = await screen.findByRole("link", { name: "返回构建记录" });
  expect(back).toHaveAttribute("href", "/builds?state=active&mode=repair");
});

it("continues the session without offering rebuild", async () => {
  const build = buildFixture({
    state: "FINISHED",
    outcome: "failed",
    error: "价格选择器为空",
  });
  await renderBuild(build, {
    available: true,
    reasoning_capture_enabled: false,
    max_repair_rounds: 1,
  });

  expect(await screen.findByRole("button", { name: "继续原会话" })).toBeVisible();
  expect(screen.getByRole("button", { name: "发送并继续" })).toBeVisible();
  expect(
    screen.queryByRole("button", { name: "重新构建（新 build）" }),
  ).not.toBeInTheDocument();
});

it("activates a verified candidate from the build detail", async () => {
  const validation = {
    status: "PASSED" as const,
    candidate_smoke: {
      executed: true,
      valid_products: 6,
      failed_products: 0,
      excluded_products: 0,
      currencies: { GBP: 6 },
    },
    issue_checks: [],
    regression: {
      executed: true,
      required: false,
      required_checked: 0,
      checked: 0,
      regressions: [],
    },
    content_audit: { products_checked: 6, description_gaps: 0 },
    diff: { changed_fields: ["description_selector"], discovery_changed: false },
    evidence_sha256: "a".repeat(64),
  };
  const build = buildFixture({
    state: "FINISHED",
    outcome: "succeeded",
    mode: "repair",
    rule: {
      rule_id: "fixture-rule",
      rule_version: "2026.11.28-1",
      path: "rules/fixture.yaml",
    },
    source_rule: { rule_version: "2026.11.27-1", sha256: "b".repeat(64) },
    candidate_rule: { rule_version: "2026.11.28-1", sha256: "a".repeat(64) },
    change_summary: {
      rule_id: "fixture-rule",
      rule_version: "2026.11.28-1",
      parent_version: "2026.11.27-1",
      changed_fields: ["description_selector"],
      discovery_changed: false,
      scope_changed: false,
      market_changed: false,
      currency_changed: false,
    },
    validation,
  });
  const siteRule: SiteRuleResponse = {
    site_key: "fixture.test",
    rule_id: "fixture-rule",
    active: {
      rule_version: "2026.11.27-1",
      sha256: "b".repeat(64),
      path: "rules/fixture.yaml",
      activated_at: date,
    },
    candidates: [
      {
        rule_version: "2026.11.28-1",
        sha256: "a".repeat(64),
        build_id: "build-1",
        validation_status: "PASSED",
        validation,
        change_summary: {
          rule_id: "fixture-rule",
          rule_version: "2026.11.28-1",
          parent_version: "2026.11.27-1",
          changed_fields: ["description_selector"],
          discovery_changed: false,
          scope_changed: false,
          market_changed: false,
          currency_changed: false,
        },
        created_at: date,
      },
    ],
    stale_tasks: 0,
    open_feedback: 0,
    retired_at: null,
    retired_by: null,
  };
  const fetchMock = await renderBuild(
    build,
    {
      available: true,
      reasoning_capture_enabled: false,
      max_repair_rounds: 1,
    },
    "/builds/build-1",
    siteRule,
  );

  expect(await screen.findByRole("heading", { name: "规则候选" })).toBeVisible();
  fireEvent.click(await screen.findByRole("button", { name: "激活规则" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "激活规则" }));

  expect(await screen.findByText(/候选规则已激活/)).toBeVisible();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/sites/fixture.test/rule/activate",
    expect.objectContaining({ method: "POST" }),
  );
});

it("explains why incomplete candidate evidence blocks activation", async () => {
  const validation = {
    status: "INCOMPLETE" as const,
    candidate_smoke: {
      executed: true,
      valid_products: 2,
      failed_products: 0,
      excluded_products: 0,
      currencies: { GBP: 2 },
    },
    issue_checks: [],
    regression: {
      executed: false,
      required: true,
      required_checked: 3,
      checked: 0,
      regressions: [],
    },
    content_audit: { products_checked: 2, description_gaps: 0 },
    diff: { changed_fields: ["description_selector"], discovery_changed: false },
    evidence_sha256: "a".repeat(64),
  };
  const build = buildFixture({
    state: "FINISHED",
    outcome: "succeeded",
    mode: "repair",
    rule: {
      rule_id: "fixture-rule",
      rule_version: "2026.11.28-1",
      path: "rules/fixture.yaml",
    },
    source_rule: { rule_version: "2026.11.27-1", sha256: "b".repeat(64) },
    candidate_rule: { rule_version: "2026.11.28-1", sha256: "a".repeat(64) },
    change_summary: {
      rule_id: "fixture-rule",
      rule_version: "2026.11.28-1",
      parent_version: "2026.11.27-1",
      changed_fields: ["description_selector"],
      discovery_changed: false,
      scope_changed: false,
      market_changed: false,
      currency_changed: false,
    },
    validation,
  });
  const siteRule: SiteRuleResponse = {
    site_key: "fixture.test",
    rule_id: "fixture-rule",
    active: {
      rule_version: "2026.11.27-1",
      sha256: "b".repeat(64),
      path: "rules/fixture.yaml",
      activated_at: date,
    },
    candidates: [
      {
        rule_version: "2026.11.28-1",
        sha256: "a".repeat(64),
        build_id: "build-1",
        validation_status: "INCOMPLETE",
        validation,
        change_summary: {
          rule_id: "fixture-rule",
          rule_version: "2026.11.28-1",
          parent_version: "2026.11.27-1",
          changed_fields: ["description_selector"],
          discovery_changed: false,
          scope_changed: false,
          market_changed: false,
          currency_changed: false,
        },
        created_at: date,
      },
    ],
    stale_tasks: 0,
    open_feedback: 0,
    retired_at: null,
    retired_by: null,
  };
  await renderBuild(
    build,
    {
      available: true,
      reasoning_capture_enabled: false,
      max_repair_rounds: 1,
    },
    "/builds/build-1",
    siteRule,
  );

  expect(await screen.findByText("验证证据不完整，不能激活")).toBeVisible();
  expect(screen.queryByRole("button", { name: "激活规则" })).not.toBeInTheDocument();
  expect(
    await screen.findByText("构建完成，候选规则已安装；验证证据不完整，不能激活。"),
  ).toBeVisible();
});

it("links merged feedback and creates one shared rerun", async () => {
  const build = buildFixture({
    state: "FINISHED",
    outcome: "succeeded",
    mode: "repair",
    feedback_id: "fb-1",
    feedback_ids: ["fb-1", "fb-2"],
    feedbacks: [
      {
        feedback_id: "fb-1",
        task_id: "web-old-1",
        status: "AWAITING_RERUN",
        category: "DESCRIPTION",
        expectation: "描述应包含规格块",
        applies_to: "CURRENT_RUN",
        rerun_task_id: null,
        resolution: null,
        rule_id: "fixture-rule",
        rule_version: "2026.11.27-1",
      },
      {
        feedback_id: "fb-2",
        task_id: "web-old-2",
        status: "AWAITING_RERUN",
        category: "BASIC_FIELDS",
        expectation: "名称字段缺失",
        applies_to: "CURRENT_RUN",
        rerun_task_id: null,
        resolution: null,
        rule_id: "fixture-rule",
        rule_version: "2026.11.27-1",
      },
    ],
  });
  await renderBuild(build, {
    available: true,
    reasoning_capture_enabled: false,
    max_repair_rounds: 1,
  });

  expect(await screen.findByRole("heading", { name: "关联反馈" })).toBeVisible();
  const feedbackLinks = await screen.findAllByRole("link", { name: "查看原反馈" });
  expect(feedbackLinks).toHaveLength(2);
  expect(feedbackLinks[0]).toHaveAttribute(
    "href",
    "/tasks/web-old-1?view=quality&feedback=fb-1",
  );

  fireEvent.click(screen.getByRole("button", { name: "创建复跑（覆盖 2 条反馈）" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "创建复跑" }));

  expect(
    await screen.findByText(/复跑任务已创建：web-rerun（覆盖 2 条反馈）/),
  ).toBeVisible();
});
