import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type {
  WorkbenchDefinitionCleanupPreview,
  WorkbenchRunCleanupPreview,
} from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { WorkbenchCleanupDialog } from "./WorkbenchCleanupDialog";

afterEach(() => vi.unstubAllGlobals());

function nodePreview(
  overrides: Partial<WorkbenchDefinitionCleanupPreview> = {},
): WorkbenchDefinitionCleanupPreview {
  return {
    node_id: "n-1",
    name: "fixture.example",
    task_ids: ["web-1", "web-2"],
    runs: [
      {
        task_id: "web-1",
        state: "FINISHED",
        outcome: "COMPLETED",
        archived: false,
        feedback_count: 0,
        bytes: 512,
        files: 1,
      },
      {
        task_id: "web-2",
        state: "FINISHED",
        outcome: "COMPLETED",
        archived: false,
        feedback_count: 0,
        bytes: 512,
        files: 1,
      },
    ],
    run_count: 2,
    active_count: 0,
    feedback_ids: [],
    feedback_count: 0,
    batch_links: [],
    can_delete: true,
    can_purge_runs: true,
    blockers: [],
    bytes: 1024,
    files: 2,
    ...overrides,
  };
}

function runPreview(
  overrides: Partial<WorkbenchRunCleanupPreview> = {},
): WorkbenchRunCleanupPreview {
  return {
    task_id: "web-1",
    state: "FINISHED",
    outcome: "COMPLETED",
    archived: false,
    feedback_ids: [],
    feedback_count: 0,
    batch_links: [],
    can_purge: true,
    blockers: [],
    bytes: 1024,
    files: 2,
    ...overrides,
  };
}

it("removes a task definition and optionally purges its runs", async () => {
  const onCompleted = vi.fn();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/workbench/nodes/n-1/cleanup-preview") {
      return Response.json(nodePreview());
    }
    if (path === "/api/workbench/nodes/n-1/delete" && init?.method === "POST") {
      return Response.json({
        deleted: true,
        task_ids: ["web-1", "web-2"],
        bytes: 1024,
        files: 2,
      });
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage(
    "*",
    "/",
    <WorkbenchCleanupDialog
      open
      target={{ kind: "node", nodeId: "n-1", name: "fixture.example" }}
      onOpenChange={() => undefined}
      onCompleted={onCompleted}
    />,
  );

  const purgeRuns = await screen.findByRole("checkbox", {
    name: /同时删除 2 个运行及其结果/,
  });
  fireEvent.click(purgeRuns);
  fireEvent.click(screen.getByRole("button", { name: "删除定义和运行" }));

  await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1));
  const post = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url) === "/api/workbench/nodes/n-1/delete" && init?.method === "POST",
  );
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({
    purge_runs: true,
    purge_feedback: false,
  });
});

it("requires explicit feedback confirmation before purging a run", async () => {
  const onCompleted = vi.fn();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/tasks/web-1/cleanup-preview") {
      return Response.json(
        runPreview({
          feedback_ids: ["fb-1"],
          feedback_count: 1,
        }),
      );
    }
    if (path === "/api/tasks/web-1/purge" && init?.method === "POST") {
      return Response.json({
        purged: true,
        task_id: "web-1",
        bytes: 1024,
        files: 2,
      });
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage(
    "*",
    "/",
    <WorkbenchCleanupDialog
      open
      target={{ kind: "run", taskId: "web-1", name: "fixture.example" }}
      onOpenChange={() => undefined}
      onCompleted={onCompleted}
    />,
  );

  const confirm = await screen.findByRole("button", { name: "永久删除运行" });
  expect(confirm).toBeDisabled();
  fireEvent.click(
    await screen.findByRole("checkbox", { name: /同时删除 1 条关联反馈/ }),
  );
  expect(confirm).toBeEnabled();
  fireEvent.click(confirm);

  await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1));
  const post = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url) === "/api/tasks/web-1/purge" && init?.method === "POST",
  );
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({ purge_feedback: true });
});
