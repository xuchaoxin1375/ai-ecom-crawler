import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { WorkbenchClonePreview, WorkbenchNode } from "../../lib/api";
import { renderPage } from "../../test/renderPage";
import { WorkbenchCloneDialog } from "./WorkbenchCloneDialog";

afterEach(() => vi.unstubAllGlobals());

const nodes: WorkbenchNode[] = [
  {
    node_id: "g-1",
    node_type: "group",
    parent_id: null,
    name: "实验目录",
    sort_order: 0,
    created_at: "2026-11-28T00:00:00Z",
    updated_at: "2026-11-28T00:00:00Z",
  },
  {
    node_id: "n-1",
    node_type: "task",
    parent_id: "g-1",
    name: "fixture.example",
    sort_order: 0,
    created_at: "2026-11-28T00:00:00Z",
    updated_at: "2026-11-28T00:00:00Z",
  },
];

function preview(
  overrides: Partial<WorkbenchClonePreview> = {},
): WorkbenchClonePreview {
  return {
    node_id: "n-1",
    name: "fixture.example",
    parent_id: "g-1",
    definition: {
      input_url: "https://fixture.example/",
      domain: "fixture.example",
      site_key: "fixture.example",
      batch_id: null,
      country: "GB",
      language: "en-GB",
      market: "GB",
      category: "toy",
      task_type: "product",
      collection_mode: "formal",
      rule_id: "fixture-local",
      rule_version: "2026.11.21-1",
      limits: {},
      proxy: null,
      note: null,
    },
    source_rule: {
      rule_id: "fixture-local",
      rule_version: "2026.11.21-1",
      path: "fixture.yaml",
      status: "candidate",
      sha256: "abc",
    },
    source_run: {
      task_id: "web-source",
      state: "FINISHED",
      outcome: "COMPLETED",
      started_at: "2026-11-27T00:00:00Z",
      finished_at: "2026-11-27T01:00:00Z",
      bytes: 2048,
      files: 3,
    },
    default_name: "fixture.example 副本",
    can_copy_rule: true,
    can_copy_data: true,
    rule_blockers: [],
    data_blockers: [],
    ...overrides,
  };
}

it("clones a task with the rule copy and latest run data", async () => {
  const onCompleted = vi.fn();
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/workbench/tasks/n-1/clone-preview") {
      return Response.json(preview());
    }
    if (path === "/api/workbench/tasks/n-1/clone" && init?.method === "POST") {
      return Response.json({
        node: {
          node_id: "n-2",
          node_type: "task",
          parent_id: "g-1",
          name: "fixture.example 副本",
          sort_order: 1,
        },
        definition: preview().definition,
        rule: {
          rule_id: "fixture-local",
          rule_version: "2026.11.21-1-exp-abc123",
          path: "fixture-exp.yaml",
          status: "candidate",
        },
        run: {
          task_id: "web-clone",
          source_task_id: "web-source",
          state: "FINISHED",
          outcome: "COMPLETED",
          bytes: 2048,
          files: 3,
        },
      });
    }
    throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage(
    "*",
    "/",
    <WorkbenchCloneDialog
      open
      target={{ nodeId: "n-1", name: "fixture.example" }}
      nodes={nodes}
      onOpenChange={() => undefined}
      onCompleted={onCompleted}
    />,
  );

  const name = await screen.findByLabelText("克隆名称");
  await waitFor(() => expect(name).toHaveValue("fixture.example 副本"));
  expect(screen.getByLabelText("复制规则包")).toBeChecked();
  expect(screen.getByLabelText("复制最近运行数据")).not.toBeChecked();

  fireEvent.click(screen.getByLabelText("复制最近运行数据"));
  fireEvent.click(screen.getByRole("button", { name: "克隆任务" }));

  await waitFor(() => expect(onCompleted).toHaveBeenCalledTimes(1));
  expect(onCompleted.mock.calls[0][0]).toContain("已克隆任务");
  expect(onCompleted.mock.calls[0][0]).toContain("web-clone");

  const post = fetchMock.mock.calls.find(
    ([url, init]) =>
      String(url) === "/api/workbench/tasks/n-1/clone" && init?.method === "POST",
  );
  expect(JSON.parse(String(post?.[1]?.body))).toEqual({
    name: "fixture.example 副本",
    parent_id: "g-1",
    copy_rule: true,
    copy_data: true,
  });
});

it("shows rule and data blockers and disables the clone", async () => {
  const onCompleted = vi.fn();
  const fetchMock = vi.fn(async (url: string) => {
    const path = url.split("?")[0];
    if (path === "/api/workbench/tasks/n-1/clone-preview") {
      return Response.json(
        preview({
          source_run: null,
          can_copy_rule: false,
          can_copy_data: false,
          rule_blockers: ["规则文件不存在"],
          data_blockers: ["还没有已结束的运行可复制"],
        }),
      );
    }
    throw new Error(`Unexpected request: ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);

  renderPage(
    "*",
    "/",
    <WorkbenchCloneDialog
      open
      target={{ nodeId: "n-1", name: "fixture.example" }}
      nodes={nodes}
      onOpenChange={() => undefined}
      onCompleted={onCompleted}
    />,
  );

  expect(await screen.findByText("规则文件不存在")).toBeInTheDocument();
  expect(screen.getByText("还没有已结束的运行可复制")).toBeInTheDocument();
  expect(screen.getByLabelText("复制规则包")).toBeDisabled();
  expect(screen.getByLabelText("复制最近运行数据")).toBeDisabled();
  expect(screen.getByRole("button", { name: "克隆任务" })).toBeDisabled();
  expect(onCompleted).not.toHaveBeenCalled();
});
