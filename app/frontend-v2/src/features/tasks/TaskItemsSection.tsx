import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { getTaskItems, type TaskItem } from "../../lib/api";
import {
  descriptionStatusLabel,
  descriptionStatusTone,
  formatNumber,
  itemStateLabel,
  itemStateTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { previewDescriptionStatusRaw, productSummary } from "../sites/site";

type TaskTab = "product" | "url";

const PAGE_SIZE = 20;

interface TaskItemsSectionProps {
  taskId: string;
  taskActive: boolean;
}

export function TaskItemsSection({ taskId, taskActive }: TaskItemsSectionProps) {
  const [taskTab, setTaskTab] = useState<TaskTab>("product");
  const [page, setPage] = useState(0);

  const itemsQuery = useQuery({
    queryKey: ["task-items", taskId, taskTab, page],
    queryFn: ({ signal }) =>
      getTaskItems(
        taskId,
        taskTab,
        PAGE_SIZE,
        page * PAGE_SIZE,
        undefined,
        "asc",
        signal,
      ),
    enabled: Boolean(taskId),
    refetchInterval: taskActive ? 3000 : false,
  });

  const total = itemsQuery.data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const columns: DataTableColumn<TaskItem>[] = [
    {
      key: "item",
      header: taskTab === "product" ? "商品" : "网址",
      width: "42%",
      cell: (item) => (
        <div className="min-w-0">
          {taskTab === "product" ? (
            productSummary(item) ? (
              <p className="truncate text-sm font-medium text-ink">
                {productSummary(item)}
              </p>
            ) : (
              <code className="block truncate font-mono text-[11px] text-ink-2">
                {item.url}
              </code>
            )
          ) : (
            <code className="block truncate font-mono text-[11px] text-ink-2">
              {item.url}
            </code>
          )}
          {taskTab === "product" && productSummary(item) ? (
            <p className="mt-0.5 truncate text-[11px] text-ink-3">{item.url}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "state",
      header: "状态",
      width: "18%",
      cell: (item) => {
        const descriptionStatus = previewDescriptionStatusRaw(item);
        return (
          <div className="flex flex-wrap items-center gap-1">
            <Badge tone={itemStateTone(item.state)} dot={false}>
              {itemStateLabel(item.state)}
            </Badge>
            {taskTab === "product" &&
            descriptionStatus &&
            descriptionStatus.toLowerCase() !== "complete" ? (
              <Badge tone={descriptionStatusTone(descriptionStatus)} dot={false}>
                {descriptionStatusLabel(descriptionStatus)}
              </Badge>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "attempts",
      header: "尝试",
      width: "9%",
      align: "right",
      cell: (item) => <span className="text-xs tabular">{item.attempts}</span>,
    },
    {
      key: "failure",
      header: "失败分类",
      width: "16%",
      cell: (item) => (
        <span className="text-xs text-ink-2">{item.failure_class || "—"}</span>
      ),
    },
    {
      key: "result",
      header: "结果",
      width: "15%",
      cell: (item) => (
        <span className="text-xs text-ink-3">
          {item.result.reason
            ? String(item.result.reason)
            : item.result.page
              ? `第 ${String(item.result.page)} 页`
              : "—"}
        </span>
      ),
    },
  ];

  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div>
          <h2 className="text-[17px] leading-6 font-semibold text-ink">任务明细</h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-3" role="status">
            {itemsQuery.isFetching
              ? "更新中…"
              : `共 ${formatNumber(total)} 条${taskActive ? "，运行中每 3 秒刷新" : ""}`}
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {(
            [
              ["product", "商品"],
              ["url", "网址"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              aria-pressed={taskTab === key}
              className={cn(
                "inline-flex h-7 items-center rounded-full border px-2.5 text-[11px] font-medium",
                taskTab === key
                  ? "border-accent/30 bg-accent-soft text-accent"
                  : "border-line bg-surface text-ink-2 hover:bg-surface-muted",
              )}
              onClick={() => {
                setTaskTab(key);
                setPage(0);
              }}
            >
              {label}
            </button>
          ))}
          <Button
            size="sm"
            onClick={() => void itemsQuery.refetch()}
            disabled={itemsQuery.isFetching}
          >
            <RefreshCw
              className={itemsQuery.isFetching ? "animate-spin" : undefined}
              size={13}
              aria-hidden="true"
            />
            刷新
          </Button>
        </div>
      </div>

      {itemsQuery.isError ? (
        <div className="px-4 pt-4">
          <ErrorNotice
            title="读取任务明细失败"
            message={
              itemsQuery.error instanceof Error
                ? itemsQuery.error.message
                : "暂时无法读取任务明细。"
            }
            compact
            onRetry={() => void itemsQuery.refetch()}
          />
        </div>
      ) : null}

      <DataTable
        caption="任务明细"
        columns={columns}
        rows={itemsQuery.data?.items ?? []}
        rowKey={(item) => item.item_id}
        density="compact"
        loading={itemsQuery.isPending}
        empty={<EmptyState title="没有明细" description="任务还没有产生这类条目。" />}
      />

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-5">
        <p className="text-xs text-ink-3">
          {total ? `第 ${page + 1} / ${pageCount} 页` : "没有可翻页的数据"}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={page === 0 || itemsQuery.isFetching}
            onClick={() => setPage((value) => Math.max(0, value - 1))}
          >
            <ChevronLeft size={13} aria-hidden="true" />
            上一页
          </Button>
          <Button
            size="sm"
            disabled={page + 1 >= pageCount || itemsQuery.isFetching}
            onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}
          >
            下一页
            <ChevronRight size={13} aria-hidden="true" />
          </Button>
        </div>
      </div>
    </section>
  );
}
