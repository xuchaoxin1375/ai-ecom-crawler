import type { BatchSite } from "../../lib/api";

export function siteExportTaskId(site: BatchSite): string | null {
  if (site.export_task_id !== undefined) return site.export_task_id;
  return site.delivery_task?.task_id ?? null;
}

export function siteExportLabel(site: BatchSite): string {
  return site.delivery_task ? "导出已采用结果 ZIP" : "导出站点结果 ZIP";
}
