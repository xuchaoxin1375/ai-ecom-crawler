import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Download,
  FileText,
  Pause,
  Play,
  RefreshCw,
  ShieldAlert,
  X,
} from "lucide-react";
import {
  cancelBuild,
  continueBuild,
  getBuild,
  getBuildConfig,
  getBuildMessages,
  pauseBuild,
  replyBuildDependency,
  replyBuildPermission,
  resumeBuild,
  buildTraceUrl,
  type BuildMessages,
  type BuildRepair,
  type BuildResponse,
  type BuildStatus,
} from "../../lib/api";
import {
  buildStateLabel,
  buildTone,
  buildOutcomeLabel,
  formatTime,
} from "../../lib/format";
import { buildIsActive, buildServiceBlockReason } from "../sites/site";
import {
  buildModeLabel,
  buildModelLabel,
  formatBytes,
  permissionItems,
} from "../sites/build";
import { BuildTimeline } from "../sites/BuildTimeline";
import { useBuildStream } from "../sites/useBuildStream";
import { RuleEvidence } from "../rules/RuleEvidence";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { Textarea } from "../../components/ui/Input";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { ConfirmBatchActionDialog } from "../batches/ConfirmBatchActionDialog";

const INTERRUPTED_CONTINUE_MESSAGE =
  "服务重启后继续：请先检查工作区和已有产物，从中断处完成剩余工作；不要重复已完成的抓取或覆盖已写好的规则。";

function siteHref(build: BuildStatus): string | null {
  if (!build.batch_id || !build.site_key) return null;
  return `/batches/${encodeURIComponent(build.batch_id)}/sites/${encodeURIComponent(
    build.site_key,
  )}`;
}

function newBuildRequest(prefix: string): string {
  const random =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${prefix}-${random}`;
}

function repairTime(repair: BuildRepair): string {
  const started = repair.started_at ? formatTime(repair.started_at) : "";
  const finished = repair.finished_at ? formatTime(repair.finished_at) : "";
  if (started && finished) return `${started} → ${finished}`;
  return started || finished || "时间未知";
}

function repairValidationSummary(repair: BuildRepair): string {
  const validation =
    repair.validation && typeof repair.validation === "object"
      ? (repair.validation as Record<string, unknown>)
      : null;
  if (!validation) return "";
  const parts: string[] = [];
  const valid = Number(validation.valid_products ?? 0);
  const failed = Number(validation.failed_products ?? 0);
  if (valid) parts.push(`有效 ${valid}`);
  if (failed) parts.push(`失败 ${failed}`);
  const detail = String(validation.stop_detail || "").trim();
  if (detail) parts.push(detail);
  return parts.join(" · ");
}

function RepairHistory({ repairs }: { repairs: BuildRepair[] }) {
  if (!repairs.length) {
    return (
      <p className="text-xs leading-5 text-ink-3">
        本次会话没有触发自动修复；主机验证失败后才会出现修复轮次。
      </p>
    );
  }
  return (
    <ol className="space-y-2">
      {[...repairs].reverse().map((repair, index) => {
        const resolved = Boolean(repair.resolved);
        const running = !repair.finished_at;
        const summary = repairValidationSummary(repair);
        return (
          <li
            key={`${repair.round}-${index}`}
            className="rounded-control border border-line bg-surface-muted px-3 py-2.5"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold text-ink">
                第 {repair.round} 轮
              </span>
              <Badge
                tone={running ? "warning" : resolved ? "success" : "neutral"}
                dot={false}
              >
                {running ? "进行中" : resolved ? "已解决" : "未解决"}
              </Badge>
              <span className="text-[11px] text-ink-3">{repairTime(repair)}</span>
            </div>
            {repair.error ? (
              <p className="mt-1 text-xs leading-5 text-ink-2">{repair.error}</p>
            ) : null}
            {summary ? (
              <p className="mt-1 font-mono text-[11px] leading-5 text-ink-3">
                {summary}
              </p>
            ) : null}
            {typeof repair.start_error === "string" && repair.start_error ? (
              <p className="mt-1 text-xs leading-5 text-danger">
                继续会话失败：{repair.start_error}
              </p>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}

export function BuildDetailPage() {
  const { buildId = "" } = useParams<{ buildId: string }>();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [confirmError, setConfirmError] = useState("");
  const [continueDraft, setContinueDraft] = useState("");
  const [continueBusy, setContinueBusy] = useState(false);

  const buildQuery = useQuery({
    queryKey: ["build", buildId],
    queryFn: ({ signal }) => getBuild(buildId, signal),
    enabled: Boolean(buildId),
    refetchInterval: (current) => {
      const data = current.state.data?.build;
      return data && buildIsActive(data) ? 2000 : false;
    },
  });
  const build: BuildStatus | null = buildQuery.data?.build ?? null;

  const configQuery = useQuery({
    queryKey: ["build-config"],
    queryFn: ({ signal }) => getBuildConfig(signal),
    staleTime: 60_000,
    retry: false,
  });
  const buildConfig = configQuery.data ?? null;
  const configBlockReason = buildServiceBlockReason(buildConfig, {
    loading: configQuery.isPending,
    error: configQuery.isError,
  });

  const stream = useBuildStream(
    buildId,
    Boolean(buildId && build && build.state !== "QUEUED"),
    build ? (buildIsActive(build) ? "active" : build.state) : "",
  );
  const streamHealthy = stream.connected || stream.ended;
  const messagesQuery = useQuery({
    queryKey: ["build-messages", buildId],
    queryFn: ({ signal }) => getBuildMessages(buildId, signal),
    enabled: Boolean(buildId),
    refetchInterval: streamHealthy
      ? false
      : build && build.state !== "QUEUED" && buildIsActive(build)
        ? 2000
        : false,
  });
  const messages: BuildMessages | null = stream.messages ?? messagesQuery.data ?? null;

  useEffect(() => {
    if (!build || buildIsActive(build)) return;
    void queryClient.invalidateQueries({ queryKey: ["builds"] });
  }, [build, queryClient]);

  function apply(response: BuildResponse) {
    queryClient.setQueryData(["build", response.build.build_id], response);
    void queryClient.invalidateQueries({
      queryKey: ["build-messages", response.build.build_id],
    });
    void queryClient.invalidateQueries({ queryKey: ["builds"] });
  }

  async function runControl(kind: "pause" | "resume" | "cancel") {
    if (!build) return;
    setBusy(kind);
    setError("");
    setConfirmError("");
    try {
      const response =
        kind === "pause"
          ? await pauseBuild(build.build_id)
          : kind === "resume"
            ? await resumeBuild(build.build_id)
            : await cancelBuild(build.build_id);
      apply(response);
      setConfirmCancel(false);
      setNotice(
        kind === "pause"
          ? "构建暂停请求已受理。"
          : kind === "resume"
            ? "构建继续请求已受理。"
            : "构建取消请求已受理。",
      );
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      if (kind === "cancel") setConfirmError(message);
      else setError(message);
    } finally {
      setBusy("");
    }
  }

  async function replyDependency(requestId: string, decision: "once" | "reject") {
    if (!build) return;
    setBusy(`dep-${requestId}`);
    setError("");
    try {
      apply(await replyBuildDependency(build.build_id, requestId, decision));
      setNotice("依赖请求已回复。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  async function replyPermission(
    requestId: string,
    decision: "once" | "always" | "reject",
  ) {
    if (!build) return;
    setBusy(`perm-${requestId}`);
    setError("");
    try {
      apply(await replyBuildPermission(build.build_id, requestId, decision));
      setNotice("权限请求已回复。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  async function runContinue() {
    if (!build) return;
    const message =
      continueDraft.trim() ||
      (build.outcome === "interrupted" ? INTERRUPTED_CONTINUE_MESSAGE : "");
    if (!message) {
      setError("继续会话需要一条具体指令。");
      return;
    }
    setContinueBusy(true);
    setError("");
    try {
      const response = await continueBuild(build.build_id, {
        request_id: newBuildRequest("build-continue"),
        message,
      });
      apply(response);
      setContinueDraft("");
      setNotice(
        build.outcome === "interrupted"
          ? "已继续中断会话；后台会重新加载同一会话，模型响应和主机验证会写回本次构建。"
          : "已继续失败会话；模型响应和主机验证会写回本次构建。",
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setContinueBusy(false);
    }
  }

  const active = build ? buildIsActive(build) : false;
  const queued = build?.state === "QUEUED";
  const interrupted = build?.outcome === "interrupted";
  const canContinue =
    build?.state === "FINISHED" &&
    (build.outcome === "failed" || build.outcome === "interrupted");
  const continuations = build?.continuations ?? [];
  const continueDisabled = continueBusy || Boolean(configBlockReason);
  const canPause = build?.state === "RUNNING";
  const canResume = build?.state === "PAUSED";
  const permissions = permissionItems(build);
  const dependencyDetails = new Map(
    (build?.pending_dependency_requests ?? []).map((item) => [item.request_id, item]),
  );
  const dependencyInstallerConfigured =
    build?.dependency_installer_configured !== false;
  const href = build ? siteHref(build) : null;
  const hasEvidence =
    Array.isArray(build?.change_summary?.changed_fields) ||
    build?.validation?.status === "PASSED" ||
    build?.validation?.status === "FAILED";

  if (buildQuery.isError) {
    return (
      <div className="space-y-4">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to="/builds"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          返回构建记录
        </Link>
        <ErrorNotice
          title="读取构建失败"
          message={
            buildQuery.error instanceof Error
              ? buildQuery.error.message
              : String(buildQuery.error)
          }
        />
      </div>
    );
  }

  if (!build) {
    return (
      <div className="space-y-4" role="status">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to="/builds"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          返回构建记录
        </Link>
        <p className="text-sm text-ink-3">正在读取构建 {buildId}…</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <header className="rounded-panel border border-line bg-surface px-4 py-5 sm:px-6">
        <div className="flex items-center justify-between gap-4">
          <Link
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
            to="/builds"
          >
            <ArrowLeft size={15} aria-hidden="true" />
            返回构建记录
          </Link>
          <span className="min-w-0 truncate font-mono text-[11px] text-ink-3">
            {build.build_id}
          </span>
        </div>

        <div className="mt-4 flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[24px] leading-8 font-semibold tracking-[-0.02em] text-ink sm:text-[28px] sm:leading-9">
                {build.site_key || "未关联站点"}
              </h1>
              <Badge tone="neutral" dot={false}>
                {buildModeLabel(build.mode)}
              </Badge>
              <Badge tone={buildTone(build.state, build.outcome)} dot={false}>
                {buildStateLabel(build.state)}
              </Badge>
              {build.outcome ? (
                <Badge tone={buildTone(null, build.outcome)} dot={false}>
                  {buildOutcomeLabel(build.outcome)}
                </Badge>
              ) : null}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-3">
              {href ? (
                <Link className="hover:text-accent hover:underline" to={href}>
                  站点详情
                </Link>
              ) : null}
              {build.batch_id ? (
                <Link
                  className="hover:text-accent hover:underline"
                  to={`/batches/${encodeURIComponent(build.batch_id)}`}
                >
                  批次 {build.batch_id}
                </Link>
              ) : null}
              <span>更新 {formatTime(build.updated_at)}</span>
              {queued && build.queue_position ? (
                <span className="font-medium text-ink-2">
                  队列第 {build.queue_position} 位
                </span>
              ) : null}
              {build.rule ? (
                <span className="font-mono">
                  {build.rule.rule_id}@{build.rule.rule_version}
                </span>
              ) : null}
            </div>
          </div>

          <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto lg:shrink-0 lg:justify-end">
            {canPause ? (
              <Button
                size="sm"
                onClick={() => void runControl("pause")}
                disabled={Boolean(busy)}
              >
                <Pause size={13} aria-hidden="true" />
                暂停
              </Button>
            ) : null}
            {canResume ? (
              <Button
                size="sm"
                variant="primary"
                onClick={() => void runControl("resume")}
                disabled={Boolean(busy)}
              >
                <Play size={13} aria-hidden="true" />
                继续
              </Button>
            ) : null}
            {active ? (
              <Button
                size="sm"
                variant="danger"
                onClick={() => {
                  setConfirmError("");
                  setConfirmCancel(true);
                }}
                disabled={Boolean(busy)}
              >
                <X size={13} aria-hidden="true" />
                {queued ? "取消排队" : "取消构建"}
              </Button>
            ) : null}
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                void buildQuery.refetch();
                void messagesQuery.refetch();
              }}
              disabled={buildQuery.isFetching || messagesQuery.isFetching}
            >
              <RefreshCw
                className={
                  buildQuery.isFetching || messagesQuery.isFetching
                    ? "animate-spin"
                    : undefined
                }
                size={13}
                aria-hidden="true"
              />
              刷新
            </Button>
          </div>
        </div>
      </header>

      {notice ? (
        <InlineNotice tone="success" onDismiss={() => setNotice("")}>
          {notice}
        </InlineNotice>
      ) : null}
      {error ? <ErrorNotice title="构建操作失败" message={error} compact /> : null}
      {build.error ? (
        <ErrorNotice
          title={interrupted ? "构建已中断" : "构建错误"}
          message={build.error}
          tone={interrupted ? "warning" : "danger"}
          compact
        />
      ) : null}

      {build.pending_dependencies.length || permissions.length ? (
        <section
          aria-label="构建等待审批"
          className="rounded-panel border border-warning/25 bg-warning-soft px-5 py-4"
        >
          <h2 className="flex items-center gap-1.5 text-[15px] leading-6 font-semibold text-warning">
            <ShieldAlert size={15} aria-hidden="true" />
            构建等待审批
          </h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-2">
            构建会话在等待你的决定；批准后会继续执行，拒绝会按拒绝结果继续或结束。处理结果会写回本次构建记录。
          </p>
          <div className="mt-3 space-y-2">
            {build.pending_dependencies.map((requestId) => {
              const detail = dependencyDetails.get(requestId);
              return (
                <div
                  key={requestId}
                  className="flex flex-wrap items-center gap-2 rounded-control border border-warning/20 bg-surface px-3 py-2 text-xs"
                >
                  <span className="font-medium text-ink">
                    {detail?.package ? `依赖 ${detail.package}` : "依赖安装"}
                  </span>
                  {detail?.version ? (
                    <code className="font-mono text-[11px] text-ink-2">
                      @{detail.version}
                    </code>
                  ) : null}
                  <span className="text-ink-3">
                    {detail?.manager
                      ? `${detail.manager} · ${detail.scope ?? "build"}`
                      : requestId}
                  </span>
                  {detail?.reason ? (
                    <p className="w-full text-[11px] leading-5 text-ink-3">
                      {detail.reason}
                    </p>
                  ) : null}
                  {!dependencyInstallerConfigured ? (
                    <p className="w-full text-[11px] leading-5 text-warning">
                      当前服务未配置依赖安装器；请操作者手工安装，批准不会执行安装。
                    </p>
                  ) : null}
                  <div className="ml-auto flex gap-1.5">
                    <Button
                      size="sm"
                      disabled={Boolean(busy) || !dependencyInstallerConfigured}
                      onClick={() => void replyDependency(requestId, "once")}
                    >
                      批准一次
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={Boolean(busy)}
                      onClick={() => void replyDependency(requestId, "reject")}
                    >
                      拒绝
                    </Button>
                  </div>
                </div>
              );
            })}
            {permissions.map((request) => {
              const requestId = String(request.id);
              return (
                <div
                  key={requestId}
                  className="flex flex-wrap items-center gap-2 rounded-control border border-warning/20 bg-surface px-3 py-2 text-xs"
                >
                  <span className="font-medium text-ink">权限请求</span>
                  <code className="font-mono text-[11px] text-ink-2">
                    {String(request.action || "permission")}
                  </code>
                  {request.resource ? (
                    <span className="truncate text-ink-3">
                      {String(request.resource)}
                    </span>
                  ) : null}
                  <div className="ml-auto flex gap-1.5">
                    <Button
                      size="sm"
                      disabled={Boolean(busy)}
                      onClick={() => void replyPermission(requestId, "once")}
                    >
                      允许一次
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={Boolean(busy)}
                      onClick={() => void replyPermission(requestId, "reject")}
                    >
                      拒绝
                    </Button>
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      ) : null}

      <MetricStrip
        label="构建概览"
        items={[
          {
            label: "自动修复",
            value: build.repair_round
              ? `${build.repair_round}/${build.repair_limit}`
              : "0",
            hint: build.repairs.some((item) => item.resolved)
              ? "至少一轮已解决"
              : build.repair_round
                ? "自动轮次未解决"
                : "主机验证失败才触发",
          },
          {
            label: "耗时",
            value:
              build.elapsed_seconds !== null
                ? `${Math.round(build.elapsed_seconds)} 秒`
                : "—",
            hint: build.finished_at
              ? `结束于 ${formatTime(build.finished_at)}`
              : "尚未结束",
          },
          {
            label: "规则",
            value: build.rule ? build.rule.rule_version : "—",
            hint: build.rule ? build.rule.rule_id : "尚未安装",
          },
          {
            label: "样例存档",
            value: build.archive_stats ? `${build.archive_stats.pages} 页` : "—",
            hint: build.archive_stats
              ? formatBytes(build.archive_stats.bytes)
              : "本次未存档",
          },
        ]}
      />

      <section className="rounded-panel border border-line bg-surface">
        <div className="flex flex-col items-start gap-3 border-b border-line px-4 py-4 sm:flex-row sm:justify-between sm:px-5">
          <div>
            <h2 className="text-[17px] leading-6 font-semibold text-ink">构建事实</h2>
            <p className="mt-0.5 text-xs text-ink-3">
              模型、出口、工作区和会话信息；不包含规则正文。
            </p>
          </div>
          {build.trace_available ? (
            <div className="flex flex-wrap gap-2">
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
        </div>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-4 sm:grid-cols-4 sm:px-5">
          <div>
            <dt className="text-[11px] text-ink-3">模型</dt>
            <dd className="mt-0.5 text-xs leading-5 text-ink">
              {buildModelLabel(build) || "—"}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-3">出口</dt>
            <dd className="mt-0.5 text-xs leading-5 text-ink">
              {build.proxy ? build.proxy : "服务默认／直连"}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-3">开始</dt>
            <dd className="mt-0.5 text-xs leading-5 text-ink">
              {build.started_at ? formatTime(build.started_at) : "—"}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-3">会话</dt>
            <dd className="mt-0.5 truncate font-mono text-xs leading-5 text-ink">
              {build.session_id || "—"}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-3">来源规则</dt>
            <dd className="mt-0.5 text-xs leading-5 text-ink">
              {build.source_rule?.rule_version || "—"}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-3">目标规则</dt>
            <dd className="mt-0.5 text-xs leading-5 text-ink">
              {build.candidate_rule?.rule_version || build.rule?.rule_version || "—"}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-3">思考</dt>
            <dd className="mt-0.5 text-xs leading-5 text-ink">
              {!build.reasoning_capture_enabled
                ? "服务端未开启"
                : build.reasoning_retained
                  ? "实时 + trace"
                  : build.reasoning_live
                    ? "实时，不写 trace"
                    : build.state === "FINISHED" || build.state === "CANCELLED"
                      ? "已结束，未写入 trace"
                      : "已开启，等待输出"}
            </dd>
          </div>
          <div>
            <dt className="text-[11px] text-ink-3">档案</dt>
            <dd className="mt-0.5 text-xs leading-5 text-ink">
              {build.catalog?.catalog_scope === "full"
                ? `全量目标 ${build.catalog.catalog_products ?? "—"}`
                : "样例验证"}
            </dd>
          </div>
        </dl>
        <div className="border-t border-line px-5 py-4">
          <p className="mb-1.5 text-[11px] text-ink-3">主机变更与验证</p>
          {hasEvidence ? (
            <RuleEvidence change={build.change_summary} validation={build.validation} />
          ) : (
            <p className="text-xs leading-5 text-ink-3">
              该构建没有记录主机验证摘要。旧构建、取消或未进入候选安装的会话不会伪造验证结果。
            </p>
          )}
        </div>
      </section>

      <section className="rounded-panel border border-line bg-surface">
        <div className="border-b border-line px-5 py-4">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">自动修复轮次</h2>
          <p className="mt-0.5 text-xs text-ink-3">
            每轮由主机验证失败触发，使用同一构建会话继续；轮次上限由服务配置。
          </p>
        </div>
        <div className="px-5 py-4">
          <RepairHistory repairs={build.repairs} />
        </div>
      </section>

      {canContinue || continuations.length ? (
        <section className="rounded-panel border border-line bg-surface">
          <div className="border-b border-line px-5 py-4">
            <h2 className="text-[17px] leading-6 font-semibold text-ink">
              继续构建会话
            </h2>
            <p className="mt-0.5 text-xs leading-5 text-ink-3">
              {interrupted
                ? "服务重启中断了本次构建，会话和工作区已保留。继续会重新加载同一会话，从中断处完成剩余工作。"
                : "失败的构建可以继续，且要求会话仍可恢复；成功构建请通过结果反馈走规则修复。"}
            </p>
          </div>
          <div className="space-y-3 px-5 py-4">
            {canContinue ? (
              <>
                <label className="flex flex-col gap-1" htmlFor="build-continue">
                  <span className="text-xs font-medium text-ink-3">
                    给构建 Agent 的指令
                  </span>
                  <Textarea
                    id="build-continue"
                    rows={3}
                    maxLength={4000}
                    value={continueDraft}
                    placeholder={
                      interrupted
                        ? "留空会发送默认指令：检查工作区已有产物，从中断处继续，不重复已完成部分。"
                        : "例如：上次失败在 discovery.sources，请检查列表入口并重新生成规则；保留已确认的选择器。"
                    }
                    onChange={(event) => setContinueDraft(event.target.value)}
                    disabled={continueDisabled}
                  />
                </label>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="max-w-2xl text-[11px] leading-5 text-ink-3">
                    发送会继续调用模型并产生费用；主机只接受失败或中断构建的会话，不会创建新的构建记录。
                  </p>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[11px] text-ink-3">
                      {continueDraft.length}/4000
                    </span>
                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => void runContinue()}
                      disabled={
                        continueDisabled || (!continueDraft.trim() && !interrupted)
                      }
                    >
                      {continueBusy ? "发送中…" : "发送并继续"}
                    </Button>
                  </div>
                </div>
                {configBlockReason ? (
                  <div className="flex flex-wrap items-center gap-2 rounded-control border border-warning/25 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning">
                    <p>{configBlockReason}</p>
                    {configQuery.isError ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void configQuery.refetch()}
                      >
                        重试读取配置
                      </Button>
                    ) : null}
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-xs leading-5 text-ink-3">
                本次构建已经继续过，当前状态为 {buildStateLabel(build.state)}。
              </p>
            )}
            {continuations.length ? (
              <div>
                <p className="text-[11px] text-ink-3">继续记录</p>
                <ul className="mt-1 space-y-1">
                  {continuations.map((item) => (
                    <li
                      key={item.request_id}
                      className="flex flex-wrap items-center gap-2 rounded-control border border-line bg-surface-muted px-3 py-2 text-xs text-ink-2"
                    >
                      <Badge
                        tone={item.state === "FAILED" ? "danger" : "neutral"}
                        dot={false}
                      >
                        {item.state === "FAILED" ? "失败" : "已受理"}
                      </Badge>
                      <span>{formatTime(item.created_at)}</span>
                      <span className="text-ink-3">{item.message_chars} 字</span>
                      <span className="font-mono text-[10px] text-ink-3">
                        {item.request_id}
                      </span>
                      {item.error ? (
                        <span className="basis-full text-danger">{item.error}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        </section>
      ) : null}

      <BuildTimeline
        build={build}
        messages={messages}
        live={active && !queued}
        connected={stream.connected}
        streamError={stream.error}
        ended={stream.ended}
      />

      <ConfirmBatchActionDialog
        open={confirmCancel}
        title={queued ? "取消这次排队？" : "取消这次构建？"}
        description={
          queued
            ? `构建 ${build.build_id} 还在排队，取消后不会启动模型会话。`
            : `构建 ${build.build_id} 会停止；已产生的会话记录和输出保留。`
        }
        consequence={
          build.mode === "repair"
            ? "取消后原规则继续生效，已有采集数据不变。"
            : "取消后站点回到待接入；可重新发起构建。"
        }
        confirmLabel={queued ? "确认取消排队" : "确认取消构建"}
        tone="danger"
        busy={busy === "cancel"}
        error={confirmError}
        onOpenChange={setConfirmCancel}
        onConfirm={() => void runControl("cancel")}
      />
    </div>
  );
}
