import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  CheckCircle2,
  Download,
  FileText,
  RefreshCw,
  RotateCcw,
  Wrench,
} from "lucide-react";
import {
  buildTraceUrl,
  type BatchSite,
  type BuildMessages,
  type BuildStatus,
} from "../../lib/api";
import {
  buildOutcomeLabel,
  buildStateLabel,
  buildTone,
  formatTime,
} from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import {
  activeRepair,
  buildEventText,
  buildEventTone,
  buildModelLabel,
  formatBytes,
  visibleBuildEvents,
} from "./build";
import { BuildTimeline } from "./BuildTimeline";
import { buildIsActive, taskIsActive } from "./site";

interface BuildPanelProps {
  site: BatchSite;
  build: BuildStatus | null;
  messages: BuildMessages | null;
  busy: string;
  error: string;
  refreshing: boolean;
  streamConnected: boolean;
  streamError: string;
  streamEnded: boolean;
  blockedReason?: string | null;
  onRetryConfig?: () => void;
  onOpenStart: (mode: "build" | "repair") => void;
  onRefresh: () => void;
}

function MetaItem({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[11px] text-ink-3">{label}</dt>
      <dd className="mt-0.5 truncate text-xs text-ink-2">{children}</dd>
    </div>
  );
}

export function BuildPanel({
  site,
  build,
  messages,
  busy,
  error,
  refreshing,
  streamConnected,
  streamError,
  streamEnded,
  blockedReason = null,
  onRetryConfig,
  onOpenStart,
  onRefresh,
}: BuildPanelProps) {
  const active = buildIsActive(build);
  const taskActive = taskIsActive(site.task);
  const canStartBuild =
    !active &&
    !site.task &&
    (site.readiness === "needs_onboarding" || site.readiness === "building");
  const canRepair =
    !active && !taskActive && site.readiness === "ready" && Boolean(site.rule);
  const events = visibleBuildEvents(build);
  const repair = activeRepair(build);

  if (!build && !canStartBuild && !canRepair) return null;

  const title = build?.mode === "repair" ? "规则修复与重新验证" : "方案构建与规则维护";

  return (
    <section
      className="rounded-panel border border-line bg-surface"
      aria-label="方案构建与规则维护"
    >
      <div className="flex flex-col items-start gap-3 border-b border-line px-4 py-4 sm:flex-row sm:justify-between sm:px-5">
        <div className="min-w-0">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">{title}</h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-ink-3">
            {site.readiness === "ready"
              ? `当前规则 ${site.rule?.rule_id ?? ""}@${
                  site.rule?.rule_version ?? ""
                }。可对已安装规则重新验证并修复描述块、规格和缺失字段；不删除已有采集数据。`
              : "新站由构建 Agent 生成候选规则；主机完成有界验证后站点才变为可采。构建会话与采集任务分开，默认只运行一个构建。"}
          </p>
          {blockedReason ? (
            <div className="mt-1 flex flex-wrap items-center gap-2">
              <p className="text-xs leading-5 text-warning">{blockedReason}</p>
              {onRetryConfig ? (
                <Button size="sm" variant="ghost" onClick={onRetryConfig}>
                  重试读取配置
                </Button>
              ) : null}
            </div>
          ) : null}
        </div>
        <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:shrink-0 sm:justify-end">
          {canRepair ? (
            <Button
              size="sm"
              variant="primary"
              disabled={Boolean(busy) || Boolean(blockedReason)}
              title={blockedReason ?? undefined}
              onClick={() => onOpenStart("repair")}
            >
              <Wrench size={13} aria-hidden="true" />
              修复规则
            </Button>
          ) : null}
          {build ? (
            <Button asChild size="sm">
              <Link to={`/builds/${encodeURIComponent(build.build_id)}`}>构建详情</Link>
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" onClick={onRefresh} disabled={refreshing}>
            <RefreshCw
              className={refreshing ? "animate-spin" : undefined}
              size={13}
              aria-hidden="true"
            />
            刷新
          </Button>
        </div>
      </div>

      {build ? (
        <div className="space-y-4 px-5 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={buildTone(build.state, build.outcome)}>
              {buildStateLabel(build.state)}
            </Badge>
            {build.outcome ? (
              <Badge tone={buildTone(null, build.outcome)} dot={false}>
                {buildOutcomeLabel(build.outcome)}
              </Badge>
            ) : null}
            <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[11px] text-ink-2">
              {build.build_id}
            </code>
            {build.repair_round ? (
              <Badge
                tone={
                  build.repairs.some((item) => item.resolved) ? "success" : "neutral"
                }
                dot={false}
              >
                自动修复 {build.repair_round}/{build.repair_limit}
              </Badge>
            ) : null}
          </div>

          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 rounded-panel border border-line bg-surface-muted px-4 py-3 sm:grid-cols-4">
            <MetaItem label="模型">{buildModelLabel(build) || "—"}</MetaItem>
            <MetaItem label="出口">
              {build.proxy ? build.proxy : "服务默认／直连"}
            </MetaItem>
            <MetaItem label="耗时">
              {build.elapsed_seconds !== null
                ? `${Math.round(build.elapsed_seconds)} 秒`
                : "—"}
            </MetaItem>
            <MetaItem label="更新">{formatTime(build.updated_at)}</MetaItem>
            <MetaItem label="规则">
              {build.rule ? `${build.rule.rule_id}@${build.rule.rule_version}` : "—"}
            </MetaItem>
            <MetaItem label="目录">
              {build.catalog?.catalog_scope === "full"
                ? `全量目标 ${build.catalog.catalog_products ?? "—"}`
                : "样例"}
            </MetaItem>
            <MetaItem label="样例存档">
              {build.archive_stats
                ? `${build.archive_stats.pages} 页 / ${formatBytes(
                    build.archive_stats.bytes,
                  )}`
                : "—"}
            </MetaItem>
            <MetaItem label="思考">
              {!build.reasoning_capture_enabled
                ? "服务端未开启"
                : build.reasoning_retained
                  ? "实时 + trace"
                  : build.reasoning_live
                    ? "实时，不写 trace"
                    : "已开启，等待输出"}
            </MetaItem>
          </dl>

          {build.trace_available ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button asChild size="sm">
                <a href={buildTraceUrl(build.build_id, "md")} download>
                  <FileText size={13} aria-hidden="true" />
                  下载构建过程
                </a>
              </Button>
              <Button asChild size="sm">
                <a href={buildTraceUrl(build.build_id, "json")} download>
                  <Download size={13} aria-hidden="true" />
                  trace.json
                </a>
              </Button>
            </div>
          ) : null}

          {build.error ? (
            <ErrorNotice
              title={build.outcome === "interrupted" ? "构建已中断" : "构建错误"}
              message={build.error}
              tone={build.outcome === "interrupted" ? "warning" : "danger"}
              compact
            />
          ) : null}

          {build.outcome === "interrupted" ? (
            <p className="rounded-control border border-warning/25 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning">
              会话和工作区已保留；打开构建详情可以继续同一会话，或重新构建。
            </p>
          ) : null}

          {repair ? (
            <div className="rounded-control border border-warning/25 bg-warning-soft px-3 py-2">
              <p className="text-sm font-semibold text-warning">
                自动修复第 {repair.round}/{build.repair_limit} 轮
              </p>
              <p className="mt-1 text-xs leading-5 text-ink-2">
                上次验证失败：{repair.error}
              </p>
            </div>
          ) : null}

          {events.length ? (
            <ol className="space-y-1.5" aria-label="构建事件">
              {events.map((event, index) => (
                <li
                  key={`${event.created_at}-${index}`}
                  className="flex items-center gap-2 text-xs"
                >
                  <Badge tone={buildEventTone(event)} dot={false}>
                    {buildEventText(event)}
                  </Badge>
                  <span className="text-ink-3">{formatTime(event.created_at)}</span>
                </li>
              ))}
            </ol>
          ) : null}

          <BuildTimeline
            build={build}
            messages={messages}
            live={active}
            connected={streamConnected}
            streamError={streamError}
            ended={streamEnded}
          />

          {build.state === "FINISHED" && build.outcome === "succeeded" ? (
            <p className="flex items-start gap-2 rounded-control border border-success/25 bg-success-soft px-3 py-2 text-xs leading-5 text-success">
              <CheckCircle2 className="mt-0.5 shrink-0" size={14} aria-hidden="true" />
              构建完成，候选规则已安装。回到批次详情启动可采站点即可创建采集任务。
            </p>
          ) : build.state === "VALIDATING" ? (
            <p className="text-xs leading-5 text-ink-3">
              模型已结束，主机正在做有界验证和规则安装；此时站点还不能启动。
            </p>
          ) : build.state === "CANCELLED" ? (
            <p className="flex items-start gap-2 text-xs leading-5 text-ink-3">
              <RotateCcw className="mt-0.5 shrink-0" size={13} aria-hidden="true" />
              构建已取消，站点回到待接入；可以重新开始构建。
            </p>
          ) : null}
        </div>
      ) : (
        <div className="space-y-2 px-5 py-4">
          <p className="text-xs leading-5 text-ink-3">
            {site.readiness === "ready"
              ? "当前没有修复记录。点击“修复规则”会把已安装规则和样例页交给构建 Agent，只做定向修复并重新验证；失败保留原规则和已有采集数据。"
              : "当前没有构建记录。开始构建会调用模型分析站点并生成规则，产生模型费用；构建完成后自动做一次有界验证，通过后站点变为可采。"}
          </p>
        </div>
      )}

      {error ? (
        <div className="border-t border-line px-5 py-3">
          <ErrorNotice title="构建操作失败" message={error} compact />
        </div>
      ) : null}
    </section>
  );
}
