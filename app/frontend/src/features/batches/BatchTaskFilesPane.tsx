import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, FileText, RefreshCw } from "lucide-react";
import { getTasks } from "../../lib/api";
import {
  formatNumber,
  formatTime,
  taskStateLabel,
  taskStateTone,
} from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

interface BatchTaskFilesPaneProps {
  batchId: string;
  batchName: string;
  onOpenDetail: () => void;
}

export function BatchTaskFilesPane({
  batchId,
  batchName,
  onOpenDetail,
}: BatchTaskFilesPaneProps) {
  const query = useQuery({
    queryKey: ["batch-task-files", batchId],
    queryFn: ({ signal }) => getTasks({ batchId, limit: 100 }, signal),
    refetchInterval: (current) =>
      (current.state.data?.items ?? []).some((task) =>
        ["QUEUED", "RUNNING", "PAUSING", "PAUSED", "CANCELLING"].includes(task.state),
      )
        ? 5000
        : false,
  });

  const tasks = query.data?.items ?? [];
  const total = query.data?.total ?? 0;
  const loading = query.isPending;

  return (
    <section
      className="overflow-hidden rounded-panel border border-line bg-surface"
      aria-label="批次任务文件"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-4 sm:px-6">
        <div className="min-w-0">
          <h2 className="truncate text-[17px] leading-6 font-semibold text-ink">
            {batchName}
          </h2>
          <p className="mt-0.5 text-xs text-ink-3" role="status">
            {loading
              ? "正在读取任务…"
              : `任务文件 ${formatNumber(total)} 个（含历史），显示 ${formatNumber(
                  tasks.length,
                )} 个${total > tasks.length ? "；更多记录请到任务列表查看" : ""}`}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
          >
            <RefreshCw
              size={14}
              className={query.isFetching ? "animate-spin" : undefined}
              aria-hidden="true"
            />
            刷新
          </Button>
          <Button size="sm" variant="primary" onClick={onOpenDetail}>
            <ExternalLink size={14} aria-hidden="true" />
            打开批次详情
          </Button>
        </div>
      </div>

      {query.isError ? (
        <div className="p-4">
          <ErrorNotice
            title="读取任务失败"
            message={
              query.error instanceof Error ? query.error.message : String(query.error)
            }
            onRetry={() => void query.refetch()}
            compact
          />
        </div>
      ) : null}

      {!query.isError && !loading && tasks.length === 0 ? (
        <div className="p-4">
          <EmptyState
            title="这个批次还没有任务"
            description="从批次详情启动可采站点后，任务会作为文件出现在这里。"
            action={
              <Button size="sm" onClick={onOpenDetail}>
                打开批次详情
              </Button>
            }
          />
        </div>
      ) : null}

      {tasks.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead className="bg-surface-muted text-xs font-medium text-ink-3">
              <tr>
                <th className="px-4 py-2.5 sm:px-6">任务文件</th>
                <th className="px-4 py-2.5">站点</th>
                <th className="px-4 py-2.5">状态</th>
                <th className="px-4 py-2.5 text-right">有效商品</th>
                <th className="px-4 py-2.5">更新时间</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {tasks.map((task) => (
                <tr key={task.task_id} className="hover:bg-surface-muted/60">
                  <td className="px-4 py-2.5 sm:px-6">
                    <Link
                      to={`/tasks/${encodeURIComponent(task.task_id)}`}
                      className="inline-flex items-center gap-1.5 font-medium text-accent hover:underline"
                    >
                      <FileText size={14} aria-hidden="true" />
                      <span className="truncate">{task.task_id}</span>
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 text-ink-2">{task.site_key ?? "—"}</td>
                  <td className="px-4 py-2.5">
                    <Badge tone={taskStateTone(task.state)} dot={false}>
                      {taskStateLabel(task.state)}
                    </Badge>
                  </td>
                  <td className="px-4 py-2.5 text-right tabular-nums text-ink-2">
                    {formatNumber(task.counts?.valid_products ?? 0)}
                  </td>
                  <td className="px-4 py-2.5 whitespace-nowrap text-xs text-ink-3">
                    {formatTime(task.updated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}
