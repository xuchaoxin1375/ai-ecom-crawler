import { Cpu, HardDrive, MemoryStick, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import type { SystemInfo } from "../../lib/api";
import { formatBytes, formatDuration } from "../../lib/format";

type Tone = "normal" | "warning" | "danger" | "muted";

const TONE_TEXT: Record<Tone, string> = {
  normal: "text-accent",
  warning: "text-warning",
  danger: "text-danger",
  muted: "text-ink-3",
};

function toneFor(
  value: number | null | undefined,
  warning: number,
  danger: number,
): Tone {
  if (value == null || !Number.isFinite(value)) return "muted";
  if (value >= danger) return "danger";
  if (value >= warning) return "warning";
  return "normal";
}

function percent(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "—" : `${Math.round(value)}%`;
}

function Gauge({
  label,
  value,
  hint,
  tone,
  icon,
}: {
  label: string;
  value: number | null | undefined;
  hint: string;
  tone: Tone;
  icon: ReactNode;
}) {
  const radius = 18;
  const circumference = 2 * Math.PI * radius;
  const clamped = value == null ? 0 : Math.max(0, Math.min(100, value));
  return (
    <div className="flex min-w-0 items-center gap-3 rounded-control border border-line bg-surface px-3 py-3">
      <div
        className="relative h-12 w-12 shrink-0"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={value == null ? undefined : Math.round(clamped)}
        aria-valuetext={value == null ? "采样中" : percent(value)}
      >
        <svg viewBox="0 0 44 44" className="h-12 w-12 -rotate-90" aria-hidden="true">
          <circle
            cx="22"
            cy="22"
            r={radius}
            fill="none"
            strokeWidth="4"
            className="text-line"
            stroke="currentColor"
          />
          <circle
            cx="22"
            cy="22"
            r={radius}
            fill="none"
            strokeWidth="4"
            strokeLinecap="round"
            stroke="currentColor"
            strokeDasharray={circumference}
            strokeDashoffset={circumference * (1 - clamped / 100)}
            className={TONE_TEXT[tone]}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-ink tabular">
          {value == null ? "…" : `${Math.round(clamped)}%`}
        </span>
      </div>
      <div className="min-w-0">
        <p className="flex items-center gap-1 text-xs font-medium text-ink-2">
          {icon}
          {label}
        </p>
        <p className="mt-0.5 truncate text-xs text-ink-3" title={hint}>
          {hint}
        </p>
      </div>
    </div>
  );
}

export function ResourceGauges({
  data,
  isPending,
  isError,
  onRetry,
}: {
  data: SystemInfo | undefined;
  isPending: boolean;
  isError: boolean;
  onRetry: () => void;
}) {
  const resources = data?.resources;
  const diskTotal = Number(data?.storage.disk_total_bytes || 0);
  const diskUsed = Number(data?.storage.disk_used_bytes || 0);
  const diskFree = Number(data?.storage.disk_free_bytes || 0);
  const diskPercent = diskTotal > 0 ? (diskUsed / diskTotal) * 100 : 0;
  const diskLow = diskTotal > 0 && diskFree / diskTotal < 0.1;
  const cpu = resources?.available ? resources.cpu_percent : null;
  const memory = resources?.available ? resources.memory_percent : null;
  const windowSeconds = resources?.cpu_window_ms
    ? Math.max(1, Math.round(resources.cpu_window_ms / 1000))
    : null;
  const sampledAt = resources?.sampled_at
    ? new Date(resources.sampled_at).toLocaleTimeString("zh-CN", { hour12: false })
    : null;

  return (
    <div className="border-b border-line px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <h3 className="text-xs font-semibold text-ink">实时资源</h3>
        <span className="text-xs text-ink-3">
          {isPending && !data
            ? "正在读取…"
            : resources?.available
              ? `${windowSeconds ? `近 ${windowSeconds} 秒采样` : "等待第二次采样"}${sampledAt ? ` · 更新于 ${sampledAt}` : ""}`
              : "资源采样不可用"}
        </span>
        {isError ? (
          <button
            type="button"
            className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline"
            onClick={onRetry}
          >
            <RefreshCw size={12} aria-hidden="true" />
            重试
          </button>
        ) : null}
      </div>

      {isPending && !data ? (
        <div className="mt-2 grid gap-2 sm:grid-cols-3" aria-hidden="true">
          {[0, 1, 2].map((item) => (
            <div
              key={item}
              className="h-[76px] animate-pulse rounded-control border border-line bg-surface"
            />
          ))}
        </div>
      ) : data ? (
        <>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            <Gauge
              label="CPU 使用率"
              value={cpu}
              tone={toneFor(cpu, 70, 90)}
              hint={
                resources?.available
                  ? `${resources.cpu_count ?? "—"} 逻辑核${
                      windowSeconds ? ` · 近 ${windowSeconds} 秒` : " · 采样中"
                    }`
                  : "psutil 未安装或采样失败"
              }
              icon={<Cpu size={12} aria-hidden="true" />}
            />
            <Gauge
              label="内存使用率"
              value={memory}
              tone={toneFor(memory, 70, 90)}
              hint={
                resources?.available
                  ? `${formatBytes(resources.memory_used_bytes)} / ${formatBytes(
                      resources.memory_total_bytes,
                    )}`
                  : "内存采样不可用"
              }
              icon={<MemoryStick size={12} aria-hidden="true" />}
            />
            <Gauge
              label="磁盘占用"
              value={diskTotal ? diskPercent : null}
              tone={toneFor(diskPercent, 90, 95)}
              hint={
                diskTotal
                  ? `${formatBytes(diskFree)} 可用${diskLow ? " · 剩余低于 10%" : ""}`
                  : "磁盘信息不可用"
              }
              icon={<HardDrive size={12} aria-hidden="true" />}
            />
          </div>
          <p className="mt-2 text-xs text-ink-3">
            服务已运行 {formatDuration(data.uptime_seconds)} · 进程内存{" "}
            {formatBytes(resources?.process_rss_bytes)} · 数据库{" "}
            {formatBytes(data.storage.db_bytes)}
            ；浏览器子进程不单独计入。
          </p>
        </>
      ) : null}
    </div>
  );
}
