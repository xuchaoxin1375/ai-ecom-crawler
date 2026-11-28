import type { TaskAnalysis } from "../../../lib/api";
import { formatNumber } from "../../../lib/format";
import { formatRunDuration } from "./analysis";

interface DiscoveryBudgetProps {
  analysis: TaskAnalysis;
}

function ratio(value: number, total: number): number {
  if (total <= 0) return 0;
  return Math.max(0, Math.min(100, (value / total) * 100));
}

function FunnelRow({
  label,
  value,
  total,
  tone = "accent",
}: {
  label: string;
  value: number;
  total: number;
  tone?: "accent" | "success" | "danger";
}) {
  const width = ratio(value, total);
  const bar =
    tone === "success" ? "bg-success" : tone === "danger" ? "bg-danger" : "bg-accent";
  return (
    <div className="grid grid-cols-[76px_minmax(0,1fr)_64px] items-center gap-2">
      <span className="text-xs text-ink-2">{label}</span>
      <div className="h-2 overflow-hidden rounded-full bg-surface-sunken">
        <div
          className={`h-full rounded-full ${bar}`}
          style={{ width: `${Math.max(value > 0 ? 2 : 0, width)}%` }}
        />
      </div>
      <span className="text-right text-xs tabular text-ink">{formatNumber(value)}</span>
    </div>
  );
}

function BudgetRow({
  label,
  used,
  limit,
  format = formatNumber,
}: {
  label: string;
  used: number;
  limit: number | null;
  format?: (value: number) => string;
}) {
  const limited = limit !== null && limit !== undefined;
  const percent = limited && limit > 0 ? (used / limit) * 100 : 0;
  const tone =
    percent >= 100 ? "bg-danger" : percent >= 90 ? "bg-warning" : "bg-accent";
  return (
    <div>
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
        <span className="text-ink-2">{label}</span>
        <span className="tabular text-ink-3">
          {format(used)} / {limited ? format(limit) : "不设限"}
        </span>
      </div>
      {limited ? (
        <div
          className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface-sunken"
          role="progressbar"
          aria-label={`${label}预算`}
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={Math.min(used, limit)}
        >
          <div
            className={`h-full rounded-full ${tone}`}
            style={{ width: `${Math.min(100, Math.max(used > 0 ? 2 : 0, percent))}%` }}
          />
        </div>
      ) : (
        <div className="mt-1.5 h-1.5 rounded-full border border-dashed border-line-strong" />
      )}
    </div>
  );
}

export function DiscoveryBudget({ analysis }: DiscoveryBudgetProps) {
  const discovery = analysis.scope.task_type === "discovery";
  const summary = analysis.summary;
  const total = Math.max(
    1,
    summary.discovered_urls,
    summary.product_candidates,
    summary.processed,
  );
  const budget = analysis.budget;
  const requestRow = analysis.requests.available;
  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="border-b border-line px-4 py-4 sm:px-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">发现与预算</h2>
          <span className="text-xs text-ink-3">{summary.coverage.label}</span>
        </div>
        <p className="mt-0.5 text-xs leading-5 text-ink-3">
          覆盖只代表规则声明的来源，不冒充整站总量；不提供剩余时间估算。
        </p>
      </div>
      <div className="space-y-5 px-4 py-4 sm:px-5">
        <div className="space-y-2">
          <FunnelRow label="发现网址" value={summary.discovered_urls} total={total} />
          <FunnelRow
            label={discovery ? "网址候选" : "商品候选"}
            value={summary.product_candidates}
            total={total}
          />
          <FunnelRow label="已处理" value={summary.processed} total={total} />
          <FunnelRow
            label={discovery ? "有效网址" : "有效商品"}
            value={summary.valid}
            total={total}
            tone="success"
          />
          <FunnelRow
            label={discovery ? "失败网址" : "失败商品"}
            value={summary.failed}
            total={total}
            tone="danger"
          />
        </div>

        <div className="border-t border-line pt-4">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-xs font-semibold text-ink-2">预算</h3>
            <span className="text-[11px] text-ink-3">
              待处理 {formatNumber(summary.pending_products)}
            </span>
          </div>
          <div className="space-y-3">
            {!discovery ? (
              <BudgetRow
                label="商品数"
                used={budget.used_products}
                limit={budget.max_products}
              />
            ) : null}
            <BudgetRow
              label="运行时长"
              used={budget.used_seconds}
              limit={budget.max_seconds}
              format={(value) => formatRunDuration(value)}
            />
            <BudgetRow
              label={discovery ? "网址数" : "网址数"}
              used={budget.used_urls}
              limit={budget.max_urls}
            />
            {requestRow ? (
              <BudgetRow
                label="请求数"
                used={budget.used_requests ?? 0}
                limit={budget.max_requests}
              />
            ) : null}
          </div>
        </div>
      </div>
    </section>
  );
}
