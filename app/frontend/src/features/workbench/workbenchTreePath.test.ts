import { expect, it } from "vitest";
import type { WorkbenchNode } from "../../lib/api";
import { planWorkbenchPath } from "./workbenchTreePath";

const date = "2026-11-27T10:00:00Z";

function node(
  partial: Pick<WorkbenchNode, "node_id" | "node_type" | "parent_id" | "name">,
): WorkbenchNode {
  return {
    sort_order: 0,
    created_at: date,
    updated_at: date,
    ...partial,
  };
}

const nodes: WorkbenchNode[] = [
  node({ node_id: "g-fr", node_type: "group", parent_id: null, name: "法国" }),
  node({
    node_id: "g-textile",
    node_type: "group",
    parent_id: "g-fr",
    name: "纺织",
  }),
  node({
    node_id: "g-other",
    node_type: "group",
    parent_id: "g-fr",
    name: "其他",
  }),
  node({
    node_id: "n-site",
    node_type: "task",
    parent_id: "g-fr",
    name: "站点A",
  }),
];

it("keeps a literal name when multi-level creation is disabled", () => {
  expect(planWorkbenchPath(nodes, "法国/纺织", null, false)).toEqual({
    ok: true,
    segments: ["法国/纺织"],
    leafName: "法国/纺织",
    parentId: null,
    missingGroups: [],
    reusedGroups: [],
  });
});

it("splits a path and reuses existing groups", () => {
  const plan = planWorkbenchPath(nodes, " 法国 / 纺织 / 2026-11 ", null, true);
  expect(plan.ok).toBe(true);
  if (!plan.ok) return;
  expect(plan.segments).toEqual(["法国", "纺织", "2026-11"]);
  expect(plan.parentId).toBe("g-textile");
  expect(plan.missingGroups).toEqual([]);
  expect(plan.reusedGroups).toEqual(["法国", "纺织"]);
  expect(plan.leafName).toBe("2026-11");
});

it("creates missing intermediate groups under the resolved parent", () => {
  const plan = planWorkbenchPath(nodes, "法国/新分类/子分类/任务A", null, true);
  expect(plan.ok).toBe(true);
  if (!plan.ok) return;
  expect(plan.parentId).toBe("g-fr");
  expect(plan.missingGroups).toEqual(["新分类", "子分类"]);
  expect(plan.leafName).toBe("任务A");
});

it("uses the selected parent as the base", () => {
  const plan = planWorkbenchPath(nodes, "纺织/2026-11", "g-fr", true);
  expect(plan.ok).toBe(true);
  if (!plan.ok) return;
  expect(plan.parentId).toBe("g-textile");
  expect(plan.missingGroups).toEqual([]);
  expect(plan.leafName).toBe("2026-11");
});

it("rejects a path segment that is already a task", () => {
  const plan = planWorkbenchPath(nodes, "法国/站点A/子目录", null, true);
  expect(plan).toEqual({
    ok: false,
    error: "「站点A」已经是任务，不能作为目录",
  });
});

it("ignores empty path segments and trims whitespace", () => {
  const plan = planWorkbenchPath(nodes, " / 法国 // 纺织 / ", null, true);
  expect(plan.ok).toBe(true);
  if (!plan.ok) return;
  expect(plan.segments).toEqual(["法国", "纺织"]);
  expect(plan.leafName).toBe("纺织");
});

it("rejects oversized names and segments", () => {
  const disabled = planWorkbenchPath(nodes, "x".repeat(81), null, false);
  expect(disabled.ok).toBe(false);

  const segment = planWorkbenchPath(nodes, `${"x".repeat(81)}/子目录`, null, true);
  expect(segment).toEqual({
    ok: false,
    error: "每一级目录名不能超过 80 个字符",
  });
});
