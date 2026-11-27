import type { WorkbenchNode } from "../../lib/api";

const NESTED_PATH_KEY = "ecom.workbench.create-nested-paths.v1";
export const MAX_TREE_NAME_LENGTH = 80;
export const MAX_CREATE_PATH_LENGTH = 240;

export function readNestedPathEnabled(): boolean {
  try {
    const stored = window.localStorage.getItem(NESTED_PATH_KEY);
    if (stored !== null) return stored === "true";
  } catch {
    // Preferences are optional; private mode keeps the default.
  }
  return true;
}

export function persistNestedPathEnabled(enabled: boolean): void {
  try {
    window.localStorage.setItem(NESTED_PATH_KEY, String(enabled));
  } catch {
    // Persistence is a convenience, not a requirement for creating nodes.
  }
}

export type WorkbenchPathPlan =
  | {
      ok: true;
      segments: string[];
      leafName: string;
      parentId: string | null;
      missingGroups: string[];
      reusedGroups: string[];
    }
  | { ok: false; error: string };

/**
 * Resolves a create name into a leaf plus any intermediate group names.
 * Existing group names are reused; a task with the same intermediate name
 * blocks the path because tasks cannot contain children.
 */
export function planWorkbenchPath(
  nodes: WorkbenchNode[],
  rawName: string,
  baseParentId: string | null,
  enabled: boolean,
): WorkbenchPathPlan {
  const name = rawName.trim();
  if (!name) return { ok: false, error: "名称不能为空" };

  if (!enabled || !name.includes("/")) {
    if (name.length > MAX_TREE_NAME_LENGTH) {
      return {
        ok: false,
        error: enabled
          ? `名称不能超过 ${MAX_TREE_NAME_LENGTH} 个字符；如需更长路径，请用 / 分隔多级目录`
          : `名称不能超过 ${MAX_TREE_NAME_LENGTH} 个字符；启用多级目录可创建更长的路径`,
      };
    }
    return {
      ok: true,
      segments: [name],
      leafName: name,
      parentId: baseParentId,
      missingGroups: [],
      reusedGroups: [],
    };
  }

  if (name.length > MAX_CREATE_PATH_LENGTH) {
    return {
      ok: false,
      error: `多级目录路径不能超过 ${MAX_CREATE_PATH_LENGTH} 个字符`,
    };
  }

  const segments = name
    .split("/")
    .map((segment) => segment.trim())
    .filter(Boolean);
  if (segments.length === 0) return { ok: false, error: "名称不能为空" };
  if (segments.some((segment) => segment.length > MAX_TREE_NAME_LENGTH)) {
    return {
      ok: false,
      error: `每一级目录名不能超过 ${MAX_TREE_NAME_LENGTH} 个字符`,
    };
  }

  const missingGroups: string[] = [];
  const reusedGroups: string[] = [];
  let parentId = baseParentId;
  let creating = false;

  for (const segment of segments.slice(0, -1)) {
    if (creating) {
      missingGroups.push(segment);
      continue;
    }
    const siblings = nodes.filter((node) => node.parent_id === parentId);
    const group = siblings.find(
      (node) => node.node_type === "group" && node.name === segment,
    );
    if (group) {
      reusedGroups.push(segment);
      parentId = group.node_id;
      continue;
    }
    const task = siblings.find(
      (node) => node.node_type === "task" && node.name === segment,
    );
    if (task) {
      return {
        ok: false,
        error: `「${segment}」已经是任务，不能作为目录`,
      };
    }
    missingGroups.push(segment);
    creating = true;
  }

  return {
    ok: true,
    segments,
    leafName: segments[segments.length - 1],
    parentId,
    missingGroups,
    reusedGroups,
  };
}
