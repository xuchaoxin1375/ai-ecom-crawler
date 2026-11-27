import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { getTaskItems, type TaskItem } from "../../lib/api";
import { descriptionStatusTone, formatNumber } from "../../lib/format";
import { useManualRefresh } from "../../lib/liveRefresh";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { ProductPreviewDialog } from "../sites/ProductPreviewDialog";
import {
  previewDescriptionStatus,
  previewDescriptionStatusRaw,
  previewImage,
  previewMeta,
  previewName,
  previewPrice,
} from "../sites/site";

interface ProductPreviewSectionProps {
  taskId: string;
  taskActive: boolean;
  validCount: number;
}

export function ProductPreviewSection({
  taskId,
  taskActive,
  validCount,
}: ProductPreviewSectionProps) {
  const [previewItem, setPreviewItem] = useState<TaskItem | null>(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewTab, setPreviewTab] = useState<"image" | "description">("image");
  const { refreshing, runRefresh } = useManualRefresh();

  // A task that just became terminal must not keep the last live snapshot:
  // switch to a fresh query key so the final products.jsonl / products.csv
  // snapshot is read before the empty or partial state is treated as final.
  const previewQuery = useQuery({
    queryKey: ["task-preview", taskId, taskActive ? "live" : "final"],
    queryFn: ({ signal }) =>
      getTaskItems(taskId, "product", 10, 0, "DONE", "desc", signal),
    enabled: Boolean(taskId),
    refetchInterval: taskActive ? 3000 : false,
  });

  const items = (previewQuery.data?.items ?? []).filter(
    (item) => item.result.product_preview,
  );

  function openPreview(item: TaskItem, tab: "image" | "description") {
    setPreviewItem(item);
    setPreviewTab(tab);
    setPreviewOpen(true);
  }

  return (
    <>
      <section className="rounded-panel border border-line bg-surface">
        <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="text-[17px] leading-6 font-semibold text-ink">
              已采数据预览
            </h2>
            <p className="mt-0.5 text-xs leading-5 text-ink-3">
              显示最近 {items.length} 条有效商品；共 {formatNumber(validCount)} 条有效。
              {taskActive ? "任务运行中每 3 秒刷新。" : ""}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              size="sm"
              onClick={() => void runRefresh(() => previewQuery.refetch())}
              disabled={refreshing}
            >
              <RefreshCw
                className={refreshing ? "animate-spin" : undefined}
                size={13}
                aria-hidden="true"
              />
              刷新预览
            </Button>
          </div>
        </div>

        {previewQuery.isError ? (
          <div className="px-4 pt-4">
            <ErrorNotice
              title="读取预览失败"
              message={
                previewQuery.error instanceof Error
                  ? previewQuery.error.message
                  : "暂时无法读取商品预览。"
              }
              compact
              onRetry={() => void previewQuery.refetch()}
            />
          </div>
        ) : null}

        {items.length ? (
          <div className="grid grid-cols-1 gap-4 px-4 py-4 sm:grid-cols-2 sm:px-5 xl:grid-cols-3">
            {items.map((item) => {
              const image = previewImage(item);
              const descriptionStatus = previewDescriptionStatusRaw(item);
              return (
                <article
                  key={item.item_id}
                  className="flex min-w-0 flex-col overflow-hidden rounded-panel border border-line bg-surface"
                >
                  {image ? (
                    <button
                      type="button"
                      className="block aspect-[4/3] overflow-hidden bg-surface-muted"
                      title={`查看大图：${previewName(item)}`}
                      onClick={() => openPreview(item, "image")}
                    >
                      <img
                        src={image}
                        alt={previewName(item)}
                        className="h-full w-full object-cover transition-transform hover:scale-[1.02]"
                        loading="lazy"
                        referrerPolicy="no-referrer"
                      />
                    </button>
                  ) : (
                    <div className="flex aspect-[4/3] items-center justify-center bg-surface-muted text-xs text-ink-3">
                      没有主图
                    </div>
                  )}
                  <div className="flex min-w-0 flex-1 flex-col gap-1 px-3 py-3">
                    <p
                      className="line-clamp-2 text-sm leading-5 font-medium text-ink"
                      title={previewName(item)}
                    >
                      {previewName(item)}
                    </p>
                    <p className="text-sm font-semibold text-ink tabular">
                      {previewPrice(item)}
                    </p>
                    {previewMeta(item) ? (
                      <p className="truncate text-[11px] text-ink-3">
                        {previewMeta(item)}
                      </p>
                    ) : null}
                    <div className="mt-auto flex flex-wrap items-center gap-1.5 pt-1">
                      {descriptionStatus &&
                      descriptionStatus.toLowerCase() !== "complete" ? (
                        <Badge
                          tone={descriptionStatusTone(descriptionStatus)}
                          dot={false}
                        >
                          {previewDescriptionStatus(item)}
                        </Badge>
                      ) : null}
                      <a
                        className="truncate text-[11px] text-accent hover:underline"
                        href={item.url}
                        target="_blank"
                        rel="noreferrer"
                      >
                        来源页
                      </a>
                    </div>
                  </div>
                </article>
              );
            })}
          </div>
        ) : (
          <p className="px-5 py-8 text-sm text-ink-3">
            {previewQuery.isPending
              ? taskActive
                ? "正在读取有效商品…"
                : "任务已结束，正在更新结果…"
              : taskActive
                ? "还没有完成的有效商品；任务运行中，预览会自动刷新。"
                : "本次任务没有可预览的有效商品。"}
          </p>
        )}
      </section>

      <ProductPreviewDialog
        key={`${previewItem?.item_id ?? "none"}-${previewTab}-${previewOpen}`}
        open={previewOpen}
        item={previewItem}
        initialTab={previewTab}
        onOpenChange={setPreviewOpen}
      />
    </>
  );
}
