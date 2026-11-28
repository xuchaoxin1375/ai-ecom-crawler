import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { RefreshCw } from "lucide-react";
import type { TaskAnalysis, TaskSummary } from "../../../lib/api";
import { formatClock, formatNumber, taskStateLabel } from "../../../lib/format";
import { ErrorNotice } from "../../../components/ui/ErrorNotice";
import { AnalysisDataTable } from "./AnalysisDataTable";
import { DiscoveryBudget } from "./DiscoveryBudget";
import { FailureBreakdown } from "./FailureBreakdown";
import { ThroughputChart } from "./ThroughputChart";
import {
  DEFAULT_VISIBILITY,
  ITEM_SERIES,
  REQUEST_SERIES,
  formatPercent,
  formatRate,
  formatRunDuration,
  isActiveState,
  itemTotal,
  requestReasonLabel,
  requestTotal,
  type AnalysisMode,
  type ChartMode,
  type SeriesVisibility,
} from "./analysis";
import { useRunAnalysis } from "./useRunAnalysis";

interface RunAnalysisPanelProps {
  task: TaskSummary;
}

type WindowChoice = "auto" | "full" | "1800" | "900" | "300";
type BucketChoice = "auto" | "60" | "300";

const WINDOW_OPTIONS: { value: WindowChoice; label: string }[] = [
  { value: "auto", label: "自动" },
  { value: "full", label: "全程" },
  { value: "1800", label: "最近 30 分钟" },
  { value: "900", label: "最近 15 分钟" },
  { value: "300", label: "最近 5 分钟" },
];

const BUCKET_OPTIONS: { value: BucketChoice; label: string }[] = [
  { value: "auto", label: "自动" },
  { value: "60", label: "1 分钟" },
  { value: "300", label: "5 分钟" },
];

function visibleItemCount(visibility: SeriesVisibility): number {
  return ITEM_SERIES.filter((series) => visibility[series.key]).length;
}

function requestVisible(visibility: SeriesVisibility): boolean {
  return REQUEST_SERIES.some((series) => visibility[series.key]);
}

function Kpi({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="rounded-panel border border-line bg-surface px-4 py-3">
      <p className="text-xs text-ink-3">{label}</p>
      <p className="mt-1 text-[22px] leading-7 font-semibold tabular text-ink">
        {value}
      </p>
      <p className="mt-0.5 text-[11px] leading-4 text-ink-3">{detail}</p>
    </div>
  );
}

function LegendChip({
  label,
  color,
  count,
  active,
  disabled,
  dashed,
  dotted,
  title,
  onClick,
}: {
  label: string;
  color: string;
  count: number;
  active: boolean;
  disabled?: boolean;
  dashed?: boolean;
  dotted?: boolean;
  title?: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-disabled={disabled || undefined}
      title={title}
      onClick={onClick}
      className={`inline-flex min-h-11 items-center gap-2 rounded-full border px-3 text-xs transition-colors sm:min-h-8 ${
        disabled
          ? "cursor-not-allowed border-line bg-surface-muted text-ink-3 opacity-60"
          : active
            ? "border-line-strong bg-surface text-ink shadow-raised"
            : "border-line bg-surface-muted text-ink-2 hover:text-ink"
      }`}
    >
      <span
        className="h-0 w-4 border-t-2"
        style={{
          borderColor: disabled ? "var(--color-line-strong)" : color,
          borderTopStyle: dotted ? "dotted" : dashed ? "dashed" : "solid",
        }}
        aria-hidden="true"
      />
      <span>{label}</span>
      <span className="tabular text-[11px] text-ink-3">{formatNumber(count)}</span>
    </button>
  );
}

function DiagnosticNotice({ analysis }: { analysis: TaskAnalysis }) {
  const diagnostic = analysis.diagnostics[0];
  if (!diagnostic || diagnostic.code === "request_log_truncated") return null;
  const danger = diagnostic.tone === "danger";
  return (
    <div
      className={`flex flex-wrap items-center justify-between gap-2 rounded-panel border px-4 py-3 text-sm leading-6 ${
        danger
          ? "border-danger/25 bg-danger-soft text-danger"
          : "border-warning/25 bg-warning-soft text-warning"
      }`}
      role="status"
    >
      <p>
        <strong className="font-semibold">{diagnostic.title}</strong>
        <span className="ml-2">{diagnostic.detail}</span>
      </p>
      {diagnostic.action_view === "data_failed" ? (
        <Link className="shrink-0 underline" to="?items=failed">
          查看失败项
        </Link>
      ) : diagnostic.action_view === "detail" ? (
        <Link className="shrink-0 underline" to="?view=detail">
          查看运行明细
        </Link>
      ) : null}
    </div>
  );
}

function RequestNotice({ analysis }: { analysis: TaskAnalysis }) {
  if (analysis.requests.available && !analysis.requests.truncated) return null;
  if (analysis.requests.truncated) {
    return (
      <div
        className="rounded-panel border border-warning/25 bg-warning-soft px-4 py-3 text-sm leading-6 text-warning"
        role="status"
      >
        请求记录达到容量上限，图表只覆盖已记录的部分。
      </div>
    );
  }
  return (
    <div
      className="rounded-panel border border-line bg-surface-muted px-4 py-3 text-sm leading-6 text-ink-2"
      role="status"
    >
      {requestReasonLabel(analysis.requests.reason)}
      {analysis.requests.reason === "legacy" ? (
        <span className="ml-1 text-ink-3">请求数、重试和 429 曲线只对新运行可用。</span>
      ) : null}
    </div>
  );
}

export function RunAnalysisPanel({ task }: RunAnalysisPanelProps) {
  const [mode, setMode] = useState<AnalysisMode>("rate");
  const [chartMode, setChartMode] = useState<ChartMode>("combined");
  const [visibility, setVisibility] = useState<SeriesVisibility>(DEFAULT_VISIBILITY);
  const [windowChoice, setWindowChoice] = useState<WindowChoice>("auto");
  const [bucketChoice, setBucketChoice] = useState<BucketChoice>("auto");
  const [frozen, setFrozen] = useState(false);
  const [tableOpen, setTableOpen] = useState(false);

  const active = isActiveState(task.state);
  const autoWindow = active ? 900 : null;
  const windowSeconds =
    windowChoice === "auto"
      ? autoWindow
      : windowChoice === "full"
        ? null
        : Number(windowChoice);
  const bucketSeconds = bucketChoice === "auto" ? null : Number(bucketChoice);
  const analysisQuery = useRunAnalysis(task, {
    windowSeconds,
    bucketSeconds,
    frozen,
    enabled: task.state !== "DRAFT" && task.state !== "QUEUED",
  });

  const analysis = analysisQuery.data;
  const requestsAvailable = analysis?.requests.available ?? false;
  const empty = analysis && analysis.series.points.length === 0;
  const effectiveChartMode = requestVisible(visibility) ? chartMode : "combined";
  const frozenActive = frozen && task.state === "RUNNING";
  const discovery = task.task_type === "discovery";
  const recentDetail = useMemo(() => {
    if (!analysis) return "";
    const count = analysis.summary.recent_buckets ?? 0;
    const prefix = active ? "最近" : "末尾";
    return `${prefix} ${count} 个桶 · ${formatRate(
      analysis.summary.recent_throughput_per_minute,
    )} ${discovery ? "个" : "件"}/分钟`;
  }, [active, analysis, discovery]);

  function toggleSeries(key: keyof SeriesVisibility) {
    const isItem = ITEM_SERIES.some((series) => series.key === key);
    if (isItem && visibility[key] && visibleItemCount(visibility) === 1) {
      return;
    }
    if (!isItem && !requestsAvailable) return;
    const next = { ...visibility, [key]: !visibility[key] };
    if (!isItem && !requestVisible(next)) {
      setChartMode("combined");
    }
    setVisibility(next);
  }

  const showChartMode = requestsAvailable && requestVisible(visibility);

  if (task.state === "DRAFT" || task.state === "QUEUED") {
    return (
      <section className="rounded-panel border border-line bg-surface px-6 py-12 text-center">
        <h2 className="text-[17px] font-semibold text-ink">运行尚未开始</h2>
        <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-ink-2">
          任务开始后，这里会按时间桶展示产出、失败和请求曲线；排队阶段不画空图。
        </p>
      </section>
    );
  }

  if (analysisQuery.isPending) {
    return (
      <div className="space-y-4" aria-busy="true">
        <span className="sr-only" role="status">
          正在读取运行分析…
        </span>
        <div className="h-20 animate-pulse rounded-panel border border-line bg-surface" />
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          {[0, 1, 2, 3].map((item) => (
            <div
              key={item}
              className="h-24 animate-pulse rounded-panel border border-line bg-surface"
            />
          ))}
        </div>
        <div className="h-[360px] animate-pulse rounded-panel border border-line bg-surface" />
      </div>
    );
  }

  if (analysisQuery.isError || !analysis) {
    return (
      <ErrorNotice
        title="读取运行分析失败"
        message={
          analysisQuery.error instanceof Error
            ? analysisQuery.error.message
            : "分析服务暂时不可用。"
        }
        onRetry={() => void analysisQuery.refetch()}
      />
    );
  }

  const bucketLabel = analysis.series.bucket_seconds >= 300 ? "5 分钟" : "1 分钟";
  const scopeText = `本次运行 · ${taskStateLabel(task.state)} · ${formatClock(
    analysis.observed_at,
    true,
  )} · ${bucketLabel}桶`;
  const itemUnit = discovery ? "个" : "件";

  return (
    <div className="space-y-5">
      <section className="rounded-panel border border-line bg-surface">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-ink">
              运行分析
              <span className="ml-2 font-normal text-ink-3">{scopeText}</span>
            </p>
            <p className="mt-0.5 text-[11px] text-ink-3">
              单次运行；商品事件与请求尝试按各自开始时间入桶。
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {active && task.state === "RUNNING" ? (
              <button
                type="button"
                className="inline-flex h-11 items-center sm:h-8 rounded-control border border-line bg-surface px-3 text-xs font-medium text-ink-2 hover:text-ink"
                aria-pressed={frozen}
                onClick={() => {
                  setFrozen((value) => !value);
                  if (frozenActive) void analysisQuery.refetch();
                }}
              >
                {frozenActive ? "回到实时" : "冻结"}
              </button>
            ) : null}
            <button
              type="button"
              className="inline-flex h-11 items-center sm:h-8 gap-1.5 rounded-control border border-line bg-surface px-3 text-xs font-medium text-ink-2 hover:text-ink disabled:opacity-50"
              onClick={() => void analysisQuery.refetch()}
              disabled={analysisQuery.isFetching}
            >
              <RefreshCw
                size={13}
                aria-hidden="true"
                className={analysisQuery.isFetching ? "animate-spin" : undefined}
              />
              刷新
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-end gap-x-4 gap-y-3 px-4 py-3 sm:px-5">
          <label className="flex flex-col gap-1 text-[11px] text-ink-3">
            时间窗口
            <select
              className="h-11 rounded-control sm:h-8 border border-line-strong bg-surface px-2 text-xs text-ink"
              value={windowChoice}
              onChange={(event) => setWindowChoice(event.target.value as WindowChoice)}
            >
              {WINDOW_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[11px] text-ink-3">
            时间桶
            <select
              className="h-11 rounded-control sm:h-8 border border-line-strong bg-surface px-2 text-xs text-ink"
              value={bucketChoice}
              onChange={(event) => setBucketChoice(event.target.value as BucketChoice)}
            >
              {BUCKET_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
          <div className="flex flex-col gap-1 text-[11px] text-ink-3">
            数值
            <div
              className="inline-flex h-11 rounded-control sm:h-8 border border-line-strong bg-surface p-0.5"
              role="group"
              aria-label="数值模式"
            >
              {(["rate", "cumulative"] as AnalysisMode[]).map((value) => (
                <button
                  key={value}
                  type="button"
                  aria-pressed={mode === value}
                  className={`rounded-[3px] px-2.5 text-xs font-medium ${
                    mode === value
                      ? "bg-accent-soft text-accent"
                      : "text-ink-2 hover:text-ink"
                  }`}
                  onClick={() => setMode(value)}
                >
                  {value === "rate" ? "速率" : "累计"}
                </button>
              ))}
            </div>
          </div>
          {showChartMode ? (
            <div className="flex flex-col gap-1 text-[11px] text-ink-3">
              图表布局
              <div
                className="inline-flex h-11 rounded-control sm:h-8 border border-line-strong bg-surface p-0.5"
                role="group"
                aria-label="图表布局"
              >
                {(["combined", "split"] as ChartMode[]).map((value) => (
                  <button
                    key={value}
                    type="button"
                    aria-pressed={chartMode === value}
                    className={`rounded-[3px] px-2.5 text-xs font-medium ${
                      chartMode === value
                        ? "bg-accent-soft text-accent"
                        : "text-ink-2 hover:text-ink"
                    }`}
                    onClick={() => setChartMode(value)}
                  >
                    {value === "combined" ? "合图" : "分图"}
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          {frozenActive || analysisQuery.isFetching ? (
            <p className="ml-auto text-[11px] text-ink-3">
              {frozenActive ? "已冻结" : "正在更新…"}
            </p>
          ) : null}
        </div>
      </section>

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Kpi
          label="运行时长"
          value={formatRunDuration(analysis.scope.run_seconds)}
          detail="暂停不计入累计时长"
        />
        <Kpi
          label="平均吞吐"
          value={`${formatRate(analysis.summary.average_throughput_per_minute)} ${itemUnit}/分钟`}
          detail={recentDetail}
        />
        <Kpi
          label={discovery ? "有效网址率" : "有效率"}
          value={formatPercent(analysis.summary.yield_rate)}
          detail={`${formatNumber(analysis.summary.valid)} / ${formatNumber(
            analysis.summary.processed,
          )} 已处理`}
        />
        <Kpi
          label={discovery ? "失败网址率" : "失败率"}
          value={formatPercent(analysis.summary.failure_rate)}
          detail={`${formatNumber(analysis.summary.failed)} / ${formatNumber(
            analysis.summary.processed,
          )} 已处理`}
        />
      </div>

      <DiagnosticNotice analysis={analysis} />
      <RequestNotice analysis={analysis} />

      {empty ? (
        <section className="rounded-panel border border-line bg-surface px-6 py-10 text-center">
          <h2 className="text-[17px] font-semibold text-ink">还没有可分析的时间桶</h2>
          <p className="mx-auto mt-1 max-w-md text-sm leading-6 text-ink-2">
            {active
              ? "任务已开始，等第一个工作项完成后曲线会出现。"
              : "这次运行没有产生商品级事件；可以查看运行明细或失败项。"}
          </p>
        </section>
      ) : (
        <section className="rounded-panel border border-line bg-surface">
          <div className="border-b border-line px-4 py-4 sm:px-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div>
                <h2 className="text-[17px] leading-6 font-semibold text-ink">
                  产出与失败
                </h2>
                <p className="mt-0.5 text-xs leading-5 text-ink-3">
                  {mode === "rate"
                    ? `每个时间桶的实际${discovery ? "网址" : "商品"}数；请求指标默认关闭。`
                    : `从运行开始累计到当前时间桶；请求指标默认关闭。`}
                </p>
              </div>
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              {ITEM_SERIES.map((series) => (
                <LegendChip
                  key={series.key}
                  label={series.label}
                  color={series.color}
                  dashed={series.dashed}
                  count={itemTotal(analysis, series.key)}
                  active={visibility[series.key]}
                  title={
                    visibility[series.key] && visibleItemCount(visibility) === 1
                      ? "至少保留一条产出曲线"
                      : undefined
                  }
                  onClick={() => toggleSeries(series.key)}
                />
              ))}
              <span
                className="mx-1 hidden h-4 w-px bg-line sm:block"
                aria-hidden="true"
              />
              {REQUEST_SERIES.map((series) => (
                <LegendChip
                  key={series.key}
                  label={series.label}
                  color={series.color}
                  dashed={series.dashed}
                  dotted={series.dotted}
                  count={requestTotal(analysis, series.key)}
                  active={visibility[series.key]}
                  disabled={!analysis.requests.available}
                  title={
                    analysis.requests.available
                      ? undefined
                      : requestReasonLabel(analysis.requests.reason)
                  }
                  onClick={() => toggleSeries(series.key)}
                />
              ))}
            </div>
            {analysis.requests.available ? (
              <p className="mt-2 text-[11px] leading-5 text-ink-3">
                请求曲线使用独立纵轴；打开后可与产出曲线同图，或切换成分图。
              </p>
            ) : null}
          </div>

          <div className="px-2 pb-2 pt-3 sm:px-3">
            <ThroughputChart
              analysis={analysis}
              mode={mode}
              chartMode={effectiveChartMode}
              visibility={visibility}
            />
          </div>

          <div className="border-t border-line px-4 py-2.5 sm:px-5">
            <button
              type="button"
              className="text-xs font-medium text-accent hover:underline"
              aria-expanded={tableOpen}
              onClick={() => setTableOpen((value) => !value)}
            >
              {tableOpen ? "收起数据表" : "展开数据表"}
            </button>
          </div>
          {tableOpen ? (
            <div className="border-t border-line px-4 py-4 sm:px-5">
              <AnalysisDataTable analysis={analysis} mode={mode} />
            </div>
          ) : null}
        </section>
      )}

      <div className="grid grid-cols-1 items-start gap-5 xl:grid-cols-2">
        <FailureBreakdown analysis={analysis} />
        <DiscoveryBudget analysis={analysis} />
      </div>
    </div>
  );
}
