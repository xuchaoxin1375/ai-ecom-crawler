import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import {
  Link,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { readSiteListReturn } from "../batches/siteListReturn";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Ban,
  Download,
  MoreHorizontal,
  RefreshCw,
  X,
} from "lucide-react";
import {
  cancelBuild,
  cancelTask,
  getBatch,
  getBuild,
  activateSiteRule,
  getBuildConfig,
  getBuildMessages,
  getSiteRule,
  getTasks,
  pauseBuild,
  pauseTask,
  rejectRuleVersion,
  replyBuildDependency,
  replyBuildPermission,
  resumeBuild,
  resumeTask,
  rollbackSiteRule,
  taskExportUrl,
  type BatchActionResponse,
  type BatchDetail,
  type BatchSite,
  type BuildConfig,
  type BuildMessages,
  type BuildResponse,
  type BuildStatus,
} from "../../lib/api";
import {
  buildOutcomeLabel,
  buildStateLabel,
  buildTone,
  coverageLabel,
  formatNumber,
  formatTime,
  outcomeLabel,
  READINESS_LABELS,
  readinessTone,
  stopReasonLabel,
  taskStateLabel,
  taskStateTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import { rememberListReturn, useListReturnRestore } from "../../lib/listReturn";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";
import { ConfirmBatchActionDialog } from "../batches/ConfirmBatchActionDialog";
import {
  siteCanCancelTask,
  siteExportLabel,
  siteExportTaskId,
} from "../batches/actions";
import { ProductPreviewSection } from "../tasks/ProductPreviewSection";
import { QualityExceptionsSection } from "../tasks/QualityExceptionsSection";
import { BuildApprovals } from "./BuildApprovals";
import { SiteRatePolicyPanel } from "./SiteRatePolicyPanel";
import { BuildPanel } from "./BuildPanel";
import { BuildStartDialog } from "./BuildStartDialog";
import { StartSiteDialog } from "./StartSiteDialog";
import { useBuildStream } from "./useBuildStream";
import { RuleEvidence } from "../rules/RuleEvidence";
import {
  buildIsActive,
  buildServiceBlockReason,
  candidateActivationBlockedReason,
  siteHasActiveWork,
  siteNextStep,
  siteStatusSentence,
  taskIsActive,
} from "./site";

type DialogKind =
  "" | "build" | "repair" | "start-site" | "cancel-task" | "cancel-build";

interface Notice {
  tone: "success" | "warning";
  text: string;
}

const SITE_VIEWS = ["current", "history", "rules", "info"] as const;
type SiteView = (typeof SITE_VIEWS)[number];

const SITE_VIEW_LABELS: Record<SiteView, string> = {
  current: "当前采集",
  history: "任务历史",
  rules: "规则与构建",
  info: "站点资料",
};

function parseSiteView(value: string | null): SiteView {
  return SITE_VIEWS.find((item) => item === value) ?? "current";
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[76px_minmax(0,1fr)] gap-3 px-4 py-2.5">
      <dt className="text-xs text-ink-3">{label}</dt>
      <dd className="min-w-0 text-xs leading-5 text-ink-2">{children}</dd>
    </div>
  );
}

function NoticeBanner({
  notice,
  onDismiss,
}: {
  notice: Notice;
  onDismiss: () => void;
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 rounded-panel border px-4 py-3",
        notice.tone === "success"
          ? "border-success/25 bg-success-soft"
          : "border-warning/25 bg-warning-soft",
      )}
      role="status"
    >
      <p
        className={cn(
          "text-sm leading-6",
          notice.tone === "success" ? "text-success" : "text-warning",
        )}
      >
        {notice.text}
      </p>
      <button
        type="button"
        className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface/60 hover:text-ink"
        aria-label="关闭提示"
        onClick={onDismiss}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6" aria-busy="true">
      <span className="sr-only" role="status">
        正在读取站点…
      </span>
      <div className="rounded-panel border border-line bg-surface p-6">
        <div className="h-3 w-32 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-5 h-7 w-72 animate-pulse rounded bg-surface-sunken" />
        <div className="mt-3 h-3 w-96 animate-pulse rounded bg-surface-sunken" />
      </div>
      <div className="h-24 animate-pulse rounded-panel border border-line bg-surface" />
      <div className="grid grid-cols-1 items-start gap-6 xl:grid-cols-[minmax(0,8fr)_minmax(320px,4fr)]">
        <div className="h-[520px] animate-pulse rounded-panel border border-line bg-surface" />
        <div className="space-y-4">
          <div className="h-40 animate-pulse rounded-panel border border-line bg-surface" />
          <div className="h-56 animate-pulse rounded-panel border border-line bg-surface" />
        </div>
      </div>
    </div>
  );
}

function newRuleRequest(prefix: string): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function SiteDetailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { batchId = "", siteKey = "" } = useParams<{
    batchId: string;
    siteKey: string;
  }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const activeView = parseSiteView(searchParams.get("view"));
  const batchPath = `/batches/${encodeURIComponent(batchId)}`;
  const returnPosition = readSiteListReturn(location.state, batchPath);
  const listRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const [dialog, setDialog] = useState<DialogKind>("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [actionError, setActionError] = useState("");
  const [buildActionError, setBuildActionError] = useState("");
  const [confirmError, setConfirmError] = useState("");
  const [taskBusy, setTaskBusy] = useState("");
  const [buildBusy, setBuildBusy] = useState("");
  const [ruleBusy, setRuleBusy] = useState("");
  const [ruleError, setRuleError] = useState("");
  const [ruleNotice, setRuleNotice] = useState("");
  const [startedBuild, setStartedBuild] = useState<{
    siteKey: string;
    buildId: string;
  } | null>(null);

  const batchQuery = useQuery({
    queryKey: ["batch", batchId],
    queryFn: ({ signal }) => getBatch(batchId, signal),
    enabled: Boolean(batchId),
    refetchInterval: (current) => {
      const data = current.state.data;
      const currentSite = data?.sites.find((item) => item.site_key === siteKey);
      return currentSite && siteHasActiveWork(currentSite, currentSite.build)
        ? 3000
        : false;
    },
  });

  const batch: BatchDetail | undefined = batchQuery.data;
  const site: BatchSite | undefined = batch?.sites.find(
    (item) => item.site_key === siteKey,
  );
  const task = site?.task ?? null;
  const buildId =
    site?.build_id ?? (startedBuild?.siteKey === siteKey ? startedBuild.buildId : null);

  const buildQuery = useQuery({
    queryKey: ["build", buildId],
    queryFn: ({ signal }) => getBuild(buildId ?? "", signal),
    enabled: Boolean(buildId),
    refetchInterval: (current) => {
      const data = current.state.data?.build;
      return data && buildIsActive(data) ? 2000 : false;
    },
  });

  const build: BuildStatus | null = buildQuery.data?.build ?? null;

  useListReturnRestore({
    ready: Boolean(batch && site),
    locationKey: location.key,
    navigationState: location.state,
    containerRef: listRef,
  });

  useEffect(() => {
    if (!build || buildIsActive(build)) return;
    void queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
  }, [build, batchId, queryClient]);

  useEffect(() => {
    const raw = searchParams.get("view");
    if (!raw || SITE_VIEWS.includes(raw as SiteView)) return;
    const params = new URLSearchParams(searchParams);
    params.delete("view");
    setSearchParams(params, { replace: true, state: location.state });
  }, [searchParams, setSearchParams, location.state]);

  const stream = useBuildStream(buildId, Boolean(buildId));
  const streamHealthy = stream.connected || stream.ended;

  const messagesQuery = useQuery({
    queryKey: ["build-messages", buildId],
    queryFn: ({ signal }) => getBuildMessages(buildId ?? "", signal),
    enabled: Boolean(buildId),
    refetchInterval: streamHealthy
      ? false
      : build && buildIsActive(build)
        ? 2000
        : false,
  });

  const configQuery = useQuery({
    queryKey: ["build-config"],
    queryFn: ({ signal }) => getBuildConfig(signal),
    staleTime: 60_000,
    retry: false,
  });

  const siteRuleQuery = useQuery({
    queryKey: ["site-rule", siteKey],
    queryFn: ({ signal }) => getSiteRule(siteKey, signal),
    enabled: Boolean(siteKey && site),
    refetchInterval: 10_000,
  });

  const historyQuery = useQuery({
    queryKey: ["site-task-history", siteKey],
    queryFn: ({ signal }) =>
      getTasks(
        {
          siteKey,
          includeArchived: true,
          limit: 8,
        },
        signal,
      ),
    enabled: Boolean(siteKey && site),
    refetchInterval: site && siteHasActiveWork(site, build) ? 5000 : false,
  });

  const taskActive = taskIsActive(task);
  const step = site ? siteNextStep(site, build) : null;
  const messages: BuildMessages | null = stream.messages ?? messagesQuery.data ?? null;
  const config: BuildConfig | null = configQuery.data ?? null;
  const configBlockReason = buildServiceBlockReason(config, {
    loading: configQuery.isPending,
    error: configQuery.isError,
  });
  const buildStepBlocked =
    Boolean(configBlockReason) &&
    (step?.action === "build" || step?.action === "repair");
  const quality = task?.quality_exceptions ?? [];

  const autoBuildMode: "build" | "repair" | null =
    searchParams.get("build") === "1" &&
    site &&
    !dialog &&
    site.readiness !== "invalid" &&
    site.readiness !== "duplicate" &&
    !buildIsActive(build) &&
    !configQuery.isPending &&
    !configBlockReason
      ? site.readiness === "ready"
        ? "repair"
        : "build"
      : null;
  const openBuildMode =
    dialog === "build" || dialog === "repair" ? dialog : autoBuildMode;

  function clearBuildParam() {
    if (searchParams.get("build") !== "1") return;
    const params = new URLSearchParams(searchParams);
    params.delete("build");
    setSearchParams(params, { replace: true, state: location.state });
  }

  function applyBatch(next: BatchDetail) {
    queryClient.setQueryData(["batch", batchId], next);
    void queryClient.invalidateQueries({ queryKey: ["batches"] });
  }

  function invalidateBatch() {
    void queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
  }

  function setView(next: SiteView) {
    const params = new URLSearchParams(searchParams);
    if (next === "current") params.delete("view");
    else params.set("view", next);
    setSearchParams(params, { replace: true, state: location.state });
  }

  function handleViewKey(event: KeyboardEvent<HTMLButtonElement>, current: SiteView) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const index = SITE_VIEWS.indexOf(current);
    const next =
      event.key === "Home"
        ? SITE_VIEWS[0]
        : event.key === "End"
          ? SITE_VIEWS[SITE_VIEWS.length - 1]
          : SITE_VIEWS[
              (index + (event.key === "ArrowRight" ? 1 : -1) + SITE_VIEWS.length) %
                SITE_VIEWS.length
            ];
    setView(next);
    window.requestAnimationFrame(() => {
      document.getElementById(`site-tab-${next}`)?.focus();
    });
  }

  function openBuild(mode: "build" | "repair") {
    setBuildActionError("");
    setDialog(mode);
  }

  function downloadTask() {
    if (!site) return;
    const taskId = siteExportTaskId(site);
    if (!taskId) return;
    const link = document.createElement("a");
    link.href = taskExportUrl(taskId, false);
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  async function runTaskControl(kind: "pause" | "resume" | "cancel") {
    if (!task) return;
    setTaskBusy(kind);
    setActionError("");
    setConfirmError("");
    try {
      if (kind === "pause") await pauseTask(task.task_id);
      else if (kind === "resume") await resumeTask(task.task_id);
      else await cancelTask(task.task_id);
      invalidateBatch();
      setDialog("");
      setNotice({
        tone: "success",
        text:
          kind === "pause"
            ? "暂停请求已受理，任务状态会随后更新。"
            : kind === "resume"
              ? "继续请求已受理，任务会从暂停点恢复。"
              : "取消请求已受理，已产生的部分结果保留。",
      });
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      if (dialog === "cancel-task") setConfirmError(message);
      else setActionError(message);
    } finally {
      setTaskBusy("");
    }
  }

  function refreshRuleState() {
    void queryClient.invalidateQueries({ queryKey: ["site-rule", siteKey] });
    void queryClient.invalidateQueries({ queryKey: ["batch", batchId] });
    void queryClient.invalidateQueries({ queryKey: ["site-task-history", siteKey] });
    void queryClient.invalidateQueries({ queryKey: ["task-feedback"] });
  }

  async function activateCandidate(ruleVersion: string) {
    const rule = siteRuleQuery.data;
    if (!rule) return;
    setRuleBusy(`activate-${ruleVersion}`);
    setRuleError("");
    setRuleNotice("");
    try {
      await activateSiteRule(siteKey, {
        request_id: newRuleRequest("activate"),
        rule_id: rule.rule_id,
        rule_version: ruleVersion,
        expected_active_version: rule.active?.rule_version ?? null,
        expected_active_sha256: rule.active?.sha256 ?? null,
      });
      setRuleNotice(`规则版本 ${ruleVersion} 已激活；旧任务结果标记为过期。`);
      refreshRuleState();
    } catch (exc) {
      setRuleError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRuleBusy("");
    }
  }

  async function rejectCandidate(ruleVersion: string) {
    const rule = siteRuleQuery.data;
    if (!rule?.rule_id) return;
    setRuleBusy(`reject-${ruleVersion}`);
    setRuleError("");
    setRuleNotice("");
    try {
      await rejectRuleVersion(rule.rule_id, ruleVersion, {
        reason: "用户放弃候选规则",
        retry: true,
      });
      setRuleNotice(`候选规则 ${ruleVersion} 已放弃，关联反馈回到待分诊。`);
      refreshRuleState();
    } catch (exc) {
      setRuleError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRuleBusy("");
    }
  }

  async function rollbackRule() {
    const rule = siteRuleQuery.data;
    if (!rule?.active) return;
    setRuleBusy("rollback");
    setRuleError("");
    setRuleNotice("");
    try {
      const response = await rollbackSiteRule(siteKey, {
        request_id: newRuleRequest("rollback"),
        expected_active_version: rule.active.rule_version,
        reason: "回滚到上一生效版本",
      });
      setRuleNotice(`已回滚到 ${response.site.active?.rule_version ?? "上一版本"}。`);
      refreshRuleState();
    } catch (exc) {
      setRuleError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setRuleBusy("");
    }
  }

  function applyBuild(response: BuildResponse) {
    queryClient.setQueryData(["build", response.build.build_id], response);
    invalidateBatch();
    void queryClient.invalidateQueries({
      queryKey: ["build-messages", response.build.build_id],
    });
  }

  async function runBuildControl(kind: "pause" | "resume" | "cancel") {
    if (!build) return;
    setBuildBusy(kind);
    setBuildActionError("");
    setConfirmError("");
    try {
      const response =
        kind === "pause"
          ? await pauseBuild(build.build_id)
          : kind === "resume"
            ? await resumeBuild(build.build_id)
            : await cancelBuild(build.build_id);
      applyBuild(response);
      setDialog("");
      setNotice({
        tone: "success",
        text:
          kind === "pause"
            ? "构建暂停请求已受理。"
            : kind === "resume"
              ? "构建继续请求已受理。"
              : "构建取消请求已受理；站点会回到待接入。",
      });
    } catch (exc) {
      const message = exc instanceof Error ? exc.message : String(exc);
      if (dialog === "cancel-build") setConfirmError(message);
      else setBuildActionError(message);
    } finally {
      setBuildBusy("");
    }
  }

  async function replyDependency(requestId: string, decision: "once" | "reject") {
    if (!build) return;
    setBuildBusy(`dep-${requestId}`);
    setBuildActionError("");
    try {
      applyBuild(await replyBuildDependency(build.build_id, requestId, decision));
    } catch (exc) {
      setBuildActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBuildBusy("");
    }
  }

  async function replyPermission(
    requestId: string,
    decision: "once" | "always" | "reject",
  ) {
    if (!build) return;
    setBuildBusy(`perm-${requestId}`);
    setBuildActionError("");
    try {
      applyBuild(await replyBuildPermission(build.build_id, requestId, decision));
    } catch (exc) {
      setBuildActionError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBuildBusy("");
    }
  }

  function handleStartedBuild(response: BuildResponse) {
    applyBuild(response);
    setStartedBuild({
      siteKey: response.build.site_key,
      buildId: response.build.build_id,
    });
    setBuildActionError("");
    setDialog("");
    clearBuildParam();
    setNotice({
      tone: "success",
      text:
        response.build.mode === "repair"
          ? "修复请求已受理；构建状态和验证进度会随后更新。"
          : "构建请求已受理；构建状态和验证进度会随后更新。",
    });
  }

  function handleStartedTask(response: BatchActionResponse) {
    applyBatch(response.batch);
    setDialog("");
    const accepted = response.accepted.length;
    const skipped = response.skipped[0];
    setNotice({
      tone: accepted ? "success" : "warning",
      text: accepted
        ? `启动请求已受理：${response.accepted[0]?.domain ?? site?.domain ?? "站点"}。`
        : `没有站点被受理${skipped ? `：${skipped.reason}` : "。"}`,
    });
  }

  function handleStep() {
    if (!step) return;
    if ((step.action === "build" || step.action === "repair") && buildStepBlocked) {
      return;
    }
    switch (step.action) {
      case "build":
        openBuild("build");
        break;
      case "repair":
        openBuild("repair");
        break;
      case "pause-build":
        void runBuildControl("pause");
        break;
      case "resume-build":
        void runBuildControl("resume");
        break;
      case "cancel-build":
        setConfirmError("");
        setDialog("cancel-build");
        break;
      case "start":
        setDialog("start-site");
        break;
      case "pause-task":
        void runTaskControl("pause");
        break;
      case "resume-task":
        void runTaskControl("resume");
        break;
      case "cancel-task":
        setConfirmError("");
        setDialog("cancel-task");
        break;
      case "export":
        downloadTask();
        break;
      case "batch":
      case "none":
        break;
    }
  }

  function openTask(taskId: string, event?: MouseEvent<HTMLAnchorElement>) {
    if (event) {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
    }
    navigate(`/tasks/${encodeURIComponent(taskId)}`, {
      state: rememberListReturn(location.key, {
        href: `${location.pathname}${location.search}`,
        label: "站点详情",
        scrollTop: window.scrollY,
        focusKey: taskId,
      }),
    });
  }

  const stepBusy =
    (step?.action === "pause-task" && taskBusy === "pause") ||
    (step?.action === "resume-task" && taskBusy === "resume") ||
    (step?.action === "pause-build" && buildBusy === "pause") ||
    (step?.action === "resume-build" && buildBusy === "resume") ||
    false;

  if (batchQuery.isPending) return <DetailSkeleton />;

  if (!batch) {
    return (
      <div className="space-y-6">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to="/batches"
        >
          <ArrowLeft size={15} aria-hidden="true" />
          返回批次列表
        </Link>
        <ErrorNotice
          title="读取站点失败"
          message={
            batchQuery.error instanceof Error
              ? batchQuery.error.message
              : "批次不存在或服务暂时不可用。"
          }
          onRetry={() => void batchQuery.refetch()}
        />
      </div>
    );
  }

  if (!site) {
    return (
      <div className="space-y-6">
        <Link
          className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
          to={returnPosition?.href ?? batchPath}
          state={returnPosition ? { siteListReturn: returnPosition } : undefined}
        >
          <ArrowLeft size={15} aria-hidden="true" />
          返回 {batch.name}
        </Link>
        <section className="rounded-panel border border-line bg-surface">
          <EmptyState
            title="批次中找不到这个站点"
            description="站点可能已被移除，或链接不完整。"
            action={
              <Button asChild size="sm">
                <Link
                  to={returnPosition?.href ?? batchPath}
                  state={
                    returnPosition ? { siteListReturn: returnPosition } : undefined
                  }
                >
                  返回批次详情
                </Link>
              </Button>
            }
          />
        </section>
      </div>
    );
  }

  const needsBuildFirst =
    !task &&
    (site.readiness === "needs_onboarding" ||
      site.readiness === "building" ||
      buildIsActive(build));

  const buildPanel = (
    <BuildPanel
      site={site}
      build={build}
      messages={messages}
      busy={buildBusy}
      error={buildActionError}
      refreshing={buildQuery.isFetching || messagesQuery.isFetching}
      streamConnected={stream.connected}
      streamError={stream.error}
      streamEnded={stream.ended}
      blockedReason={configBlockReason}
      showRepair={step?.action !== "repair"}
      onRetryConfig={configQuery.isError ? () => void configQuery.refetch() : undefined}
      onOpenStart={openBuild}
      onRefresh={() => {
        void buildQuery.refetch();
        void messagesQuery.refetch();
        invalidateBatch();
      }}
    />
  );

  const buildNeedsAttention = Boolean(
    build &&
    task &&
    (buildIsActive(build) ||
      (build.state === "FINISHED" && build.outcome === "interrupted")),
  );

  const buildStrip =
    build && buildNeedsAttention ? (
      <section
        aria-label="构建状态"
        className="flex flex-wrap items-center gap-3 rounded-panel border border-warning/25 bg-warning-soft px-4 py-3"
      >
        <Badge tone={buildTone(build.state, build.outcome)}>
          {buildStateLabel(build.state)}
        </Badge>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-ink">
            {build.mode === "repair" ? "规则修复构建" : "方案构建"}
            {build.outcome ? ` · ${buildOutcomeLabel(build.outcome)}` : ""}
          </p>
          <p className="text-xs leading-5 text-ink-3">
            更新 {formatTime(build.updated_at)} · 审批和构建详情在「规则与构建」
          </p>
        </div>
        <Button size="sm" onClick={() => setView("rules")}>
          查看构建
        </Button>
      </section>
    ) : null;

  const summary = (
    <dl
      aria-label="站点进度"
      className="grid grid-cols-2 gap-x-6 gap-y-2 rounded-panel border border-line bg-surface px-4 py-3 text-sm leading-5 xl:grid-cols-4"
    >
      <div className="flex min-w-0 flex-wrap gap-x-2">
        <dt className="font-semibold text-ink">任务</dt>
        <dd className="min-w-0 text-ink-2">
          {task
            ? `${taskStateLabel(task.state)}${
                task.outcome ? ` · ${outcomeLabel(task.outcome)}` : ""
              }`
            : "—"}
        </dd>
      </div>
      <div className="flex min-w-0 flex-wrap gap-x-2">
        <dt className="font-semibold text-ink">有效／失败</dt>
        <dd className="min-w-0 text-ink-2">
          {task
            ? `${formatNumber(task.counts.valid_products ?? 0)} / ${formatNumber(
                task.counts.failed_products ?? 0,
              )}`
            : "—"}
        </dd>
      </div>
      <div className="flex min-w-0 flex-wrap gap-x-2">
        <dt className="font-semibold text-ink">覆盖</dt>
        <dd className="min-w-0 text-ink-2">
          {task ? coverageLabel(task.coverage?.status) : "—"}
        </dd>
      </div>
      <div className="flex min-w-0 flex-wrap gap-x-2">
        <dt className="font-semibold text-ink">质量异常</dt>
        <dd className="min-w-0 text-ink-2">{formatNumber(quality.length)}</dd>
      </div>
    </dl>
  );

  const tabCounts: Record<SiteView, string> = {
    current: task ? formatNumber(task.counts.valid_products ?? 0) : "",
    history: historyQuery.data?.items.length
      ? formatNumber(historyQuery.data.items.length)
      : "",
    rules: siteRuleQuery.data?.candidates.length
      ? formatNumber(siteRuleQuery.data.candidates.length)
      : "",
    info: "",
  };

  const moreActions: RowActionItem[][] = [];
  if (siteExportTaskId(site) && step?.action !== "export") {
    moreActions.push([
      {
        key: "export",
        label: siteExportLabel(site),
        icon: <Download size={14} />,
        onSelect: downloadTask,
      },
    ]);
  }
  const dangerActions: RowActionItem[] = [];
  if (task && siteCanCancelTask(site) && step?.action !== "cancel-task") {
    dangerActions.push({
      key: "cancel-task",
      label: "取消任务…",
      icon: <Ban size={14} />,
      danger: true,
      onSelect: () => {
        setConfirmError("");
        setDialog("cancel-task");
      },
    });
  }
  if (
    build &&
    buildIsActive(build) &&
    build.state !== "CANCELLING" &&
    step?.action !== "cancel-build"
  ) {
    dangerActions.push({
      key: "cancel-build",
      label: "取消构建…",
      icon: <Ban size={14} />,
      danger: true,
      onSelect: () => {
        setConfirmError("");
        setDialog("cancel-build");
      },
    });
  }
  if (dangerActions.length) moreActions.push(dangerActions);

  const emptyState = (
    <section className="rounded-panel border border-line bg-surface">
      <EmptyState
        title={
          site.readiness === "ready"
            ? "站点可采，但还没有任务"
            : site.readiness === "needs_onboarding"
              ? "站点待接入"
              : site.readiness === "building"
                ? "规则包构建中"
                : "该条目无效或重复，不进入采集"
        }
        description={
          site.readiness === "ready"
            ? "使用页头的「启动采集」创建任务；任务会进入队列，已有结果和历史任务不受影响。"
            : site.readiness === "needs_onboarding"
              ? configBlockReason
                ? "构建入口当前不可用；先处理上方提示，再启动构建。"
                : "使用页头的「启动构建」生成候选规则；验证通过后站点自动变为可采。"
              : site.readiness === "building"
                ? "规则包正在构建或验证；构建状态和审批在上方，站点不会被显示成可启动。"
                : "无效和重复条目只保留在批次记录中，不创建任务、不计为失败。"
        }
      />
    </section>
  );

  const taskSection = task ? (
    <section className="rounded-panel border border-line bg-surface">
      <div className="flex flex-col items-start gap-3 border-b border-line px-4 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-5">
        <div className="min-w-0">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">当前任务</h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-3">
            任务 {task.task_id} · {task.plan_id}@{task.plan_version}
          </p>
        </div>
        <Button asChild size="sm">
          <Link
            to={`/tasks/${encodeURIComponent(task.task_id)}`}
            onClick={(event) => openTask(task.task_id, event)}
            data-return-focus={task.task_id}
          >
            打开任务详情
          </Link>
        </Button>
      </div>
      <dl className="grid grid-cols-2 gap-px bg-line max-sm:hidden sm:grid-cols-4">
        <div className="bg-surface px-4 py-3">
          <dt className="text-xs text-ink-3">停止原因</dt>
          <dd className="mt-0.5 text-sm text-ink">
            {stopReasonLabel(task.stop_reason)}
          </dd>
        </div>
        <div className="bg-surface px-4 py-3">
          <dt className="text-xs text-ink-3">更新</dt>
          <dd className="mt-0.5 text-sm text-ink tabular">
            {formatTime(task.updated_at)}
          </dd>
        </div>
        <div className="bg-surface px-4 py-3">
          <dt className="text-xs text-ink-3">排除</dt>
          <dd className="mt-0.5 text-sm text-ink tabular">
            {formatNumber(task.counts.excluded_products ?? 0)}
          </dd>
        </div>
        <div className="bg-surface px-4 py-3">
          <dt className="text-xs text-ink-3">结果</dt>
          <dd className="mt-0.5 text-sm text-ink">
            {taskActive
              ? "任务未结束，结果会继续更新"
              : task.counts.valid_products === 0
                ? "本次没有有效商品"
                : "结果已生成"}
          </dd>
        </div>
      </dl>
      {site.delivery_task && site.delivery_task.task_id !== task.task_id ? (
        <div className="px-4 py-2.5 text-xs leading-5 text-ink-3 sm:px-5">
          站点和批次导出仍使用{" "}
          <Link
            className="text-accent hover:underline"
            to={`/tasks/${encodeURIComponent(site.delivery_task.task_id)}`}
          >
            上次已采用的结果
          </Link>
          。
        </div>
      ) : null}
    </section>
  ) : null;

  const rawDataSection = task ? (
    <section className="rounded-panel border border-line bg-surface px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">原始数据</h2>
          <p className="mt-1 text-xs leading-5 text-ink-3">
            CSV
            预览和任务明细在任务详情中查看；站点页只保留结果、质量异常和入口，避免两处重复。
          </p>
        </div>
        <Button asChild size="sm">
          <Link
            to={`/tasks/${encodeURIComponent(task.task_id)}`}
            onClick={(event) => openTask(task.task_id, event)}
            data-return-focus={task.task_id}
          >
            查看 CSV 与明细
          </Link>
        </Button>
      </div>
    </section>
  ) : null;

  const currentContent = needsBuildFirst ? (
    <>
      {buildPanel}
      {emptyState}
    </>
  ) : task ? (
    <>
      {buildStrip}
      {taskSection}
      <ProductPreviewSection
        taskId={task.task_id}
        taskActive={taskActive}
        validCount={task.counts.valid_products ?? 0}
      />
      <QualityExceptionsSection exceptions={quality} />
      {rawDataSection}
    </>
  ) : (
    <>
      {emptyState}
      {buildPanel}
    </>
  );

  const rulesSection = (
    <section className="rounded-panel border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">规则版本</h2>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void siteRuleQuery.refetch()}
          disabled={siteRuleQuery.isFetching}
        >
          刷新
        </Button>
      </div>
      {siteRuleQuery.isError ? (
        <p className="px-4 py-3 text-xs leading-5 text-danger">
          读取规则版本失败：
          {siteRuleQuery.error instanceof Error
            ? siteRuleQuery.error.message
            : "服务暂时不可用。"}
        </p>
      ) : (
        <div className="space-y-3 px-4 py-4">
          {ruleNotice ? (
            <p className="rounded-control border border-success/20 bg-success-soft px-2.5 py-2 text-xs leading-5 text-success">
              {ruleNotice}
            </p>
          ) : null}
          {ruleError ? (
            <p className="rounded-control border border-danger/20 bg-danger-soft px-2.5 py-2 text-xs leading-5 text-danger">
              {ruleError}
            </p>
          ) : null}
          <div>
            <p className="text-[11px] text-ink-3">当前生效</p>
            <p className="mt-0.5 font-mono text-xs text-ink">
              {siteRuleQuery.data?.active
                ? `${siteRuleQuery.data.rule_id}@${siteRuleQuery.data.active.rule_version}`
                : "暂无生效规则"}
            </p>
            {siteRuleQuery.data?.active ? (
              <p className="mt-0.5 text-[11px] text-ink-3">
                过期任务 {siteRuleQuery.data.stale_tasks} · 未关闭反馈{" "}
                {siteRuleQuery.data.open_feedback}
              </p>
            ) : null}
            {siteRuleQuery.data?.active ? (
              <Button
                className="mt-2"
                size="sm"
                onClick={() => void rollbackRule()}
                disabled={Boolean(ruleBusy)}
              >
                回滚上一版本
              </Button>
            ) : null}
          </div>

          <div className="border-t border-line pt-3">
            <p className="text-[11px] text-ink-3">候选规则</p>
            {siteRuleQuery.data?.candidates.length ? (
              <ul className="mt-1.5 space-y-2">
                {siteRuleQuery.data.candidates.map((candidate) => {
                  const activationBlocked = candidateActivationBlockedReason(candidate);
                  return (
                    <li
                      key={candidate.rule_version}
                      className="rounded-control border border-warning/25 bg-warning-soft px-2.5 py-2"
                    >
                      <p className="flex items-center justify-between gap-2 font-mono text-[11px] text-ink">
                        <span>{candidate.rule_version}</span>
                        <Badge tone="warning" dot={false}>
                          待激活
                        </Badge>
                      </p>
                      <p className="mt-0.5 text-[11px] text-ink-3">
                        {candidate.build_id || "未知构建"} ·{" "}
                        {formatTime(candidate.created_at)}
                      </p>
                      <RuleEvidence
                        change={candidate.change_summary}
                        validation={candidate.validation}
                        className="mt-1.5 border-t border-warning/20 pt-1.5"
                      />
                      <div className="mt-2 flex items-center gap-1.5">
                        <Button
                          size="sm"
                          variant="primary"
                          onClick={() => void activateCandidate(candidate.rule_version)}
                          disabled={
                            Boolean(ruleBusy) ||
                            siteHasActiveWork(site, build) ||
                            Boolean(activationBlocked)
                          }
                          title={activationBlocked ?? undefined}
                        >
                          激活
                        </Button>
                        <Button
                          size="sm"
                          onClick={() => void rejectCandidate(candidate.rule_version)}
                          disabled={Boolean(ruleBusy)}
                        >
                          放弃
                        </Button>
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="mt-1 text-xs leading-5 text-ink-3">
                {siteRuleQuery.isPending
                  ? "正在读取…"
                  : "没有候选规则；定向修复成功后会出现。"}
              </p>
            )}
          </div>
        </div>
      )}
    </section>
  );

  const rulesContent = (
    <>
      {buildPanel}
      {rulesSection}
    </>
  );

  const historyContent = (
    <section className="rounded-panel border border-line bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
        <div>
          <h2 className="text-[17px] leading-6 font-semibold text-ink">任务历史</h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-3">
            最近任务；旧任务和结果保留，不随复跑删除。
          </p>
        </div>
        <Link
          className="text-xs text-accent hover:underline"
          to={`/tasks?site=${encodeURIComponent(site.site_key)}&archived=1`}
        >
          全部任务
        </Link>
      </div>
      {historyQuery.isError ? (
        <div className="space-y-2 px-4 py-3">
          <p className="text-xs leading-5 text-danger">
            读取任务历史失败：
            {historyQuery.error instanceof Error
              ? historyQuery.error.message
              : "服务暂时不可用。"}
          </p>
          <Button size="sm" onClick={() => void historyQuery.refetch()}>
            重试
          </Button>
        </div>
      ) : (historyQuery.data?.items.length ?? 0) > 0 ? (
        <ul className="divide-y divide-line">
          {historyQuery.data?.items.map((item) => (
            <li key={item.task_id}>
              <Link
                className="block px-4 py-2.5 transition-colors hover:bg-surface-muted"
                to={`/tasks/${encodeURIComponent(item.task_id)}`}
                onClick={(event) => openTask(item.task_id, event)}
                data-return-focus={item.task_id}
              >
                <div className="flex items-center justify-between gap-2">
                  <code className="truncate font-mono text-[11px] text-ink-2">
                    {item.task_id}
                  </code>
                  <Badge tone={taskStateTone(item.state)} dot={false}>
                    {taskStateLabel(item.state)}
                  </Badge>
                </div>
                <p className="mt-0.5 text-[11px] text-ink-3">
                  {item.outcome ? outcomeLabel(item.outcome) : "未结束"}
                  {item.archived_at ? " · 已归档" : ""}
                  {" · "}
                  {item.task_type === "discovery" ? "网址" : "有效"}{" "}
                  {formatNumber(
                    item.task_type === "discovery"
                      ? (item.counts.discovered_urls ?? 0)
                      : (item.counts.valid_products ?? 0),
                  )}
                  {" · "}
                  {formatTime(item.updated_at)}
                </p>
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className="px-4 py-6 text-xs leading-5 text-ink-3">
          {historyQuery.isPending ? "正在读取任务历史…" : "这个站点还没有任务记录。"}
        </p>
      )}
    </section>
  );

  const infoContent = (
    <div className="space-y-6">
      <section className="rounded-panel border border-line bg-surface">
        <div className="border-b border-line px-4 py-4 sm:px-5">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">站点资料</h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-3">
            批次、市场、规则路径和技术标识；低频信息集中在这里，不占结果首屏。
          </p>
        </div>
        <dl className="grid grid-cols-1 gap-x-6 px-4 py-2 sm:grid-cols-2 sm:px-5">
          <Fact label="批次">
            <Link
              className="text-accent hover:underline"
              to={`/batches/${encodeURIComponent(batch.batch_id)}`}
            >
              {batch.name}
            </Link>
          </Fact>
          <Fact label="站点 ID">
            <code className="break-all font-mono text-[11px]">{site.site_key}</code>
          </Fact>
          <Fact label="国家／市场">
            {batch.country || "—"} / {batch.market || "—"}
          </Fact>
          <Fact label="语言">{batch.language || "—"}</Fact>
          <Fact label="品类">{batch.category || "—"}</Fact>
          <Fact label="规则">
            {site.rule ? (
              <span className="font-mono text-[11px]">
                {site.rule.rule_id}@{site.rule.rule_version}
              </span>
            ) : (
              "—"
            )}
          </Fact>
          <Fact label="规则路径">
            <code className="break-all font-mono text-[11px]">
              {site.rule?.path || "—"}
            </code>
          </Fact>
          <Fact label="任务 ID">
            {task ? <code className="font-mono text-[11px]">{task.task_id}</code> : "—"}
          </Fact>
          <Fact label="计划">
            {task ? (
              <code className="font-mono text-[11px]">
                {task.plan_id}@{task.plan_version}
              </code>
            ) : (
              "—"
            )}
          </Fact>
          <Fact label="构建 ID">
            {buildId ? <code className="font-mono text-[11px]">{buildId}</code> : "—"}
          </Fact>
          <Fact label="市场">{task?.market || batch.market || "—"}</Fact>
          <Fact label="出口">
            {site.proxy
              ? site.proxy
              : site.proxy_configured
                ? "已配置"
                : "服务默认／直连"}
          </Fact>
          <Fact label="创建">
            <span className="tabular">{formatTime(site.created_at)}</span>
          </Fact>
          <Fact label="更新">
            <span className="tabular">{formatTime(site.updated_at)}</span>
          </Fact>
          <Fact label="最近构建">
            {build ? (
              <span>
                {buildStateLabel(build.state)}
                {build.outcome ? ` · ${buildOutcomeLabel(build.outcome)}` : ""}
              </span>
            ) : site.build ? (
              <span>
                {buildStateLabel(site.build.state)}
                {site.build.outcome
                  ? ` · ${buildOutcomeLabel(site.build.outcome)}`
                  : ""}
              </span>
            ) : (
              "—"
            )}
          </Fact>
        </dl>
      </section>
      <SiteRatePolicyPanel batchId={batch.batch_id} siteKey={site.site_key} />
    </div>
  );

  const panels: Record<SiteView, ReactNode> = {
    current: currentContent,
    history: historyContent,
    rules: rulesContent,
    info: infoContent,
  };

  return (
    <div ref={listRef} tabIndex={-1} className="space-y-6">
      <header className="rounded-panel border border-line bg-surface px-4 py-5 sm:px-6">
        <div className="flex items-center justify-between gap-4">
          <Link
            className="inline-flex items-center gap-1.5 text-sm font-medium text-ink-2 hover:text-ink"
            to={returnPosition?.href ?? batchPath}
            state={returnPosition ? { siteListReturn: returnPosition } : undefined}
          >
            <ArrowLeft size={15} aria-hidden="true" />
            返回 {batch.name}
          </Link>
          <span className="hidden min-w-0 truncate font-mono text-[11px] text-ink-3 sm:inline">
            {site.site_key}
          </span>
        </div>

        <div className="mt-3 flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between lg:gap-8">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-[24px] leading-8 font-semibold tracking-[-0.02em] break-words text-ink sm:text-[28px] sm:leading-9">
                {site.domain}
              </h1>
              <Badge tone={readinessTone(site.readiness)}>
                {READINESS_LABELS[site.readiness]}
              </Badge>
              {task ? (
                <Badge tone={taskStateTone(task.state)} dot={false}>
                  {taskStateLabel(task.state)}
                </Badge>
              ) : null}
              {build || site.build ? (
                <Badge
                  tone={buildTone(
                    (build ?? site.build)?.state,
                    (build ?? site.build)?.outcome,
                  )}
                  dot={false}
                >
                  {buildStateLabel((build ?? site.build)?.state)}
                </Badge>
              ) : null}
            </div>
            <p
              className="mt-1 max-w-3xl text-sm leading-6 text-ink-2 line-clamp-2 break-words lg:line-clamp-none"
              title={`${site.input_value}${site.note ? ` · ${site.note}` : ""}`}
            >
              {site.input_value}
              {site.note ? ` · ${site.note}` : ""}
            </p>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
              <span>{step?.title ?? siteStatusSentence(site, build)}</span>
              <span>更新 {formatTime(task?.updated_at || site.updated_at)}</span>
              {site.rule ? (
                <span className="font-mono">
                  {site.rule.rule_id}@{site.rule.rule_version}
                </span>
              ) : null}
            </div>
          </div>

          <div className="flex w-full flex-wrap items-center gap-2 lg:w-auto lg:shrink-0 lg:justify-end">
            {step && step.action !== "none" ? (
              step.action === "batch" ? (
                <Button asChild variant="primary">
                  <Link to={`/batches/${encodeURIComponent(batch.batch_id)}`}>
                    {step.actionLabel ?? "回批次详情"}
                    <ArrowRight size={14} aria-hidden="true" />
                  </Link>
                </Button>
              ) : (
                <Button
                  variant={
                    step.action === "cancel-task" || step.action === "cancel-build"
                      ? "danger"
                      : "primary"
                  }
                  onClick={handleStep}
                  disabled={stepBusy || buildStepBlocked}
                  title={
                    buildStepBlocked ? (configBlockReason ?? undefined) : undefined
                  }
                >
                  {stepBusy ? "处理中…" : step.actionLabel}
                </Button>
              )
            ) : null}
            {moreActions.length ? (
              <RowActionsMenu
                label="更多站点操作"
                groups={moreActions}
                trigger={
                  <Button aria-label="更多站点操作">
                    <MoreHorizontal size={16} aria-hidden="true" />
                    更多
                  </Button>
                }
              />
            ) : null}
            <Button
              onClick={() => {
                void batchQuery.refetch();
                void buildQuery.refetch();
                void messagesQuery.refetch();
              }}
              disabled={batchQuery.isFetching || buildQuery.isFetching}
            >
              <RefreshCw
                className={
                  batchQuery.isFetching || buildQuery.isFetching
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
        <NoticeBanner notice={notice} onDismiss={() => setNotice(null)} />
      ) : null}

      {actionError ? (
        <ErrorNotice title="操作失败" message={actionError} compact />
      ) : null}

      <BuildApprovals
        build={build}
        busy={buildBusy}
        error={buildActionError}
        onReplyDependency={(requestId, decision) =>
          void replyDependency(requestId, decision)
        }
        onReplyPermission={(requestId, decision) =>
          void replyPermission(requestId, decision)
        }
      />

      {buildStepBlocked ? (
        <InlineNotice tone="warning" title="构建服务不可用">
          <p>{configBlockReason}</p>
          {configQuery.isError ? (
            <Button
              className="mt-2"
              size="sm"
              onClick={() => void configQuery.refetch()}
            >
              重试读取配置
            </Button>
          ) : null}
        </InlineNotice>
      ) : null}

      {summary}

      <div className="sm:hidden">
        <label className="sr-only" htmlFor="site-view-select">
          切换站点视图
        </label>
        <select
          id="site-view-select"
          className="h-9 w-full rounded-control border border-line-strong bg-surface px-3 text-sm text-ink"
          value={activeView}
          onChange={(event) => setView(event.target.value as SiteView)}
        >
          {SITE_VIEWS.map((view) => (
            <option key={view} value={view}>
              {SITE_VIEW_LABELS[view]}
              {tabCounts[view] ? `（${tabCounts[view]}）` : ""}
            </option>
          ))}
        </select>
      </div>

      <div
        className="hidden gap-1 overflow-x-auto border-b border-line sm:flex"
        role="tablist"
        aria-label="站点视图"
      >
        {SITE_VIEWS.map((view) => {
          const selected = activeView === view;
          const count = tabCounts[view];
          return (
            <button
              key={view}
              id={`site-tab-${view}`}
              type="button"
              role="tab"
              aria-selected={selected}
              aria-controls={`site-panel-${view}`}
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
              {SITE_VIEW_LABELS[view]}
              {count ? (
                <span className="rounded-full bg-surface-sunken px-1.5 text-[10px] leading-[18px] text-ink-3">
                  {count}
                </span>
              ) : null}
            </button>
          );
        })}
      </div>

      {SITE_VIEWS.map((view) => (
        <section
          key={view}
          id={`site-panel-${view}`}
          role="tabpanel"
          aria-labelledby={`site-tab-${view}`}
          hidden={activeView !== view}
          tabIndex={0}
          className="space-y-5"
        >
          {panels[view]}
        </section>
      ))}

      {openBuildMode ? (
        <BuildStartDialog
          open
          batchId={batch.batch_id}
          site={site}
          config={config}
          blockedReason={configBlockReason}
          initialMode={openBuildMode}
          onOpenChange={(next) => {
            if (!next) {
              setDialog("");
              clearBuildParam();
            }
          }}
          onStarted={handleStartedBuild}
        />
      ) : null}

      {dialog === "start-site" ? (
        <StartSiteDialog
          open
          batchId={batch.batch_id}
          site={site}
          collectionMode={batch.collection_mode}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onStarted={handleStartedTask}
        />
      ) : null}

      {dialog === "cancel-task" && task ? (
        <ConfirmBatchActionDialog
          open
          title="取消这个任务？"
          description="排队或运行中的任务会停止；已经产生的部分结果保留，可继续导出。"
          consequence="取消是任务级操作，不会删除批次和站点；可回批次详情复跑该站点。"
          confirmLabel="确认取消任务"
          tone="danger"
          busy={taskBusy === "cancel"}
          error={confirmError}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onConfirm={() => void runTaskControl("cancel")}
        />
      ) : null}

      {dialog === "cancel-build" && build ? (
        <ConfirmBatchActionDialog
          open
          title="取消这次构建？"
          description="构建会停止，站点回到待接入；已经生成的中间文件和原因会保留。"
          consequence="取消构建不影响已有采集任务和结果；之后可以重新开始构建。"
          confirmLabel="确认取消构建"
          tone="warning"
          busy={buildBusy === "cancel"}
          error={confirmError}
          onOpenChange={(next) => {
            if (!next) setDialog("");
          }}
          onConfirm={() => void runBuildControl("cancel")}
        />
      ) : null}
    </div>
  );
}
