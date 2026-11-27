import type { BatchDetail } from "../../lib/api";
import { formatNumber } from "../../lib/format";

export function BatchStatusBand({ batch }: { batch: BatchDetail }) {
  const { counts } = batch;
  const intake = [
    [counts.startable, "可启动"],
    [counts.needs_onboarding, "待接入"],
    [counts.building, "构建中"],
    [counts.invalid + counts.duplicate, "无效／重复"],
  ] as const;
  const tasks = [
    [counts.draft, "未排队"],
    [counts.queued, "排队中"],
    [counts.running, "处理中"],
    [counts.paused, "已暂停"],
    [Math.max(0, counts.finished - counts.failed - counts.partial_tasks), "已完成"],
    [counts.failed + counts.partial_tasks, "失败／部分完成"],
    [counts.cancelled, "已取消"],
  ] as const;
  const describe = (items: readonly (readonly [number, string])[]) =>
    items
      .filter(([count]) => count > 0)
      .map(([count, label]) => `${label} ${formatNumber(count)}`)
      .join(" · ");
  return (
    <dl
      aria-label="批次进度"
      className="grid gap-x-6 gap-y-2 rounded-panel border border-line bg-surface px-4 py-3 text-sm leading-5 sm:grid-cols-3"
    >
      <div className="flex flex-wrap gap-x-2">
        <dt className="font-semibold text-ink">站点 {formatNumber(counts.sites)}</dt>
        {describe(intake) && <dd className="text-ink-2">{describe(intake)}</dd>}
      </div>
      <div className="flex flex-wrap gap-x-2">
        <dt className="font-semibold text-ink">任务</dt>
        <dd className="text-ink-2">{describe(tasks) || "尚未创建"}</dd>
      </div>
      <div className="flex flex-wrap gap-x-2">
        <dt className="font-semibold text-ink">当前结果</dt>
        <dd className="text-ink-2">
          {counts.tasks > 0
            ? `有效商品 ${formatNumber(batch.valid_products)} · 失败 ${formatNumber(batch.failed_products)}`
            : "暂无"}
        </dd>
      </div>
    </dl>
  );
}
