import type { BatchDetail } from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { ReadinessBar } from "../../components/ui/ReadinessBar";
import { cn } from "../../lib/cn";
import type { SiteFilter } from "./detail";

interface BatchStatusBandProps {
  batch: BatchDetail;
  activeFilter: SiteFilter;
  onFilter: (filter: SiteFilter) => void;
}

function FilterChip({
  label,
  count,
  filter,
  activeFilter,
  onFilter,
}: {
  label: string;
  count: number;
  filter: SiteFilter;
  activeFilter: SiteFilter;
  onFilter: (filter: SiteFilter) => void;
}) {
  const active = activeFilter === filter;
  return (
    <button
      type="button"
      aria-pressed={active}
      disabled={count === 0}
      title={count === 0 ? "当前没有符合条件的站点" : undefined}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium transition-colors",
        active
          ? "border-accent/30 bg-accent-soft text-accent"
          : "border-line bg-surface text-ink-2 hover:bg-surface-muted hover:text-ink",
        count === 0 && "cursor-default opacity-40",
      )}
      onClick={() => onFilter(active ? "all" : filter)}
    >
      {label}
      <span className="tabular">{formatNumber(count)}</span>
    </button>
  );
}

export function BatchStatusBand({
  batch,
  activeFilter,
  onFilter,
}: BatchStatusBandProps) {
  const { counts } = batch;
  const needs = counts.needs_onboarding + counts.building;
  const invalid = counts.invalid + counts.duplicate;
  const failed = counts.failed + counts.partial_tasks;
  const completed = Math.max(0, counts.finished - failed);
  const hasTasks = counts.tasks > 0;
  const taskHeadline =
    counts.running > 0
      ? { value: counts.running, label: "运行中" }
      : counts.queued > 0
        ? { value: counts.queued, label: "排队中" }
        : counts.paused > 0
          ? { value: counts.paused, label: "已暂停" }
          : completed > 0
            ? { value: completed, label: "已完成" }
            : failed > 0
              ? { value: failed, label: "失败／部分" }
              : { value: 0, label: "运行中" };

  return (
    <section
      className="overflow-hidden rounded-panel border border-line bg-surface"
      aria-label="批次状态带"
    >
      <div className="grid grid-cols-1 divide-y divide-line sm:grid-cols-[1.25fr_1.15fr_1fr] sm:divide-x sm:divide-y-0">
        <div className="px-5 py-4">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-xs font-semibold tracking-[0.04em] text-ink-3">站点</h2>
            <span className="text-xs text-ink-3 tabular">
              {formatNumber(counts.sites)} 个
            </span>
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl leading-8 font-semibold tracking-[-0.02em] text-ink tabular">
              {formatNumber(counts.ready)}
            </span>
            <span className="text-sm text-ink-2">可采</span>
          </div>
          <div className="mt-2.5">
            <ReadinessBar
              ready={counts.ready}
              needs={counts.needs_onboarding}
              building={counts.building}
              invalid={counts.invalid}
              duplicate={counts.duplicate}
            />
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <FilterChip
              label="未启动"
              count={counts.startable}
              filter="startable"
              activeFilter={activeFilter}
              onFilter={onFilter}
            />
            <FilterChip
              label="待接入"
              count={needs}
              filter="needs"
              activeFilter={activeFilter}
              onFilter={onFilter}
            />
            <FilterChip
              label="无效／重复"
              count={invalid}
              filter="invalid"
              activeFilter={activeFilter}
              onFilter={onFilter}
            />
          </div>
        </div>

        <div className="px-5 py-4">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-xs font-semibold tracking-[0.04em] text-ink-3">任务</h2>
            <span className="text-xs text-ink-3 tabular">
              {formatNumber(counts.tasks)} 个
            </span>
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl leading-8 font-semibold tracking-[-0.02em] text-ink tabular">
              {formatNumber(taskHeadline.value)}
            </span>
            <span className="text-sm text-ink-2">{taskHeadline.label}</span>
          </div>
          <p className="mt-1 text-xs text-ink-3">
            {hasTasks
              ? "任务按队列逐个执行；完成后保留结果。"
              : "尚未创建任务；启动可采站点后开始。"}
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            <FilterChip
              label="排队"
              count={counts.queued}
              filter="queued"
              activeFilter={activeFilter}
              onFilter={onFilter}
            />
            <FilterChip
              label="暂停"
              count={counts.paused}
              filter="paused"
              activeFilter={activeFilter}
              onFilter={onFilter}
            />
            <FilterChip
              label="完成"
              count={completed}
              filter="finished"
              activeFilter={activeFilter}
              onFilter={onFilter}
            />
            <FilterChip
              label="失败／部分"
              count={failed}
              filter="failed"
              activeFilter={activeFilter}
              onFilter={onFilter}
            />
          </div>
        </div>

        <div className="px-5 py-4">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-xs font-semibold tracking-[0.04em] text-ink-3">结果</h2>
            <span className="text-xs text-ink-3">当前任务</span>
          </div>
          <div className="mt-1 flex items-baseline gap-2">
            <span className="text-2xl leading-8 font-semibold tracking-[-0.02em] text-ink tabular">
              {hasTasks ? formatNumber(batch.valid_products) : "—"}
            </span>
            <span className="text-sm text-ink-2">有效商品</span>
          </div>
          <p className="mt-1 text-xs text-ink-3">
            {hasTasks
              ? `失败商品 ${formatNumber(batch.failed_products)}`
              : "任务结束后显示有效与失败商品。"}
          </p>
        </div>
      </div>
    </section>
  );
}
