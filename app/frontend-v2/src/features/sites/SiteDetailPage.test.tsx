import { fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { BatchDetail, SiteRuleResponse } from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { SiteDetailPage } from "./SiteDetailPage";

const date = "2026-11-24T10:00:00Z";
const batch: BatchDetail = {
  batch_id: "b-fixture",
  name: "批次夹具",
  country: "GB",
  market: "GB",
  language: "en-GB",
  category: null,
  note: null,
  status: "PARTIAL_READY",
  archived_at: null,
  created_at: date,
  updated_at: date,
  counts: {
    sites: 1,
    ready: 1,
    startable: 1,
    needs_onboarding: 0,
    building: 0,
    invalid: 0,
    duplicate: 0,
    tasks: 0,
    task_runs: 0,
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
      site_key: "fixture.test",
      domain: "fixture.test",
      input_value: "https://fixture.test/",
      readiness: "ready",
      note: null,
      rule: { rule_id: "fixture-rule", rule_version: "1", path: "fixture.yaml" },
      task_id: null,
      task: null,
      build_id: null,
      build: null,
      proxy: null,
      proxy_configured: false,
      created_at: date,
      updated_at: date,
    },
  ],
};

const siteRule: SiteRuleResponse = {
  site_key: "fixture.test",
  rule_id: "fixture-rule",
  active: {
    rule_version: "1",
    sha256: "a".repeat(64),
    path: "fixture.yaml",
    activated_at: date,
  },
  stale_tasks: 0,
  open_feedback: 0,
  candidates: [
    {
      rule_version: "2",
      sha256: "b".repeat(64),
      build_id: "build-1",
      validation_status: "INCOMPLETE",
      created_at: date,
      validation: {
        status: "INCOMPLETE",
        candidate_smoke: {
          executed: true,
          valid_products: 2,
          failed_products: 0,
          excluded_products: 0,
          currencies: { GBP: 2 },
        },
        regression: { required: true, executed: false, checked: 0, regressions: [] },
        issue_checks: [],
        content_audit: { products_checked: 2, description_gaps: 0 },
        diff: { changed_fields: [], discovery_changed: false },
        evidence_sha256: "c".repeat(64),
      },
    },
  ],
};

afterEach(() => vi.unstubAllGlobals());

it("keeps the active rule and blocks activation when the repair lacks regression evidence", async () => {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/batches/b-fixture") return Response.json(batch);
    if (path === "/api/sites/fixture.test/rule") return Response.json(siteRule);
    if (path === "/api/tasks") return Response.json({ items: [], total: 0 });
    if (path === "/api/builds/config") return Response.json({ enabled: false });
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  renderPage(
    "/batches/:batchId/sites/:siteKey",
    "/batches/b-fixture/sites/fixture.test",
    <SiteDetailPage />,
  );

  const activate = await screen.findByRole("button", { name: "激活" });
  const candidate = within(activate.closest("li")!);
  expect(candidate.getByText("证据不完整")).toBeVisible();
  expect(candidate.getByText(/回归未执行/)).toBeVisible();
  expect(activate).toBeDisabled();
  fireEvent.click(activate);
  expect(fetchMock.mock.calls.filter(([, init]) => init?.method === "POST")).toEqual(
    [],
  );
  const active = within(screen.getByText("当前生效").parentElement!);
  expect(active.getByText("fixture-rule@1")).toBeVisible();
});
