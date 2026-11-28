import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type {
  RuleCleanupResult,
  RuleVersionCleanupPreview,
  RuleVersionRecord,
  SiteRuleResponse,
} from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { RuleCandidateCard } from "./RuleCandidateCard";

afterEach(() => vi.unstubAllGlobals());

const RULE_ID = "familidoo-fr-d03";
const SITE_KEY = "familidoo.fr";

function siteRule(overrides: Partial<SiteRuleResponse> = {}): SiteRuleResponse {
  return {
    site_key: SITE_KEY,
    rule_id: RULE_ID,
    active: {
      rule_version: "2026.11.21-1",
      sha256: "sha-active",
      path: "familidoo.yaml",
      activated_at: "2026-11-21T00:00:00Z",
    },
    candidates: [],
    stale_tasks: 0,
    open_feedback: 0,
    retired_at: null,
    retired_by: null,
    ...overrides,
  };
}

function version(
  ruleVersion: string,
  status: RuleVersionRecord["status"],
): RuleVersionRecord {
  return {
    rule_id: RULE_ID,
    rule_version: ruleVersion,
    sha256: `sha-${ruleVersion}`,
    parent_version: null,
    status,
    source_build_id: null,
    source_feedback_id: null,
    path: `familidoo-${ruleVersion}.yaml`,
    created_at: "2026-11-21T00:00:00Z",
    activated_at: null,
    activated_by: null,
    reviewed_by: null,
    reviewed_at: null,
    notes: null,
  };
}

function cleanupPreview(
  overrides: Partial<RuleVersionCleanupPreview> = {},
): RuleVersionCleanupPreview {
  return {
    rule_id: RULE_ID,
    rule_version: "2026.11.24-2",
    sha256: "sha-2026.11.24-2",
    status: "rejected",
    path: "familidoo-2026.11.24-2.yaml",
    file_exists: true,
    bytes: 2048,
    references: {
      tasks: 0,
      builds: 1,
      builds_active: 0,
      feedback: 0,
      site_rules: 0,
      batch_sites: 0,
      workbench_defs: 0,
      activations: 0,
      child_versions: 0,
      samples: {},
    },
    blockers: [],
    warnings: ["1 个已结束构建保留版本号和哈希；构建详情会显示规则版本已清理"],
    can_purge: true,
    ...overrides,
  };
}

function cleanupResult(): RuleCleanupResult {
  return {
    purged: true,
    cleanup_id: "rc-1",
    rule_id: RULE_ID,
    rule_version: "2026.11.24-2",
    sha256: "sha-2026.11.24-2",
    path: "familidoo-2026.11.24-2.yaml",
    bytes: 2048,
    file_removed: true,
    residual_path: null,
    references: cleanupPreview().references,
  };
}

it("retires the active site rule after confirmation", async () => {
  const onChanged = vi.fn();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === `/api/sites/${SITE_KEY}/rule`) {
      return Response.json(siteRule());
    }
    if (path === `/api/rules/${RULE_ID}/versions/2026.11.21-1`) {
      return Response.json(version("2026.11.21-1", "active"));
    }
    if (path === `/api/sites/${SITE_KEY}/rule/retire` && init?.method === "POST") {
      return Response.json({
        retired: true,
        site: siteRule({ retired_at: "2026-11-28T00:00:00Z" }),
        previous: { rule_version: "2026.11.21-1", sha256: "sha-active" },
      });
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage(
    "*",
    "/",
    <RuleCandidateCard
      siteKey={SITE_KEY}
      ruleId={RULE_ID}
      ruleVersion="2026.11.21-1"
      onChanged={onChanged}
    />,
  );

  fireEvent.click(await screen.findByRole("button", { name: "停用站点规则" }));
  fireEvent.click(await screen.findByRole("button", { name: "停用规则" }));

  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  const post = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url) === `/api/sites/${SITE_KEY}/rule/retire` && init?.method === "POST",
  );
  const body = JSON.parse(String(post?.[1]?.body));
  expect(body.expected_active_version).toBe("2026.11.21-1");
  expect(body.expected_active_sha256).toBe("sha-active");
});

it("cleans up an unreferenced rejected version", async () => {
  const onChanged = vi.fn();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === `/api/sites/${SITE_KEY}/rule`) {
      return Response.json(siteRule());
    }
    if (path === `/api/rules/${RULE_ID}/versions/2026.11.24-2`) {
      return Response.json(version("2026.11.24-2", "rejected"));
    }
    if (path === `/api/rules/${RULE_ID}/versions/2026.11.24-2/cleanup-preview`) {
      return Response.json(cleanupPreview());
    }
    if (
      path === `/api/rules/${RULE_ID}/versions/2026.11.24-2/purge` &&
      init?.method === "POST"
    ) {
      return Response.json(cleanupResult());
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage(
    "*",
    "/",
    <RuleCandidateCard
      siteKey={SITE_KEY}
      ruleId={RULE_ID}
      ruleVersion="2026.11.24-2"
      onChanged={onChanged}
    />,
  );

  fireEvent.click(await screen.findByRole("button", { name: "清理版本…" }));
  await screen.findByText(/已结束构建保留版本号和哈希/);
  fireEvent.click(screen.getByRole("button", { name: "清理版本" }));

  await screen.findByText("规则版本已清理；构建记录保留版本号和哈希。");
  await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
  const post = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url) === `/api/rules/${RULE_ID}/versions/2026.11.24-2/purge` &&
      init?.method === "POST",
  );
  expect(JSON.parse(String(post?.[1]?.body)).request_id).toBeTruthy();
});

it("blocks cleanup when the version is still referenced", async () => {
  const fetchMock = vi.fn(async (url: string) => {
    const path = url.split("?")[0];
    if (path === `/api/sites/${SITE_KEY}/rule`) {
      return Response.json(siteRule());
    }
    if (path === `/api/rules/${RULE_ID}/versions/2026.11.24-2`) {
      return Response.json(version("2026.11.24-2", "rejected"));
    }
    if (path === `/api/rules/${RULE_ID}/versions/2026.11.24-2/cleanup-preview`) {
      return Response.json(
        cleanupPreview({
          can_purge: false,
          blockers: ["仍有 2 个任务引用"],
        }),
      );
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage(
    "*",
    "/",
    <RuleCandidateCard
      siteKey={SITE_KEY}
      ruleId={RULE_ID}
      ruleVersion="2026.11.24-2"
    />,
  );

  fireEvent.click(await screen.findByRole("button", { name: "清理版本…" }));
  expect(await screen.findByText("仍有 2 个任务引用")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "清理版本" })).toBeDisabled();
});
