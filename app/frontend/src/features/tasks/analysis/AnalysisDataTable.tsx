import type { TaskAnalysis } from "../../../lib/api";
import { formatNumber } from "../../../lib/format";
import {
  formatPercent,
  formatPointValue,
  pointLabel,
  requestCounts,
  type AnalysisMode,
} from "./analysis";

interface AnalysisDataTableProps {
  analysis: TaskAnalysis;
  mode: AnalysisMode;
}

const MAX_ROWS = 100;

export function AnalysisDataTable({ analysis, mode }: AnalysisDataTableProps) {
  const points = analysis.series.points;
  const rows = points.slice(-MAX_ROWS);
  const requestsAvailable = analysis.requests.available;
  return (
    <div>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-ink">数据表</h3>
        <p className="text-xs text-ink-3">
          每行一个时间桶，作为图表的可访问替代。
          {points.length > MAX_ROWS ? ` 仅显示最近 ${MAX_ROWS} 个时间桶。` : ""}
        </p>
      </div>
      <div className="max-h-[420px] overflow-auto rounded-control border border-line">
        <table className="w-full min-w-[620px] border-collapse text-left text-xs">
          <caption className="sr-only">
            运行分析数据表；时间桶、处理、有效、排除、失败、失败率
            {requestsAvailable ? "、请求、重试、错误响应和 429" : ""}。
          </caption>
          <thead className="sticky top-0 z-10 bg-surface-muted text-ink-3">
            <tr>
              <th scope="col" className="px-3 py-2 font-semibold">
                时间
              </th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">
                处理
              </th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">
                有效
              </th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">
                排除
              </th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">
                失败
              </th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">
                失败率
              </th>
              {requestsAvailable ? (
                <>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">
                    请求
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">
                    重试
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">
                    错误响应
                  </th>
                  <th scope="col" className="px-3 py-2 text-right font-semibold">
                    429
                  </th>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.map((point) => {
              const processed = formatPointValue(point, "processed", mode);
              const failed = formatPointValue(point, "failed", mode);
              const failureRate = processed ? failed / processed : 0;
              return (
                <tr key={point.start} className="border-t border-line">
                  <th
                    scope="row"
                    className="whitespace-nowrap px-3 py-1.5 font-normal text-ink-2"
                  >
                    {pointLabel(point)}
                  </th>
                  <td className="px-3 py-1.5 text-right tabular text-ink">
                    {formatNumber(processed)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular text-ink">
                    {formatNumber(formatPointValue(point, "valid", mode))}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular text-ink">
                    {formatNumber(
                      mode === "cumulative"
                        ? point.cumulative_excluded
                        : point.excluded,
                    )}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular text-ink">
                    {formatNumber(failed)}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular text-ink-2">
                    {formatPercent(failureRate)}
                  </td>
                  {requestsAvailable ? (
                    <>
                      <td className="px-3 py-1.5 text-right tabular text-ink-2">
                        {formatNumber(requestCounts(point, "requests", mode))}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular text-ink-2">
                        {formatNumber(requestCounts(point, "retries", mode))}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular text-ink-2">
                        {formatNumber(requestCounts(point, "errors", mode))}
                      </td>
                      <td className="px-3 py-1.5 text-right tabular text-ink-2">
                        {formatNumber(requestCounts(point, "rate_limited", mode))}
                      </td>
                    </>
                  ) : null}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
