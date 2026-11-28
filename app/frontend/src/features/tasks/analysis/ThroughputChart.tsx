import { useEffect, useRef, useState } from "react";
import type { EChartsCoreOption } from "echarts/core";
import type { TaskAnalysis } from "../../../lib/api";
import { formatClock, formatNumber } from "../../../lib/format";
import {
  ITEM_SERIES,
  REQUEST_SERIES,
  formatPointValue,
  requestCounts,
  type AnalysisMode,
  type ChartMode,
  type SeriesVisibility,
} from "./analysis";
import { colorForToken, readChartTheme } from "./chartTheme";
import { loadChartRuntime, type ChartInstance } from "./chartRuntime";

interface ThroughputChartProps {
  analysis: TaskAnalysis;
  mode: AnalysisMode;
  chartMode: ChartMode;
  visibility: SeriesVisibility;
}

const TEST_MODE = import.meta.env.MODE === "test";

function requestVisible(visibility: SeriesVisibility): boolean {
  return (
    visibility.requests ||
    visibility.retries ||
    visibility.errors ||
    visibility.rate_limited
  );
}

function itemUnit(analysis: TaskAnalysis, mode: AnalysisMode): string {
  const base = analysis.scope.task_type === "discovery" ? "个" : "件";
  return mode === "rate" ? `${base}/分钟` : base;
}

function requestUnit(mode: AnalysisMode): string {
  return mode === "rate" ? "次/分钟" : "次";
}

function tooltipFormatter(mode: AnalysisMode, analysis: TaskAnalysis, muted: string) {
  const itemSuffix =
    analysis.scope.task_type === "discovery"
      ? mode === "rate"
        ? " 个/分钟"
        : " 个"
      : mode === "rate"
        ? " 件/分钟"
        : " 件";
  const requestSuffix = mode === "rate" ? " 次/分钟" : " 次";
  return (params: unknown) => {
    const rows = Array.isArray(params) ? params : [params];
    if (!rows.length) return "";
    const first = rows[0] as {
      axisValueLabel?: string;
      axisValue?: string;
    };
    const title = first.axisValueLabel ?? first.axisValue ?? "";
    const lines = rows
      .map((row) => {
        const item = row as {
          marker?: string;
          seriesName?: string;
          value?: unknown;
        };
        const isRequest = REQUEST_SERIES.some(
          (series) => series.label === item.seriesName,
        );
        const value = Number(item.value ?? 0);
        const suffix = isRequest ? requestSuffix : itemSuffix;
        return `<div style="display:flex;align-items:center;gap:8px;justify-content:space-between;min-width:168px;line-height:20px"><span>${item.marker ?? ""}${item.seriesName ?? ""}</span><strong>${formatNumber(value)}${suffix}</strong></div>`;
      })
      .join("");
    return `<div style="font-size:12px"><div style="margin-bottom:4px;color:${muted}">${title}</div>${lines}</div>`;
  };
}

function baseGrid(requestAxis: boolean, showZoom: boolean) {
  return {
    left: 8,
    right: requestAxis ? 12 : 8,
    top: 28,
    bottom: showZoom ? 38 : 8,
    containLabel: true,
  };
}

function xAxis(
  points: TaskAnalysis["series"]["points"],
  theme: ReturnType<typeof readChartTheme>,
) {
  const labels = points.map((point) => formatClock(point.start));
  const step = Math.max(1, Math.ceil(labels.length / 4));
  return {
    type: "category" as const,
    data: labels,
    boundaryGap: false,
    axisLine: { lineStyle: { color: theme.lineStrong } },
    axisTick: { show: false },
    axisLabel: {
      color: theme.ink3,
      fontSize: 10,
      hideOverlap: true,
      interval: (index: number) =>
        index === 0 || index === labels.length - 1 || index % step === 0,
    },
    splitLine: { show: false },
  };
}

function itemSeriesOption(
  analysis: TaskAnalysis,
  mode: AnalysisMode,
  visibility: SeriesVisibility,
  theme: ReturnType<typeof readChartTheme>,
  includeRequests: boolean,
): EChartsCoreOption {
  const points = analysis.series.points;
  const series: Record<string, unknown>[] = [];

  for (const item of ITEM_SERIES) {
    if (!visibility[item.key]) continue;
    const color = colorForToken(theme, item.color);
    series.push({
      name: item.label,
      type: "line",
      yAxisIndex: 0,
      data: points.map((point) => formatPointValue(point, item.key, mode)),
      showSymbol: false,
      smooth: false,
      connectNulls: false,
      lineStyle: {
        width: item.key === "processed" ? 2.4 : 1.8,
        color,
        type: item.dashed ? "dashed" : "solid",
      },
      itemStyle: { color },
      areaStyle: item.key === "processed" ? { color, opacity: 0.075 } : undefined,
      emphasis: { focus: "series" },
      z: item.key === "processed" ? 3 : 2,
    });
  }

  if (includeRequests) {
    for (const request of REQUEST_SERIES) {
      if (!visibility[request.key]) continue;
      const color = colorForToken(theme, request.color);
      series.push({
        name: request.label,
        type: "line",
        yAxisIndex: 1,
        data: points.map((point) => requestCounts(point, request.key, mode)),
        showSymbol: false,
        smooth: false,
        connectNulls: false,
        lineStyle: {
          width: 1.8,
          color,
          type: request.dotted ? "dotted" : request.dashed ? "dashed" : "solid",
        },
        itemStyle: { color },
        emphasis: { focus: "series" },
        z: 1,
      });
    }
  }

  const requestAxis = includeRequests && requestVisible(visibility);
  const width = points.length > 24 ? 640 : 0;
  const showZoom = points.length > 24;
  const option: EChartsCoreOption = {
    animation: true,
    animationDuration: 220,
    animationDurationUpdate: 120,
    grid: baseGrid(requestAxis, showZoom),
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: theme.surface,
      borderColor: theme.lineStrong,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: theme.ink, fontSize: 12 },
      axisPointer: {
        type: "line",
        lineStyle: { color: theme.lineStrong, type: "dashed" },
      },
      formatter: tooltipFormatter(mode, analysis, theme.ink3),
    },
    xAxis: xAxis(points, theme),
    yAxis: [
      {
        type: "value",
        name: itemUnit(analysis, mode),
        nameTextStyle: { color: theme.ink3, fontSize: 10 },
        minInterval: 1,
        splitLine: {
          lineStyle: { color: theme.line, type: "dashed", opacity: 0.72 },
        },
        axisLabel: { color: theme.ink3, fontSize: 10 },
        axisLine: { show: false },
      },
      ...(requestAxis
        ? [
            {
              type: "value",
              name: requestUnit(mode),
              position: "right",
              nameTextStyle: { color: theme.ink3, fontSize: 10 },
              minInterval: 1,
              splitLine: { show: false },
              axisLabel: { color: theme.info, fontSize: 10 },
              axisLine: { show: false },
            },
          ]
        : []),
    ],
    series,
  };
  if (showZoom && window.innerWidth >= width) {
    (option as Record<string, unknown>).dataZoom = [
      {
        type: "slider",
        height: 20,
        bottom: 2,
        showDetail: false,
        brushSelect: false,
        borderColor: "transparent",
        backgroundColor: theme.surfaceMuted,
        fillerColor: `${theme.accent}22`,
        handleStyle: { color: theme.accent, borderColor: theme.surface },
        textStyle: { color: theme.ink3, fontSize: 9 },
      },
    ];
  }
  return option;
}

function requestSeriesOption(
  analysis: TaskAnalysis,
  mode: AnalysisMode,
  visibility: SeriesVisibility,
  theme: ReturnType<typeof readChartTheme>,
): EChartsCoreOption {
  const points = analysis.series.points;
  const series = REQUEST_SERIES.filter((request) => visibility[request.key]).map(
    (request) => {
      const color = colorForToken(theme, request.color);
      return {
        name: request.label,
        type: "line",
        data: points.map((point) => requestCounts(point, request.key, mode)),
        showSymbol: false,
        smooth: false,
        connectNulls: false,
        lineStyle: {
          width: 1.8,
          color,
          type: request.dotted ? "dotted" : request.dashed ? "dashed" : "solid",
        },
        itemStyle: { color },
        emphasis: { focus: "series" },
      };
    },
  );
  return {
    animation: true,
    animationDuration: 180,
    animationDurationUpdate: 120,
    grid: { left: 8, right: 8, top: 24, bottom: 8, containLabel: true },
    tooltip: {
      trigger: "axis",
      confine: true,
      backgroundColor: theme.surface,
      borderColor: theme.lineStrong,
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: theme.ink, fontSize: 12 },
      axisPointer: {
        type: "line",
        lineStyle: { color: theme.lineStrong, type: "dashed" },
      },
      formatter: tooltipFormatter(mode, analysis, theme.ink3),
    },
    xAxis: xAxis(points, theme),
    yAxis: [
      {
        type: "value",
        name: requestUnit(mode),
        nameTextStyle: { color: theme.ink3, fontSize: 10 },
        minInterval: 1,
        splitLine: {
          lineStyle: { color: theme.line, type: "dashed", opacity: 0.72 },
        },
        axisLabel: { color: theme.info, fontSize: 10 },
        axisLine: { show: false },
      },
    ],
    series,
  };
}

export function ThroughputChart({
  analysis,
  mode,
  chartMode,
  visibility,
}: ThroughputChartProps) {
  const mainRef = useRef<HTMLDivElement>(null);
  const requestRef = useRef<HTMLDivElement>(null);
  const mainChart = useRef<ChartInstance | null>(null);
  const requestChart = useRef<ChartInstance | null>(null);
  const [generation, setGeneration] = useState(0);
  const [error, setError] = useState(false);
  const [retryKey, setRetryKey] = useState(0);
  const hasPoints = analysis.series.points.length > 0;

  useEffect(() => {
    if (TEST_MODE || !hasPoints) return;
    let cancelled = false;
    let observer: ResizeObserver | null = null;
    void (async () => {
      try {
        const runtime = await loadChartRuntime();
        if (cancelled || !mainRef.current) return;
        mainChart.current = runtime.init(mainRef.current, undefined, {
          renderer: "canvas",
        });
        if (chartMode === "split" && requestRef.current) {
          requestChart.current = runtime.init(requestRef.current, undefined, {
            renderer: "canvas",
          });
        }
        observer = new ResizeObserver(() => {
          mainChart.current?.resize();
          requestChart.current?.resize();
        });
        observer.observe(mainRef.current);
        if (requestChart.current && requestRef.current) {
          observer.observe(requestRef.current);
        }
        setGeneration((value) => value + 1);
      } catch {
        if (!cancelled) setError(true);
      }
    })();
    return () => {
      cancelled = true;
      observer?.disconnect();
      mainChart.current?.dispose();
      requestChart.current?.dispose();
      mainChart.current = null;
      requestChart.current = null;
    };
  }, [chartMode, hasPoints, retryKey]);

  useEffect(() => {
    if (!generation) return;
    const theme = readChartTheme(mainRef.current ?? document.documentElement);
    const showRequests = requestVisible(visibility);
    const includeRequests = chartMode === "combined" && showRequests;
    mainChart.current?.setOption(
      itemSeriesOption(analysis, mode, visibility, theme, includeRequests),
      { notMerge: true },
    );
    if (chartMode === "split" && showRequests) {
      requestChart.current?.setOption(
        requestSeriesOption(analysis, mode, visibility, theme),
        { notMerge: true },
      );
      window.requestAnimationFrame(() => requestChart.current?.resize());
    } else {
      requestChart.current?.clear();
    }
  }, [analysis, chartMode, generation, mode, visibility]);

  if (!hasPoints) {
    return (
      <div className="flex h-[220px] items-center justify-center rounded-control border border-dashed border-line bg-surface-muted text-sm text-ink-3">
        还没有可绘制的时间桶。
      </div>
    );
  }

  if (TEST_MODE) {
    return (
      <div
        className="flex h-[220px] items-center justify-center rounded-control border border-line bg-surface-muted text-xs text-ink-3"
        data-testid="analysis-chart-placeholder"
      >
        图表在浏览器中渲染；下方数据表提供同样的数据。
      </div>
    );
  }

  const split = chartMode === "split" && requestVisible(visibility);
  return (
    <div className="space-y-3">
      {error ? (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-control border border-warning/25 bg-warning-soft px-4 py-3 text-sm leading-6 text-warning">
          <span>图表加载失败；下方数据表仍可查看。</span>
          <button
            type="button"
            className="rounded-control border border-warning/30 px-2.5 py-1 text-xs font-medium hover:bg-warning/10"
            onClick={() => {
              setError(false);
              setRetryKey((value) => value + 1);
            }}
          >
            重试图表
          </button>
        </div>
      ) : null}
      <div
        ref={mainRef}
        className={split ? "h-[250px] w-full" : "h-[260px] w-full sm:h-[310px]"}
        role="img"
        aria-label="产出与失败曲线。完整数值见下方数据表。"
      />
      <div
        ref={requestRef}
        className={split ? "h-[170px] w-full" : "hidden"}
        role="img"
        aria-label="请求、重试、错误响应和 429 曲线。完整数值见下方数据表。"
      />
    </div>
  );
}
