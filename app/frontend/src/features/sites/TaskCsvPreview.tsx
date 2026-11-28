import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { getTaskCsv, type TaskItem } from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { useManualRefresh } from "../../lib/liveRefresh";
import { cn } from "../../lib/cn";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { DescriptionModeToggle } from "./DescriptionModeToggle";
import { ProductThumb } from "./ProductThumb";
import { ProductPreviewDialog } from "./ProductPreviewDialog";
import { PreviewSettingsButton } from "./PreviewSettingsButton";
import { useDescriptionMode } from "./descriptionMode";
import { htmlToText, previewImage } from "./site";
import { usePreviewDisplaySettings } from "../../lib/previewSettings";

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

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}

function imageUrl(value: unknown): string {
  const text = String(value || "");
  return /^https?:\/\//.test(text) ? text : "";
}

/**
 * Adapt a CSV row to the item shape consumed by ProductPreviewDialog. The
 * dialog is shared with the workbench and product cards, so a CSV row does not
 * need a second image-preview implementation.
 */
function csvRowItem(row: Record<string, unknown>, index: number): TaskItem {
  const sourceUrl = String(row.source_url || "");
  return {
    item_id: `csv-${index}-${sourceUrl || String(row.name || "")}`,
    item_type: "product",
    url: sourceUrl,
    state: "DONE",
    occurred_at: "",
    attempts: 0,
    failure_class: null,
    result: {
      product_preview: {
        name: String(row.name || ""),
        primary_image_url: imageUrl(row.primary_image_url),
        price_amount: row.price_amount ?? "",
        price_currency: String(row.price_currency || ""),
        description_html: String(row.description_html || ""),
        brand: String(row.brand || ""),
        category: String(row.category || ""),
      },
    },
  };
}

interface TaskCsvPreviewProps {
  taskId: string;
  live: boolean;
}

export function TaskCsvPreview({ taskId, live }: TaskCsvPreviewProps) {
  const [page, setPage] = useState(0);
  const [previewItem, setPreviewItem] = useState<TaskItem | null>(null);
  const [previewTab, setPreviewTab] = useState<"image" | "description">("image");
  const [previewOpen, setPreviewOpen] = useState(false);
  const [descriptionMode, setDescriptionMode] = useDescriptionMode();
  const { thumbnailsEnabled, ready: previewSettingsReady } =
    usePreviewDisplaySettings();
  const showImageLink = previewSettingsReady && !thumbnailsEnabled;
  const { refreshing, runRefresh } = useManualRefresh();

  function openPreview(item: TaskItem, tab: "image" | "description") {
    setPreviewItem(item);
    setPreviewTab(tab);
    setPreviewOpen(true);
  }

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
  const previewItems = rows.map((row, index) => csvRowItem(row, index));
  const previewGallery = previewItems.filter((item) => Boolean(previewImage(item)));

  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="flex flex-col gap-3 border-b border-line px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h2 className="text-[17px] leading-6 font-semibold text-ink">CSV 表格预览</h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-3">
            按导出的 9 列结构显示；任务运行中读取 products.jsonl，结束后读取
            products.csv。描述去标签显示，可切换单行或换行，点击描述查看全文。
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <DescriptionModeToggle
            value={descriptionMode}
            onChange={setDescriptionMode}
          />
          <PreviewSettingsButton />
          <Button
            size="sm"
            onClick={() => void runRefresh(() => query.refetch())}
            disabled={refreshing}
          >
            <RefreshCw
              className={refreshing ? "animate-spin" : undefined}
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
                        : column === "primary_image_url"
                          ? { width: "64px" }
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
                  {columns.map((column) => {
                    const descriptionText =
                      column === "description_html" ? htmlToText(row[column]) : "";
                    return (
                      <td
                        key={column}
                        className={cn(
                          "px-3 py-2 align-top text-ink-2",
                          column === "description_html" && descriptionMode === "wrap"
                            ? "whitespace-pre-wrap break-words"
                            : "truncate",
                        )}
                        title={
                          column === "primary_image_url"
                            ? String(row.name || "")
                            : column === "description_html"
                              ? descriptionText
                              : displayValue(row[column])
                        }
                      >
                        {column === "primary_image_url" && imageUrl(row[column]) ? (
                          <div className="flex flex-col items-start gap-1">
                            <button
                              type="button"
                              className="group relative block h-9 w-9 overflow-hidden rounded-control border border-line bg-surface-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50"
                              title={`查看大图：${String(row.name || "商品")}`}
                              aria-label={`查看大图：${String(row.name || "商品")}`}
                              onClick={() => {
                                const preview = previewItems[index];
                                if (preview) openPreview(preview, "image");
                              }}
                            >
                              <ProductThumb
                                src={imageUrl(row[column])}
                                alt={String(row.name || "商品主图")}
                                taskId={taskId}
                                className="h-full w-full transition-transform duration-150 group-hover:scale-105"
                              />
                            </button>
                            {showImageLink ? (
                              <button
                                type="button"
                                className="text-[10px] font-medium leading-4 text-accent hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                                aria-label={`预览图片：${String(row.name || "商品")}`}
                                onClick={() => {
                                  const preview = previewItems[index];
                                  if (preview) openPreview(preview, "image");
                                }}
                              >
                                图片
                              </button>
                            ) : null}
                          </div>
                        ) : column === "primary_image_url" ? (
                          <span className="text-ink-3">—</span>
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
                          descriptionText ? (
                            <button
                              type="button"
                              className={cn(
                                "block w-full text-left hover:text-accent",
                                descriptionMode === "wrap"
                                  ? "whitespace-pre-wrap break-words"
                                  : "truncate hover:underline",
                              )}
                              title="点击在窗口中查看完整描述"
                              aria-label={`查看完整描述：${String(row.name || "商品")}`}
                              onClick={() => {
                                const preview = previewItems[index];
                                if (preview) openPreview(preview, "description");
                              }}
                            >
                              {descriptionText}
                            </button>
                          ) : (
                            "—"
                          )
                        ) : (
                          displayValue(row[column])
                        )}
                      </td>
                    );
                  })}
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
            disabled={page === 0}
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
            disabled={page + 1 >= pageCount}
            onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}
          >
            下一页
            <ChevronRight size={13} aria-hidden="true" />
          </Button>
        </div>
      </div>

      <ProductPreviewDialog
        key={`${previewItem?.item_id ?? "none"}-${previewTab}-${previewOpen}`}
        open={previewOpen}
        item={previewItem}
        items={previewGallery}
        taskId={taskId}
        initialTab={previewTab}
        onOpenChange={setPreviewOpen}
      />
    </section>
  );
}
