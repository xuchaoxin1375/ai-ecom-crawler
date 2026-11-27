import type { BatchSite, BatchSummary } from "../../lib/api";
import { taskPrimaryControl, type TaskPrimaryControl } from "../../lib/taskControl";

/** States that still have work to settle or can be controlled. */
export const TASK_LIVE_STATES = new Set([
  "DRAFT",
  "QUEUED",
  "RUNNING",
  "PAUSING",
  "PAUSED",
  "CANCELLING",
]);

/** A terminal task can be replaced by a rerun without losing its ledger row. */
export const TASK_TERMINAL_STATES = new Set(["FINISHED", "CANCELLED"]);

export function batchIsArchived(batch: BatchSummary): boolean {
  return batch.status === "ARCHIVED" || Boolean(batch.archived_at);
}

export function batchNeedsLiveRefresh(batch: BatchSummary): boolean {
  const counts = batch.counts;
  return counts.queued + counts.running + counts.building > 0;
}

export function batchCanStart(batch: BatchSummary): boolean {
  return !batchIsArchived(batch) && batch.counts.startable > 0;
}

export function batchCanPause(batch: BatchSummary): boolean {
  return (
    !batchIsArchived(batch) && (batch.counts.running > 0 || batch.counts.queued > 0)
  );
}

export function batchCanResume(batch: BatchSummary): boolean {
  return !batchIsArchived(batch) && batch.counts.paused > 0;
}

export function batchCanExport(batch: BatchSummary): boolean {
  return batch.counts.tasks > 0;
}

export function batchExportIsPartial(batch: BatchSummary): boolean {
  const counts = batch.counts;
  return counts.draft + counts.queued + counts.running + counts.paused > 0;
}

export function batchExportLabel(batch: BatchSummary): string {
  return batchExportIsPartial(batch) ? "导出部分结果" : "导出批次 ZIP";
}

export function taskExportLabel(partial: boolean): string {
  return partial ? "导出当前任务（部分结果）" : "导出当前任务 ZIP";
}

/**
 * A ready target can start its first run under the batch plan. Other terminal
 * runs are replaced only when the user chooses to rerun.
 */
export function siteStartMode(site: BatchSite): "start" | "rerun" | null {
  if (site.readiness !== "ready") return null;
  if (!site.task_id || site.formal_pending) return "start";
  return site.task && TASK_TERMINAL_STATES.has(site.task.state) ? "rerun" : null;
}

export function siteCanPauseTask(site: BatchSite): boolean {
  return site.task?.state === "RUNNING" || site.task?.state === "QUEUED";
}

/** Primary control shown inline in a batch site row; start still opens a dialog. */
export function sitePrimaryControl(site: BatchSite): TaskPrimaryControl | null {
  if (siteStartMode(site) === "start") return "start";
  return taskPrimaryControl(site.task?.state, { allowDraftStart: false });
}

export function siteCanResumeTask(site: BatchSite): boolean {
  return site.task?.state === "PAUSED";
}

export function siteCanCancelTask(site: BatchSite): boolean {
  return Boolean(
    site.task &&
    TASK_LIVE_STATES.has(site.task.state) &&
    site.task.state !== "CANCELLING",
  );
}

export function siteCanExport(site: BatchSite): boolean {
  return Boolean(siteExportTaskId(site));
}

export function siteExportTaskId(site: BatchSite): string | null {
  if (site.export_task_id !== undefined) return site.export_task_id;
  return site.delivery_task?.task_id ?? null;
}

export function siteExportLabel(site: BatchSite): string {
  return site.delivery_task ? "导出已采用结果 ZIP" : "导出站点结果 ZIP";
}
