import { useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Download,
  ExternalLink,
  FileText,
  MoreHorizontal,
  Pause,
  Play,
  RefreshCw,
  ShieldAlert,
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
  formatNumber,
  formatTime,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import { readListReturn } from "../../lib/listReturn";
import { buildIsActive, buildServiceBlockReason } from "../sites/site";
import {
  buildEventText,
  buildEventTone,
  buildModeLabel,
  buildModelLabel,
  formatBytes,
  permissionItems,
  visibleBuildEvents,
} from "../sites/build";
import { BuildTimeline } from "../sites/BuildTimeline";
import { useBuildStream } from "../sites/useBuildStream";
import { RuleEvidence } from "../rules/RuleEvidence";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { Textarea } from "../../components/ui/Input";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";
import { ConfirmBatchActionDialog } from "../batches/ConfirmBatchActionDialog";

const INTERRUPTED_CONTINUE_MESSAGE =
  "服务重启后继续：请先检查工作区和已有产物，从中断处完成剩余工作；不要重复已完成的抓取或覆盖已写好的规则。";

const BUILD_VIEWS = ["status", "evidence", "repairs", "logs"] as const;
type BuildView = (typeof BUILD_VIEWS)[number];

const BUILD_VIEW_LABELS: Record<BuildView, string> = {
  status: "运行状态",
  evidence: "验证证据",
  repairs: "修复轮次",
  logs: "日志与 Trace",
};

function parseBuildView(value: string | null): BuildView {
  return BUILD_VIEWS.find((item) => item === value) ?? "status";
}

function validationLabel(build: BuildStatus): string {
  if (build.validation?.status === "PASSED") return "通过";
  if (build.validation?.status === "FAILED") return "失败";
  if (build.validation?.status === "INCOMPLETE") return "证据不完整";
  if (build.state === "VALIDATING") return "验证中";
  if (buildIsActive(build)) return "等待中";
  return "—";
}

function BuildFact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[88px_minmax(0,1fr)] gap-3 px-4 py-2.5">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="min-w-0 text-xs leading-5 text-ink-2 [overflow-wrap:anywhere]">
        {children}
      </dd>
    </div>
  );
}

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
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeView = parseBuildView(searchParams.get("view"));
  const returnTo = readListReturn(location.state);
  const backHref = returnTo?.href ?? "/builds";
  const backLabel = returnTo?.label ?? "构建记录";
  const backLink = (
    <Link
      className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
      to={backHref}
      state={returnTo ? { listReturn: returnTo } : undefined}
    >
      <ArrowLeft size={15} aria-hidden="true" />
      返回{backLabel}
    </Link>
  );
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

  useEffect(() => {
    const raw = searchParams.get("view");
    if (!raw || BUILD_VIEWS.includes(raw as BuildView)) return;
    const params = new URLSearchParams(searchParams);
    params.delete("view");
    setSearchParams(params, { replace: true, state: location.state });
  }, [searchParams, setSearchParams, location.state]);

  function setView(next: BuildView) {
    const params = new URLSearchParams(searchParams);
    if (next === "status") params.delete("view");
    else params.set("view", next);
    setSearchParams(params, { replace: true, state: location.state });
  }

  function handleViewKey(event: KeyboardEvent<HTMLButtonElement>, current: BuildView) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = BUILD_VIEWS.indexOf(current);
    const next =
      event.key === "Home"
        ? BUILD_VIEWS[0]
        : event.key === "End"
          ? BUILD_VIEWS[BUILD_VIEWS.length - 1]
          : BUILD_VIEWS[
              (index + (event.key === "ArrowRight" ? 1 : -1) + BUILD_VIEWS.length) %
                BUILD_VIEWS.length
            ];
    setView(next);
    window.requestAnimationFrame(() => {
      document.getElementById(`build-tab-${next}`)?.focus();
    });
  }

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
        {backLink}
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
        {backLink}
        <p className="text-sm text-ink-3">正在读取构建 {buildId}…</p>
      </div>
    );
  }

  const rebuildHref = href ? `${href}?build=1` : null;
  const canCancel = ["QUEUED", "CREATED", "RUNNING", "PAUSED"].includes(build.state);
  const events = visibleBuildEvents(build).slice(-4);

  const primary =
    build.state === "QUEUED" || build.state === "CREATED"
      ? {
          kind: "cancel" as const,
          label: build.state === "QUEUED" ? "取消排队" : "取消构建",
        }
      : canPause
        ? { kind: "pause" as const, label: "暂停构建" }
        : canResume
          ? { kind: "resume" as const, label: "继续构建" }
          : canContinue
            ? { kind: "continue" as const, label: "继续原会话" }
            : build.state === "FINISHED" && build.outcome === "succeeded"
              ? { kind: "site" as const, label: "查看站点" }
              : build.state === "CANCELLED"
                ? { kind: "rebuild" as const, label: "重新构建" }
                : null;

  function focusContinue() {
    if (activeView !== "status") setView("status");
    window.setTimeout(() => {
      const input = document.getElementById("build-continue");
      input?.focus();
      input?.scrollIntoView({ block: "center" });
    }, 0);
  }

  function downloadTrace(format: "md" | "json") {
    if (!build) return;
    const link = document.createElement("a");
    link.href = buildTraceUrl(build.build_id, format);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  const summary = (
    <section
      aria-label="构建概览"
      className="rounded-panel border border-line bg-surface px-4 py-3"
    >
      <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm leading-5 xl:grid-cols-4">
        <div className="flex min-w-0 flex-wrap gap-x-2">
          <dt className="font-semibold text-ink">状态</dt>
          <dd className="min-w-0 text-ink-2">
            {buildStateLabel(build.state)}
            {build.outcome ? ` · ${buildOutcomeLabel(build.outcome)}` : ""}
          </dd>
        </div>
        <div className="flex min-w-0 flex-wrap gap-x-2">
          <dt className="font-semibold text-ink">自动修复</dt>
          <dd className="min-w-0 text-ink-2">
            {build.repair_round ? `${build.repair_round}/${build.repair_limit}` : "0"}
          </dd>
        </div>
        <div className="flex min-w-0 flex-wrap gap-x-2">
          <dt className="font-semibold text-ink">耗时</dt>
          <dd className="min-w-0 text-ink-2">
            {build.elapsed_seconds !== null
              ? `${Math.round(build.elapsed_seconds)} 秒`
              : "—"}
          </dd>
        </div>
        <div className="flex min-w-0 flex-wrap gap-x-2">
          <dt className="font-semibold text-ink">验证</dt>
          <dd className="min-w-0 text-ink-2">{validationLabel(build)}</dd>
        </div>
      </dl>
      {build.onboarding_budget || build.token_usage ? (
        <dl className="mt-3 grid gap-x-6 gap-y-2 border-t border-line pt-3 text-sm sm:grid-cols-3">
          {build.onboarding_budget?.max_seconds ? (
            <BuildFact label="模型会话时限">
              {formatNumber(build.onboarding_budget.max_seconds)} 秒
            </BuildFact>
          ) : null}
          <BuildFact label="输入 tokens">
            {build.token_usage?.input === undefined
              ? "—"
              : formatNumber(build.token_usage.input)}
            {build.onboarding_budget?.max_input_tokens
              ? ` / ${formatNumber(build.onboarding_budget.max_input_tokens)}`
              : ""}
          </BuildFact>
          <BuildFact label="输出 tokens（含推理）">
            {build.token_usage
              ? formatNumber(
                  (build.token_usage.output ?? 0) + (build.token_usage.reasoning ?? 0),
                )
              : "—"}
            {build.onboarding_budget?.max_output_tokens
              ? ` / ${formatNumber(build.onboarding_budget.max_output_tokens)}`
              : ""}
          </BuildFact>
        </dl>
      ) : null}
    </section>
  );

  const moreGroups: RowActionItem[][] = [];
  const primaryActions: RowActionItem[] = [];
  if (
    rebuildHref &&
    (canContinue || build.state === "CANCELLED") &&
    primary?.kind !== "rebuild"
  ) {
    primaryActions.push({
      key: "rebuild",
      label: "重新构建（新 build）",
      icon: <RefreshCw size={14} />,
      onSelect: () => navigate(rebuildHref),
    });
  }
  if (canCancel && primary?.kind !== "cancel") {
    primaryActions.push({
      key: "cancel",
      label: "取消构建…",
      icon: <ShieldAlert size={14} />,
      danger: true,
      onSelect: () => {
        setConfirmError("");
        setConfirmCancel(true);
      },
    });
  }
  if (primaryActions.length) moreGroups.push(primaryActions);

  const utilityActions: RowActionItem[] = [
    {
      key: "copy",
      label: "复制构建 ID",
      icon: <FileText size={14} />,
      onSelect: () => void copyId(),
    },
  ];
  if (href) {
    utilityActions.push({
      key: "site",
      label: "打开站点详情",
      icon: <ArrowLeft size={14} />,
      onSelect: () => navigate(href),
    });
  }
  if (build.batch_id) {
    utilityActions.push({
      key: "batch",
      label: "打开批次详情",
      icon: <ArrowLeft size={14} />,
      onSelect: () => navigate(`/batches/${encodeURIComponent(build.batch_id ?? "")}`),
    });
  }
  if (build.trace_available) {
    utilityActions.push(
      {
        key: "trace-md",
        label: "下载构建过程",
        icon: <FileText size={14} />,
        onSelect: () => downloadTrace("md"),
      },
      {
        key: "trace-json",
        label: "下载 trace.json",
        icon: <Download size={14} />,
        onSelect: () => downloadTrace("json"),
      },
    );
  }
  moreGroups.push(utilityActions);

  const continuePanel = canContinue ? (
    <section
      aria-label="继续构建会话"
      className="rounded-panel border border-warning/25 bg-warning-soft px-4 py-4 sm:px-5"
    >
      <div className="border-b border-warning/20 pb-3">
        <h2 className="text-[17px] leading-6 font-semibold text-warning">继续原会话</h2>
        <p className="mt-1 text-xs leading-5 text-ink-2">
          沿用当前构建记录、会话和工作区，把补充指令发回同一模型会话，不产生新的
          build。重新构建会回到站点详情发起新构建，旧记录和证据保留。
        </p>
      </div>
      <div className="mt-3 space-y-3">
        {canContinue ? (
          <>
            <label className="flex flex-col gap-1" htmlFor="build-continue">
              <span className="text-xs font-medium text-ink-3">
                给构建 Agent 的补充指令
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
                  disabled={continueDisabled || (!continueDraft.trim() && !interrupted)}
                >
                  {continueBusy ? "发送中…" : "发送并继续"}
                </Button>
                {rebuildHref ? (
                  <Button
                    size="sm"
                    onClick={() => navigate(rebuildHref)}
                    disabled={continueBusy}
                  >
                    重新构建（新 build）
                  </Button>
                ) : null}
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
  ) : null;

  const factsPanel = (
    <section className="rounded-panel border border-line bg-surface">
      <div className="border-b border-line px-4 py-4 sm:px-5">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">构建事实</h2>
        <p className="mt-0.5 text-xs leading-5 text-ink-3">
          模型、出口、会话和规则；不包含规则正文。
        </p>
      </div>
      <dl className="grid grid-cols-1 gap-x-6 px-4 py-2 sm:grid-cols-2 sm:px-5">
        <BuildFact label="模型">{buildModelLabel(build) || "—"}</BuildFact>
        <BuildFact label="出口">
          {build.proxy ? build.proxy : "服务默认／直连"}
        </BuildFact>
        <BuildFact label="开始">
          {build.started_at ? formatTime(build.started_at) : "—"}
        </BuildFact>
        <BuildFact label="会话">
          <span className="font-mono text-[11px]">{build.session_id || "—"}</span>
        </BuildFact>
        <BuildFact label="来源规则">{build.source_rule?.rule_version || "—"}</BuildFact>
        <BuildFact label="目标规则">
          {build.candidate_rule?.rule_version || build.rule?.rule_version || "—"}
        </BuildFact>
        <BuildFact label="工作区">
          <span className="break-all font-mono text-[11px]">
            {build.workspace || "—"}
          </span>
        </BuildFact>
        <BuildFact label="样例存档">
          {build.archive_stats
            ? `${build.archive_stats.pages} 页 / ${formatBytes(
                build.archive_stats.bytes,
              )}`
            : "—"}
        </BuildFact>
        <BuildFact label="目录">
          {build.catalog?.catalog_scope === "full"
            ? `全量目标 ${build.catalog.catalog_products ?? "—"}`
            : build.catalog?.catalog_scope === "batch"
              ? "批次目标范围"
              : "样例"}
        </BuildFact>
        <BuildFact label="思考">
          {!build.reasoning_capture_enabled
            ? "服务端未开启"
            : build.reasoning_retained
              ? "实时 + trace"
              : build.reasoning_live
                ? "实时，不写 trace"
                : "已开启，等待输出"}
        </BuildFact>
        <BuildFact label="更新">
          <span className="tabular">{formatTime(build.updated_at)}</span>
        </BuildFact>
        <BuildFact label="队列">
          {queued && build.queue_position ? `第 ${build.queue_position} 位` : "—"}
        </BuildFact>
      </dl>
    </section>
  );

  const eventsPanel = (
    <section className="rounded-panel border border-line bg-surface">
      <div className="border-b border-line px-4 py-4 sm:px-5">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">当前阶段</h2>
        <p className="mt-0.5 text-xs leading-5 text-ink-3">
          最近事件；完整模型输出和工具调用在「日志与 Trace」。
        </p>
      </div>
      <div className="px-4 py-3 sm:px-5">
        {events.length ? (
          <ol className="space-y-1.5" aria-label="构建事件">
            {events.map((event, index) => (
              <li
                key={`${event.created_at}-${index}`}
                className="flex flex-wrap items-center gap-2 text-xs"
              >
                <Badge tone={buildEventTone(event)} dot={false}>
                  {buildEventText(event)}
                </Badge>
                <span className="text-ink-3">{formatTime(event.created_at)}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-xs leading-5 text-ink-3">
            {queued
              ? "排队中的构建尚未创建会话；开始后会在这里显示当前阶段。"
              : "还没有可显示的事件。"}
          </p>
        )}
      </div>
    </section>
  );

  const statusContent = (
    <>
      {continuePanel}
      {factsPanel}
      {eventsPanel}
      {build.state === "FINISHED" && build.outcome === "succeeded" ? (
        <p className="flex items-start gap-2 rounded-panel border border-success/25 bg-success-soft px-4 py-3 text-xs leading-5 text-success">
          <FileText className="mt-0.5 shrink-0" size={14} aria-hidden="true" />
          构建完成，候选规则已安装。回到站点详情启动可采站点即可创建采集任务。
        </p>
      ) : null}
    </>
  );

  const evidenceContent = (
    <>
      <section className="rounded-panel border border-line bg-surface">
        <div className="border-b border-line px-4 py-4 sm:px-5">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">验证证据</h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-3">
            主机变更、候选冒烟和同页回归；证据不足时保留阻断理由。
          </p>
        </div>
        <div className="px-4 py-4 sm:px-5">
          {hasEvidence ? (
            <RuleEvidence change={build.change_summary} validation={build.validation} />
          ) : (
            <p className="text-xs leading-5 text-ink-3">
              该构建没有记录主机验证摘要。旧构建、取消或未进入候选安装的会话不会伪造验证结果。
            </p>
          )}
        </div>
      </section>
      <section className="rounded-panel border border-line bg-surface px-4 py-4 sm:px-5">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">样例存档</h2>
        <p className="mt-1 text-xs leading-5 text-ink-3">
          {build.archive_stats
            ? `${build.archive_stats.pages} 页，${formatBytes(
                build.archive_stats.bytes,
              )}；按样例验证范围保存。`
            : "本次构建没有样例存档。"}
        </p>
      </section>
    </>
  );

  const repairsContent = (
    <section className="rounded-panel border border-line bg-surface">
      <div className="border-b border-line px-4 py-4 sm:px-5">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">自动修复轮次</h2>
        <p className="mt-0.5 text-xs leading-5 text-ink-3">
          每轮由主机验证失败触发，使用同一构建会话继续；轮次上限由服务配置。
        </p>
      </div>
      <div className="px-4 py-4 sm:px-5">
        <RepairHistory repairs={build.repairs} />
      </div>
    </section>
  );

  const logsContent = (
    <>
      <section className="rounded-panel border border-line bg-surface px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h2 className="text-[17px] leading-6 font-semibold text-ink">
              日志与 Trace
            </h2>
            <p className="mt-1 text-xs leading-5 text-ink-3">
              构建时间线有界滚动；trace 可能包含页面或提示内容，按证据文件管理。
            </p>
          </div>
          {build.trace_available ? (
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={() => downloadTrace("md")}>
                <FileText size={13} aria-hidden="true" />
                下载构建过程
              </Button>
              <Button size="sm" onClick={() => downloadTrace("json")}>
                <Download size={13} aria-hidden="true" />
                trace.json
              </Button>
            </div>
          ) : null}
        </div>
      </section>
      <BuildTimeline
        build={build}
        messages={messages}
        live={active && !queued}
        connected={stream.connected}
        streamError={stream.error}
        ended={stream.ended}
      />
    </>
  );

  const panels: Record<BuildView, ReactNode> = {
    status: statusContent,
    evidence: evidenceContent,
    repairs: repairsContent,
    logs: logsContent,
  };

  const tabCounts: Record<BuildView, string> = {
    status: "",
    evidence: hasEvidence ? "1" : "",
    repairs: build.repairs.length ? String(build.repairs.length) : "",
    logs: build.trace_available ? "1" : "",
  };

  async function copyId() {
    if (!build) return;
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("浏览器不支持复制操作");
      }
      await navigator.clipboard.writeText(build.build_id);
      setNotice("构建 ID 已复制。");
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }

  function handlePrimary() {
    if (!primary) return;
    if (primary.kind === "cancel") {
      setConfirmError("");
      setConfirmCancel(true);
      return;
    }
    if (primary.kind === "continue") {
      focusContinue();
      return;
    }
    if (primary.kind === "site" && href) {
      navigate(href);
      return;
    }
    if (primary.kind === "rebuild" && rebuildHref) {
      navigate(rebuildHref);
      return;
    }
    if (primary.kind === "pause" || primary.kind === "resume") {
      void runControl(primary.kind);
    }
  }

  return (
    <div className="space-y-6">
      <header className="rounded-panel border border-line bg-surface px-4 py-5 sm:px-6">
        <div className="flex items-center justify-between gap-4">
          {backLink}
          <span className="min-w-0 truncate font-mono text-[11px] text-ink-3">
            {build.build_id}
          </span>
        </div>

        <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[24px] leading-8 font-semibold tracking-[-0.02em] break-words text-ink sm:text-[28px] sm:leading-9">
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
            <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">
              {build.error ? "构建错误" : buildModeLabel(build.mode)} ·{" "}
              <span className="mono text-[11px]">
                {buildModelLabel(build) || "模型未记录"}
              </span>
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
              {href ? (
                <Link className="text-accent hover:underline" to={href}>
                  站点详情
                </Link>
              ) : null}
              {build.batch_id ? (
                <Link
                  className="text-accent hover:underline"
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
            {primary ? (
              <Button
                variant={primary.kind === "cancel" ? "danger" : "primary"}
                onClick={handlePrimary}
                disabled={
                  Boolean(busy) ||
                  (primary.kind === "continue" && continueDisabled) ||
                  (primary.kind === "site" && !href) ||
                  (primary.kind === "rebuild" && !rebuildHref)
                }
              >
                {primary.kind === "pause" ? (
                  <Pause size={14} aria-hidden="true" />
                ) : primary.kind === "resume" ? (
                  <Play size={14} aria-hidden="true" />
                ) : primary.kind === "continue" ? (
                  <Play size={14} aria-hidden="true" />
                ) : primary.kind === "site" ? (
                  <ExternalLink size={14} aria-hidden="true" />
                ) : (
                  <RefreshCw size={14} aria-hidden="true" />
                )}
                {busy &&
                primary.kind !== "continue" &&
                primary.kind !== "site" &&
                primary.kind !== "rebuild"
                  ? "处理中…"
                  : primary.label}
              </Button>
            ) : null}
            <RowActionsMenu
              label="更多构建操作"
              groups={moreGroups}
              busy={busy === "cancel"}
              trigger={
                <Button aria-label="更多构建操作">
                  <MoreHorizontal size={16} aria-hidden="true" />
                  更多
                </Button>
              }
            />
            <Button
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
                size={14}
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
          className="rounded-panel border border-warning/25 bg-warning-soft px-4 py-4 sm:px-5"
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

      {summary}

      <div className="sm:hidden">
        <label className="sr-only" htmlFor="build-view-select">
          切换构建视图
        </label>
        <select
          id="build-view-select"
          className="h-9 w-full rounded-control border border-line-strong bg-surface px-3 text-sm text-ink"
          value={activeView}
          onChange={(event) => setView(event.target.value as BuildView)}
        >
          {BUILD_VIEWS.map((view) => (
            <option key={view} value={view}>
              {BUILD_VIEW_LABELS[view]}
              {tabCounts[view] ? `（${tabCounts[view]}）` : ""}
            </option>
          ))}
        </select>
      </div>

      <div
        className="hidden gap-1 overflow-x-auto border-b border-line sm:flex"
        role="tablist"
        aria-label="构建视图"
      >
        {BUILD_VIEWS.map((view) => {
          const selected = activeView === view;
          const count = tabCounts[view];
          return (
            <button
              key={view}
              id={`build-tab-${view}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`build-panel-${view}`}
              tabIndex={selected ? 0 : -1}
              className={cn(
                "flex shrink-0 items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-semibold transition-colors",
                selected
                  ? "border-accent text-accent"
                  : "border-transparent text-ink-2 hover:text-ink",
              )}
              onClick={() => setView(view)}
              onKeyDown={(event) => handleViewKey(event, view)}
            >
              {BUILD_VIEW_LABELS[view]}
              {count ? (
                <span className="rounded-full bg-surface-sunken px-1.5 text-[10px] leading-[18px] text-ink-3">
                  {count}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {BUILD_VIEWS.map((view) => (
        <section
          key={view}
          id={`build-panel-${view}`}
          role="tabpanel"
          aria-labelledby={`build-tab-${view}`}
          hidden={activeView !== view}
          tabIndex={0}
          className="space-y-5"
        >
          {activeView === view ? panels[view] : null}
        </section>
      ))}

      <ConfirmBatchActionDialog
        open={confirmCancel}
        title="取消这次构建？"
        description="构建会停止，站点回到待接入；已经生成的中间文件和原因会保留。"
        consequence="取消构建不影响已有采集任务和结果；之后可以重新开始构建。"
        confirmLabel="确认取消构建"
        tone="warning"
        busy={busy === "cancel"}
        error={confirmError}
        onOpenChange={(next) => {
          if (!next) setConfirmCancel(false);
        }}
        onConfirm={() => void runControl("cancel")}
      />
    </div>
  );
}
