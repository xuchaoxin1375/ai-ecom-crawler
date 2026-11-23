import type { ReactNode } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Download,
  FileText,
  RefreshCw,
  RotateCcw,
  ShieldAlert,
  Wrench,
} from "lucide-react";
import {
  buildTraceUrl,
  type BatchSite,
  type BuildConfig,
  type BuildMessages,
  type BuildStatus,
} from "../../lib/api";
import {
  buildOutcomeLabel,
  buildStateLabel,
  buildStateTone,
  formatTime,
} from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Checkbox } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import {
  activeRepair,
  buildEventText,
  buildEventTone,
  buildModelLabel,
  buildOutputText,
  buildReasoningText,
  formatBytes,
  formatTimelineValue,
  permissionItems,
  reasoningSummary,
  timelineTime,
  toolStatusLabel,
  toolStatusTone,
  visibleBuildEvents,
} from "./build";
import { buildIsActive, taskIsActive } from "./site";

interface BuildPanelProps {
  site: BatchSite;
  build: BuildStatus | null;
  messages: BuildMessages | null;
  config: BuildConfig | null;
  detailMode: boolean;
  busy: string;
  error: string;
  refreshing: boolean;
  onToggleDetail: (next: boolean) => void;
  onOpenStart: (mode: "build" | "repair") => void;
  onReplyDependency: (requestId: string, decision: "once" | "reject") => void;
  onReplyPermission: (
    requestId: string,
    decision: "once" | "always" | "reject",
  ) => void;
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
  config,
  detailMode,
  busy,
  error,
  refreshing,
  onToggleDetail,
  onOpenStart,
  onReplyDependency,
  onReplyPermission,
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
  const permissions = permissionItems(build);
  const repair = activeRepair(build);
  const outputText = buildOutputText(messages);
  const reasoningText = buildReasoningText(messages);
  const timeline = messages?.timeline || [];

  if (!build && !canStartBuild && !canRepair) return null;

  const title = build?.mode === "repair" ? "规则修复与重新验证" : "方案构建与规则维护";

  return (
    <section
      className="rounded-panel border border-line bg-surface"
      aria-label="方案构建与规则维护"
    >
      <div className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
        <div className="min-w-0">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">{title}</h2>
          <p className="mt-1 max-w-3xl text-xs leading-5 text-ink-3">
            {site.readiness === "ready"
              ? `当前规则 ${site.rule?.rule_id ?? ""}@${
                  site.rule?.rule_version ?? ""
                }。可对已安装规则重新验证并修复描述块、规格和缺失字段；不删除已有采集数据。`
              : "新站由构建 Agent 生成候选规则；主机完成有界验证后站点才变为可采。构建会话与采集任务分开，默认只运行一个构建。"}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center justify-end gap-2">
          {canRepair ? (
            <Button
              size="sm"
              variant="primary"
              disabled={Boolean(busy)}
              onClick={() => onOpenStart("repair")}
            >
              <Wrench size={13} aria-hidden="true" />
              修复规则
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
            <Badge
              tone={build.outcome === "failed" ? "danger" : buildStateTone(build.state)}
            >
              {buildStateLabel(build.state)}
            </Badge>
            {build.outcome ? (
              <Badge
                tone={
                  build.outcome === "succeeded"
                    ? "success"
                    : build.outcome === "failed"
                      ? "danger"
                      : "neutral"
                }
                dot={false}
              >
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

          <dl className="grid grid-cols-4 gap-x-4 gap-y-3 rounded-panel border border-line bg-surface-muted px-4 py-3">
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
              {build.reasoning_retained
                ? "已保留"
                : build.reasoning_capture_enabled
                  ? "未保留"
                  : "服务端未开启"}
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
            <ErrorNotice title="构建错误" message={build.error} compact />
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

          {build.pending_dependencies.length ? (
            <div className="space-y-2 rounded-control border border-warning/25 bg-warning-soft px-3 py-2">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-warning">
                <ShieldAlert size={14} aria-hidden="true" />
                依赖审批
              </p>
              {build.pending_dependencies.map((requestId) => (
                <div
                  key={requestId}
                  className="flex flex-wrap items-center gap-2 text-xs"
                >
                  <code className="font-mono text-[11px]">{requestId}</code>
                  <Button
                    size="sm"
                    disabled={Boolean(busy)}
                    onClick={() => onReplyDependency(requestId, "once")}
                  >
                    批准
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={Boolean(busy)}
                    onClick={() => onReplyDependency(requestId, "reject")}
                  >
                    拒绝
                  </Button>
                </div>
              ))}
            </div>
          ) : null}

          {permissions.length ? (
            <div className="space-y-2 rounded-control border border-warning/25 bg-warning-soft px-3 py-2">
              <p className="flex items-center gap-1.5 text-sm font-semibold text-warning">
                <ShieldAlert size={14} aria-hidden="true" />
                权限请求
              </p>
              {permissions.map((request) => (
                <div
                  key={String(request.id)}
                  className="flex flex-wrap items-center gap-2 text-xs"
                >
                  <code className="font-mono text-[11px]">
                    {String(request.action || "permission")}
                  </code>
                  {request.resources ? (
                    <span className="text-ink-3">
                      {Array.isArray(request.resources)
                        ? request.resources.join("、")
                        : String(request.resources)}
                    </span>
                  ) : null}
                  <Button
                    size="sm"
                    disabled={Boolean(busy)}
                    onClick={() => onReplyPermission(String(request.id), "once")}
                  >
                    允许一次
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={Boolean(busy)}
                    onClick={() => onReplyPermission(String(request.id), "reject")}
                  >
                    拒绝
                  </Button>
                </div>
              ))}
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

          <div className="border-t border-line pt-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-[15px] leading-6 font-semibold text-ink">
                  模型输出
                </h3>
                <p className="text-xs text-ink-3">
                  {messages?.live ? "流式输出，随轮询追加" : "阶段性输出"}
                  {messages?.timeline_truncated ? "；时间线只显示最近 200 条" : ""}
                </p>
              </div>
              <label
                className="flex items-center gap-2 text-xs text-ink-2"
                htmlFor="build-detail-mode"
              >
                <Checkbox
                  id="build-detail-mode"
                  checked={detailMode}
                  onChange={(event) => onToggleDetail(event.target.checked)}
                />
                详细模式
              </label>
            </div>

            {detailMode ? (
              <div className="mt-3 space-y-2">
                {!messages?.reasoning_retained ? (
                  <p className="text-xs leading-5 text-ink-3">
                    本次构建未保留思考过程；构建前勾选“保留思考过程”且服务端开启
                    <code className="mx-1 rounded bg-surface-muted px-1 font-mono text-[11px]">
                      ECOM_BUILD_CAPTURE_REASONING=1
                    </code>
                    才会显示。
                  </p>
                ) : null}
                {timeline.length ? (
                  timeline.map((item, index) => (
                    <details
                      key={`${item.kind}-${index}-${item.created_at || ""}`}
                      className="group rounded-control border border-line bg-surface-muted"
                    >
                      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs text-ink-2 [&::-webkit-details-marker]:hidden">
                        <ChevronDown
                          className="shrink-0 text-ink-3 transition-transform group-open:rotate-180"
                          size={13}
                          aria-hidden="true"
                        />
                        {item.kind === "reasoning" ? (
                          <span>{reasoningSummary(item)}</span>
                        ) : item.kind === "tool" ? (
                          <>
                            <span className="font-medium text-ink">
                              工具 {item.name || "unknown"}
                            </span>
                            <Badge tone={toolStatusTone(item.status)} dot={false}>
                              {toolStatusLabel(item.status)}
                            </Badge>
                            <span className="text-ink-3">{timelineTime(item)}</span>
                            {item.duration_ms != null ? (
                              <span className="text-ink-3">{item.duration_ms} ms</span>
                            ) : null}
                          </>
                        ) : (
                          <>
                            <Badge tone="neutral" dot={false}>
                              {item.role === "user" ? "用户" : "模型"}
                            </Badge>
                            <span className="text-ink-3">{timelineTime(item)}</span>
                          </>
                        )}
                      </summary>
                      <div className="border-t border-line px-3 py-2">
                        {item.kind === "tool" ? (
                          <>
                            {formatTimelineValue(item.input) ? (
                              <div className="mb-2">
                                <p className="mb-1 text-[11px] text-ink-3">入参</p>
                                <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-surface p-2 font-mono text-[11px] leading-5 text-ink-2">
                                  {formatTimelineValue(item.input)}
                                </pre>
                              </div>
                            ) : null}
                            {item.output ? (
                              <div>
                                <p className="mb-1 text-[11px] text-ink-3">输出</p>
                                <pre className="max-h-56 overflow-auto whitespace-pre-wrap rounded bg-surface p-2 font-mono text-[11px] leading-5 text-ink-2">
                                  {item.output}
                                </pre>
                              </div>
                            ) : null}
                            {!formatTimelineValue(item.input) && !item.output ? (
                              <p className="text-xs text-ink-3">
                                工具完成后可在 trace 查看输出。
                              </p>
                            ) : null}
                          </>
                        ) : (
                          <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded bg-surface p-2 font-sans text-xs leading-5 text-ink-2">
                            {item.text}
                          </pre>
                        )}
                      </div>
                    </details>
                  ))
                ) : (
                  <p className="text-xs text-ink-3">还没有可见模型输出。</p>
                )}
              </div>
            ) : (
              <div className="mt-3 space-y-2">
                {outputText ? (
                  <pre className="max-h-72 overflow-auto whitespace-pre-wrap rounded-control border border-line bg-surface-muted p-3 font-sans text-xs leading-5 text-ink-2">
                    {outputText}
                  </pre>
                ) : (
                  <p className="text-xs text-ink-3">还没有可见模型输出。</p>
                )}
                {reasoningText ? (
                  <details className="rounded-control border border-line bg-surface-muted">
                    <summary className="cursor-pointer px-3 py-2 text-xs text-ink-2">
                      思考过程（已保留，仅本地复盘）
                    </summary>
                    <pre className="max-h-72 overflow-auto whitespace-pre-wrap border-t border-line p-3 font-sans text-xs leading-5 text-ink-2">
                      {reasoningText}
                    </pre>
                  </details>
                ) : null}
              </div>
            )}
          </div>

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
          {config && !config.available ? (
            <p className="text-xs text-warning">
              服务端未配置构建 Agent；启动构建会返回不可用。
            </p>
          ) : null}
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
