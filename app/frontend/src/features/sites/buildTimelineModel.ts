import type { BuildTimelineItem } from "../../lib/api";

export type BuildTimelineEntry =
  | { kind: "text"; id: string; index: number; item: BuildTimelineItem }
  | { kind: "reasoning"; id: string; index: number; item: BuildTimelineItem }
  | { kind: "activity"; id: string; index: number; items: BuildTimelineItem[] };

export function groupBuildTimeline(items: BuildTimelineItem[]): BuildTimelineEntry[] {
  const entries: BuildTimelineEntry[] = [];
  let group: BuildTimelineItem[] = [];
  let groupStart = 0;

  const flush = () => {
    if (!group.length) return;
    const first = group[0];
    entries.push({
      kind: "activity",
      id: `activity:${groupStart}:${first?.created_at ?? ""}:${first?.name ?? ""}`,
      index: groupStart,
      items: group,
    });
    group = [];
  };

  items.forEach((item, index) => {
    if (item.kind === "tool") {
      if (!group.length) groupStart = index;
      group.push(item);
      return;
    }
    flush();
    entries.push({
      kind: item.kind,
      id: `${item.kind}:${index}:${item.created_at ?? ""}`,
      index,
      item,
    });
  });

  flush();
  return entries;
}

export function toolSubject(item: BuildTimelineItem): string {
  const input = item.input;
  if (input && typeof input === "object" && !Array.isArray(input)) {
    const record = input as Record<string, unknown>;
    for (const key of [
      "command",
      "url",
      "filePath",
      "path",
      "pattern",
      "query",
      "glob",
    ]) {
      const value = record[key];
      if (typeof value === "string" && value.trim()) return value.trim();
    }
  }
  if (typeof input === "string" && input.trim()) return input.trim();
  return item.name && !item.name.startsWith("call_") ? item.name : "工具调用";
}

export function toolVerb(name: string | undefined): string {
  const value = (name || "").toLowerCase();
  if (!value || value.startsWith("call_")) return "工具";
  if (value.includes("shell") || value.includes("bash") || value.includes("terminal"))
    return "命令";
  if (value.includes("fetch") || value.includes("browser") || value.includes("http"))
    return "抓取";
  if (value.includes("read")) return "读取";
  if (value.includes("write") || value.includes("edit") || value.includes("patch"))
    return "写入";
  if (value.includes("grep") || value.includes("glob") || value.includes("search"))
    return "搜索";
  if (value.includes("dependency")) return "依赖";
  if (value.includes("skill")) return "技能";
  if (value.includes("task") || value.includes("agent")) return "任务";
  return name || "工具";
}

export function formatTimelineDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "";
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatElapsedSeconds(seconds: number | null | undefined): string {
  const total = Math.max(0, Math.round(Number(seconds || 0)));
  if (total < 60) return `${total} 秒`;
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  return `${minutes} 分 ${rest} 秒`;
}
