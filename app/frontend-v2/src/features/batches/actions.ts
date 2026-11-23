import type { BatchSite, BatchSummary, TaskSummary } from "../../lib/api";

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

export function batchCanStart(batch: BatchSummary): boolean {
  return !batchIsArchived(batch) && batch.counts.startable > 0;
}

export function batchCanPause(batch: BatchSummary): boolean {
  return !batchIsArchived(batch) && batch.counts.running > 0;
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

/**
 * Only a ready site without an active link can start. A finished or cancelled
 * task is replaced (rerun); other linked states are skipped by the API.
 */
export function siteStartMode(site: BatchSite): "start" | "rerun" | null {
  if (site.readiness !== "ready") return null;
  if (!site.task) return "start";
  return TASK_TERMINAL_STATES.has(site.task.state) ? "rerun" : null;
}

export function siteTaskIsLive(task: TaskSummary | null | undefined): boolean {
  return Boolean(task && TASK_LIVE_STATES.has(task.state));
}

export function siteCanPauseTask(site: BatchSite): boolean {
  return site.task?.state === "RUNNING";
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
  return Boolean(site.task);
}

export function siteExportIsPartial(site: BatchSite): boolean {
  return siteTaskIsLive(site.task);
}
