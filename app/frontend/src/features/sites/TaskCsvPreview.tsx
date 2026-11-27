import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { getTaskCsv } from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

const PAGE_SIZE = 20;

const COLUMN_LABELS: Record<string, string> = {
  name: "商品名",
  price_amount: "价格",
  price_currency: "币种",
  primary_image_url: "主图",
  description_html: "描述",
  category: "分类",
  brand: "品牌",
  attributes: "属性",
  source_url: "来源",
};

function stripHtml(value: unknown): string {
  return String(value || "")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function imageUrl(value: unknown): string {
  const text = String(value || "");
  return /^https?:\/\//.test(text) ? text : "";
}

interface TaskCsvPreviewProps {
  taskId: string;
  live: boolean;
}

export function TaskCsvPreview({ taskId, live }: TaskCsvPreviewProps) {
  const [page, setPage] = useState(0);

  // The live and final snapshots come from different files. Use separate query
  // keys so a task turning terminal triggers one final read instead of keeping
  // the last live snapshot until a manual refresh.
  const query = useQuery({
    queryKey: ["task-csv", taskId, page, live ? "live" : "final"],
    queryFn: ({ signal }) => getTaskCsv(taskId, PAGE_SIZE, page * PAGE_SIZE, signal),
    enabled: Boolean(taskId),
    refetchInterval: live ? 3000 : false,
  });

  const payload = query.data;
  const total = payload?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rows = payload?.rows ?? [];
  const columns = payload?.columns ?? [];

  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div>
          <h2 className="text-[17px] leading-6 font-semibold text-ink">CSV 表格预览</h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-3">
            按导出的 9 列结构显示；任务运行中读取 products.jsonl，结束后读取
            products.csv。描述单元格去标签显示。
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Button
            size="sm"
            onClick={() => void query.refetch()}
            disabled={query.isFetching}
          >
            <RefreshCw
              className={query.isFetching ? "animate-spin" : undefined}
              size={13}
              aria-hidden="true"
            />
            刷新
          </Button>
        </div>
      </div>

      {query.isError ? (
        <div className="px-4 pt-4">
          <ErrorNotice
            title="读取 CSV 预览失败"
            message={
              query.error instanceof Error ? query.error.message : "暂时无法读取 CSV。"
            }
            compact
            onRetry={() => void query.refetch()}
          />
        </div>
      ) : null}

      {rows.length ? (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[920px] table-fixed border-collapse bg-surface text-xs">
            <caption className="sr-only">任务 CSV 预览</caption>
            <colgroup>
              {columns.map((column) => (
                <col
                  key={column}
                  style={
                    column === "description_html"
                      ? { width: "28%" }
                      : column === "name"
                        ? { width: "18%" }
                        : undefined
                  }
                />
              ))}
            </colgroup>
            <thead>
              <tr>
                {columns.map((column) => (
                  <th
                    key={column}
                    scope="col"
                    className="border-b border-line bg-surface-muted px-3 py-2 text-left font-medium text-ink-3"
                  >
                    {COLUMN_LABELS[column] || column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr
                  key={`${String(row.source_url || "")}-${index}`}
                  className="border-b border-line bg-surface last:border-0 hover:bg-surface-muted"
                >
                  {columns.map((column) => (
                    <td
                      key={column}
                      className="truncate px-3 py-2 align-top text-ink-2"
                      title={displayValue(row[column])}
                    >
                      {column === "primary_image_url" && imageUrl(row[column]) ? (
                        <a
                          href={imageUrl(row[column])}
                          target="_blank"
                          rel="noreferrer"
                          className="text-accent hover:underline"
                        >
                          查看图片
                        </a>
                      ) : column === "source_url" && imageUrl(row[column]) ? (
                        <a
                          href={imageUrl(row[column])}
                          target="_blank"
                          rel="noreferrer"
                          className="text-accent hover:underline"
                        >
                          来源页
                        </a>
                      ) : column === "description_html" ? (
                        stripHtml(row[column]) || "—"
                      ) : (
                        displayValue(row[column])
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-5 py-8 text-sm text-ink-3">
          {query.isPending
            ? live
              ? "正在读取 CSV…"
              : "任务已结束，正在更新结果…"
            : live
              ? "还没有可预览的 CSV 行；任务运行中会自动刷新。"
              : "本次任务没有 CSV 数据。"}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-5">
        <p className="text-xs text-ink-3">
          共 {formatNumber(total)} 行；数据源 {payload?.source || "—"}。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={page === 0 || query.isFetching}
            onClick={() => setPage((value) => Math.max(0, value - 1))}
          >
            <ChevronLeft size={13} aria-hidden="true" />
            上一页
          </Button>
          <span className="text-xs text-ink-3 tabular">
            {page + 1} / {pageCount}
          </span>
          <Button
            size="sm"
            disabled={page + 1 >= pageCount || query.isFetching}
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
