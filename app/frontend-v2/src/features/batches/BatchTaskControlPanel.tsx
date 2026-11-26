import type { MouseEvent } from "react";
import { Link } from "react-router-dom";
import { ArrowUpRight, Ban, Pause, Play, RefreshCw } from "lucide-react";
import type { BatchSite } from "../../lib/api";
import { formatNumber, taskStateLabel, taskStateTone } from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { siteCanCancelTask, siteCanPauseTask, siteCanResumeTask } from "./actions";

const LIVE_STATE_ORDER: Record<string, number> = {
  RUNNING: 0,
  PAUSING: 1,
  PAUSED: 2,
  QUEUED: 3,
  CANCELLING: 4,
};

function liveTaskSites(sites: BatchSite[]): BatchSite[] {
  return sites
    .filter((site) => site.task && site.task.state in LIVE_STATE_ORDER)
    .sort((left, right) => {
      const leftOrder = LIVE_STATE_ORDER[left.task?.state ?? ""] ?? 99;
      const rightOrder = LIVE_STATE_ORDER[right.task?.state ?? ""] ?? 99;
      if (leftOrder !== rightOrder) return leftOrder - rightOrder;
      return (right.task?.updated_at ?? "").localeCompare(left.task?.updated_at ?? "");
    });
}

function countState(sites: BatchSite[], states: string[]): number {
  return sites.filter((site) => site.task && states.includes(site.task.state)).length;
}

interface BatchTaskControlPanelProps {
  sites: BatchSite[];
  rowBusy: string;
  batchBusy: boolean;
  onPauseSite: (site: BatchSite) => void;
  onResumeSite: (site: BatchSite) => void;
  onCancelSite: (site: BatchSite) => void;
  onPauseAll: () => void;
  onResumeAll: () => void;
  onOpenTask: (taskId: string, event: MouseEvent<HTMLAnchorElement>) => void;
}

export function BatchTaskControlPanel({
  sites,
  rowBusy,
  batchBusy,
  onPauseSite,
  onResumeSite,
  onCancelSite,
  onPauseAll,
  onResumeAll,
  onOpenTask,
}: BatchTaskControlPanelProps) {
  const liveSites = liveTaskSites(sites);
  if (liveSites.length === 0) return null;

  const running = countState(sites, ["RUNNING", "PAUSING"]);
  const paused = countState(sites, ["PAUSED"]);
  const queued = countState(sites, ["QUEUED"]);
  const cancelling = countState(sites, ["CANCELLING"]);
  const canPauseAny = liveSites.some(siteCanPauseTask);
  const canResumeAny = liveSites.some(siteCanResumeTask);

  return (
    <section
      className="rounded-panel border border-line bg-surface"
      aria-labelledby="batch-task-control-title"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div className="min-w-0">
          <h2 id="batch-task-control-title" className="text-sm font-semibold text-ink">
            任务控制
          </h2>
          <p className="mt-0.5 text-xs text-ink-3">
            运行中 {formatNumber(running)} · 排队中 {formatNumber(queued)} · 已暂停{" "}
            {formatNumber(paused)}
            {cancelling ? ` · 取消中 ${formatNumber(cancelling)}` : ""}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={onPauseAll}
            disabled={batchBusy || !canPauseAny}
            title="暂停本批运行中和排队中的任务"
          >
            <Pause size={13} aria-hidden="true" />
            暂停全部
          </Button>
          <Button
            size="sm"
            onClick={onResumeAll}
            disabled={batchBusy || !canResumeAny}
            title="继续本批已暂停的任务"
          >
            <Play size={13} aria-hidden="true" />
            继续全部
          </Button>
        </div>
      </div>

      <ul
        className="max-h-80 divide-y divide-line overflow-y-auto"
        aria-label="本批活动任务"
      >
        {liveSites.map((site) => {
          const task = site.task;
          if (!task) return null;
          const busy = rowBusy === site.site_key;
          const counts = task.counts;
          const pending = counts.pending ?? counts.in_flight;
          const hasCounts =
            counts.valid_products !== undefined ||
            counts.failed_products !== undefined ||
            pending !== undefined;
          return (
            <li
              key={site.site_key}
              className="flex flex-wrap items-center justify-between gap-3 px-4 py-3"
              aria-busy={busy || undefined}
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={taskStateTone(task.state)} dot={false}>
                    {taskStateLabel(task.state)}
                  </Badge>
                  <Link
                    className="min-w-0 truncate text-sm font-semibold text-ink hover:text-accent hover:underline"
                    to={`/tasks/${encodeURIComponent(task.task_id)}`}
                    onClick={(event) => onOpenTask(task.task_id, event)}
                  >
                    {site.domain}
                  </Link>
                </div>
                {hasCounts ? (
                  <p className="mt-1 text-[11px] text-ink-3">
                    有效 {formatNumber(counts.valid_products ?? 0)} · 失败{" "}
                    {formatNumber(counts.failed_products ?? 0)}
                    {pending !== undefined ? ` · 待处理 ${formatNumber(pending)}` : ""}
                  </p>
                ) : null}
              </div>

              <div className="flex flex-wrap items-center gap-1.5">
                {busy ? (
                  <span
                    className="inline-flex items-center gap-1 text-[11px] text-ink-3"
                    aria-live="polite"
                  >
                    <RefreshCw size={12} className="animate-spin" aria-hidden="true" />
                    处理中…
                  </span>
                ) : null}
                {siteCanPauseTask(site) ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => onPauseSite(site)}
                  >
                    <Pause size={13} aria-hidden="true" />
                    暂停
                  </Button>
                ) : null}
                {siteCanResumeTask(site) ? (
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={busy}
                    onClick={() => onResumeSite(site)}
                  >
                    <Play size={13} aria-hidden="true" />
                    继续
                  </Button>
                ) : null}
                {siteCanCancelTask(site) ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-danger hover:bg-danger-soft hover:text-danger"
                    disabled={busy}
                    onClick={() => onCancelSite(site)}
                  >
                    <Ban size={13} aria-hidden="true" />
                    取消
                  </Button>
                ) : null}
                <Link
                  className="inline-flex items-center gap-1 rounded-control px-2 py-1 text-xs font-medium text-ink-2 hover:bg-surface-muted hover:text-ink"
                  to={`/tasks/${encodeURIComponent(task.task_id)}`}
                  onClick={(event) => onOpenTask(task.task_id, event)}
                >
                  详情
                  <ArrowUpRight size={12} aria-hidden="true" />
                </Link>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
