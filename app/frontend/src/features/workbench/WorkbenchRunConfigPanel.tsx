import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, RotateCcw, Save, SlidersHorizontal } from "lucide-react";
import {
  getWorkbenchRunConfig,
  updateWorkbenchRunConfig,
  type WorkbenchRunConfig,
  type WorkbenchRunConfigResult,
  type WorkbenchRunConfigUpdate,
} from "../../lib/api";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Checkbox, Input } from "../../components/ui/Input";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import {
  formatNumber,
  stopReasonLabel,
  taskStatusLabel,
  taskStatusTone,
} from "../../lib/format";

interface RunConfigFormState {
  maxProducts: string;
  maxSeconds: string;
  maxUrls: string;
  maxAttempts: string;
  maxNavigation: string;
  maxSitemaps: string;
  concurrency: string;
  perDomainRps: string;
  delayMs: string;
}

interface WorkbenchRunConfigPanelProps {
  taskId: string | null;
  readOnly: boolean;
  onSaved: (result: WorkbenchRunConfigResult) => void;
}

function optionalText(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

function formFromConfig(config: WorkbenchRunConfig): RunConfigFormState {
  return {
    maxProducts: optionalText(config.limits.max_products),
    maxSeconds: optionalText(config.limits.max_seconds),
    maxUrls: optionalText(config.limits.max_urls),
    maxAttempts: String(config.limits.max_attempts ?? 2),
    maxNavigation: optionalText(config.limits.max_navigation),
    maxSitemaps: optionalText(config.limits.max_sitemaps),
    concurrency: optionalText(config.limits.concurrency),
    perDomainRps: optionalText(config.limits.per_domain_rps),
    delayMs: optionalText(config.limits.delay_ms),
  };
}

const EDITABLE_STATES = new Set(["QUEUED", "RUNNING", "PAUSED", "PAUSING"]);

function readOptional(
  value: string,
  label: string,
  min: number,
  max: number,
): number | null | string {
  const text = value.trim();
  if (!text) return null;
  const number = Number(text);
  if (!Number.isFinite(number) || number < min || number > max) {
    return `${label}必须是 ${min} 到 ${max} 之间的数字`;
  }
  return number;
}

function readRequired(
  value: string,
  label: string,
  min: number,
  max: number,
): number | string {
  const text = value.trim();
  if (!text) return `${label}不能为空`;
  const number = Number(text);
  if (!Number.isFinite(number) || number < min || number > max) {
    return `${label}必须是 ${min} 到 ${max} 之间的数字`;
  }
  return number;
}

export function WorkbenchRunConfigPanel({
  taskId,
  readOnly,
  onSaved,
}: WorkbenchRunConfigPanelProps) {
  const queryClient = useQueryClient();
  const configQuery = useQuery({
    queryKey: ["workbench-run-config", taskId],
    queryFn: ({ signal }) => getWorkbenchRunConfig(taskId as string, signal),
    enabled: Boolean(taskId),
    refetchOnWindowFocus: false,
    refetchInterval: (query) => {
      const state = query.state.data?.state;
      return state === "RUNNING" || state === "PAUSING" || state === "CANCELLING"
        ? 3000
        : false;
    },
  });

  if (!taskId) {
    return (
      <div
        role="tabpanel"
        aria-label="运行配置"
        className="flex min-h-0 flex-1 items-center justify-center p-6"
      >
        <EmptyState
          title="未选择运行"
          description="从最近任务或任务树选择一条运行，查看预算、速度和发现上限。"
        />
      </div>
    );
  }

  if (configQuery.isPending) {
    return (
      <div
        role="tabpanel"
        aria-label="运行配置"
        className="flex min-h-0 flex-1 items-center justify-center p-6 text-sm text-ink-3"
      >
        正在读取运行配置…
      </div>
    );
  }

  if (configQuery.isError || !configQuery.data) {
    return (
      <div role="tabpanel" aria-label="运行配置" className="min-h-0 flex-1 p-4">
        <ErrorNotice
          title="读取运行配置失败"
          message={
            configQuery.error instanceof Error ? configQuery.error.message : "未知错误"
          }
          compact
          onRetry={() => void configQuery.refetch()}
        />
      </div>
    );
  }

  const config = configQuery.data;
  return (
    <div role="tabpanel" aria-label="运行配置" className="flex min-h-0 flex-1 flex-col">
      <RunConfigForm
        key={`${config.task_id}:${config.state}:${JSON.stringify(config.limits)}`}
        config={config}
        readOnly={readOnly}
        onSaved={(result) => {
          onSaved(result);
          void queryClient.invalidateQueries({
            queryKey: ["workbench-run-config", taskId],
          });
        }}
      />
    </div>
  );
}

function RunConfigForm({
  config,
  readOnly,
  onSaved,
}: {
  config: WorkbenchRunConfig;
  readOnly: boolean;
  onSaved: (result: WorkbenchRunConfigResult) => void;
}) {
  const isFormal = config.collection_mode === "formal";
  const [budgetEnabled, setBudgetEnabled] = useState(!isFormal);
  const [form, setForm] = useState<RunConfigFormState>(() => formFromConfig(config));
  const initial = formFromConfig(config);
  const [syncDefinition, setSyncDefinition] = useState(Boolean(config.definition));
  const [resetDiscovery, setResetDiscovery] = useState(Boolean(config.reset_discovery));
  const [busy, setBusy] = useState<"save" | "continue" | "">("");
  const [localError, setLocalError] = useState("");
  const [notice, setNotice] = useState("");

  const editable = EDITABLE_STATES.has(config.state);
  const canSaveDefinition = Boolean(config.definition);
  const canSave = (editable || canSaveDefinition) && !readOnly;

  const counts = config.counts ?? {};
  const pendingProducts = Number(counts.pending_products ?? 0);
  const pendingUrls = Number(counts.pending_urls ?? 0);
  const pending = config.task_type === "discovery" ? pendingUrls : pendingProducts;
  const processed =
    config.task_type === "discovery"
      ? Number(counts.valid_urls ?? 0) +
        Number(counts.excluded_urls ?? 0) +
        Number(counts.failed_urls ?? 0)
      : Number(counts.processed_products ?? 0);
  const candidates =
    config.task_type === "discovery"
      ? Number(counts.url_candidates ?? 0)
      : Number(counts.product_candidates ?? 0);
  const valid =
    config.task_type === "discovery"
      ? Number(counts.valid_urls ?? 0)
      : Number(counts.valid_products ?? 0);
  const failed =
    config.task_type === "discovery"
      ? Number(counts.failed_urls ?? 0)
      : Number(counts.failed_products ?? 0);
  const statusText = taskStatusLabel(config.state, config.outcome);
  const currentBudgetParts = [
    config.limits.max_products !== null
      ? `商品 ${formatNumber(config.limits.max_products)}`
      : null,
    config.limits.max_seconds !== null
      ? `时长 ${formatNumber(config.limits.max_seconds)} 秒`
      : null,
    config.task_type === "discovery" && config.limits.max_urls !== null
      ? `URL ${formatNumber(config.limits.max_urls)}`
      : null,
  ].filter((part): part is string => Boolean(part));
  const currentBudgetText =
    currentBudgetParts.length > 0 ? currentBudgetParts.join(" / ") : "不限";

  function patchForm(patch: Partial<RunConfigFormState>) {
    setForm((current) => ({ ...current, ...patch }));
    setLocalError("");
    setNotice("");
  }

  function buildChanges(action: "save" | "continue"): {
    body: WorkbenchRunConfigUpdate;
    error: string;
  } {
    const limits: Record<string, number | null> = {};
    const rate: Record<string, number> = {};
    let validationError = "";

    const optional = (
      key: keyof RunConfigFormState,
      limitKey: string,
      label: string,
      min: number,
      max: number,
    ) => {
      if (validationError || form[key].trim() === initial[key].trim()) return;
      const value = readOptional(form[key], label, min, max);
      if (typeof value === "string") {
        validationError = value;
        return;
      }
      limits[limitKey] = value;
    };
    const required = (
      key: keyof RunConfigFormState,
      target: Record<string, number>,
      targetKey: string,
      label: string,
      min: number,
      max: number,
    ) => {
      if (validationError || form[key].trim() === initial[key].trim()) return;
      const value = readRequired(form[key], label, min, max);
      if (typeof value === "string") {
        validationError = value;
        return;
      }
      target[targetKey] = value;
    };

    if (isFormal && !budgetEnabled) {
      if (config.limits.max_products !== null) limits.max_products = null;
      if (config.limits.max_seconds !== null) limits.max_seconds = null;
      if (config.task_type === "discovery" && config.limits.max_urls !== null) {
        limits.max_urls = null;
      }
    } else {
      optional("maxProducts", "max_products", "最大商品数", 1, 100000);
      optional("maxSeconds", "max_seconds", "最大时长", 1, 86400);
      if (config.task_type === "discovery") {
        optional("maxUrls", "max_urls", "最大 URL", 1, 100000);
      }
    }
    required(
      "maxAttempts",
      limits as unknown as Record<string, number>,
      "max_attempts",
      "最大尝试次数",
      1,
      10,
    );
    optional("maxNavigation", "max_navigation", "最大导航数", 1, 10000);
    optional("maxSitemaps", "max_sitemaps", "最大 sitemap 数", 1, 1000);
    required("concurrency", rate, "concurrency", "并发", 1, 8);
    required("perDomainRps", rate, "per_domain_rps", "每域 RPS", 0.1, 10);
    required("delayMs", rate, "delay_ms", "请求间隔", 0, 10000);
    if (validationError) return { body: {}, error: validationError };

    const hasRunChanges =
      Object.keys(limits).length > 0 || Object.keys(rate).length > 0;
    if (action === "save" && !hasRunChanges && !syncDefinition) {
      return { body: {}, error: "没有需要保存的修改" };
    }
    if (action === "save" && !editable && !canSaveDefinition) {
      return { body: {}, error: "该运行已结束且未关联任务定义，不能保存" };
    }
    if (action === "save" && !editable && !syncDefinition) {
      return {
        body: {},
        error: "已结束的运行只能同步到任务定义，请勾选同步",
      };
    }
    const body: WorkbenchRunConfigUpdate = {
      sync_definition: syncDefinition,
      action,
      reset_discovery: action === "continue" ? resetDiscovery : false,
    };
    if (Object.keys(limits).length > 0) {
      body.limits = limits as WorkbenchRunConfigUpdate["limits"];
    }
    if (Object.keys(rate).length > 0) {
      body.rate = rate as WorkbenchRunConfigUpdate["rate"];
    }
    return { body, error: "" };
  }

  async function submit(action: "save" | "continue") {
    if (busy || readOnly) return;
    const { body, error: validation } = buildChanges(action);
    if (validation) {
      setLocalError(validation);
      return;
    }
    setBusy(action);
    setLocalError("");
    setNotice("");
    try {
      const result = await updateWorkbenchRunConfig(config.task_id, body);
      onSaved(result);
      setNotice(
        result.applied.continued
          ? "已排入队列，保留此前已采结果。"
          : result.applied.definition && !result.applied.run
            ? "已保存到任务定义；历史运行限额不变。"
            : "运行配置已保存。",
      );
      if (result.warnings.length > 0) {
        setNotice(result.warnings.join(" "));
      }
    } catch (failure) {
      setLocalError(failure instanceof Error ? failure.message : "保存运行配置失败");
    } finally {
      setBusy("");
    }
  }

  const stateHint = editable
    ? config.state === "RUNNING"
      ? "预算在下一个工作项边界生效；并发、RPS 和请求间隔需暂停并继续后生效。"
      : "保存后在本运行恢复或领取时生效。"
    : config.can_continue
      ? "该运行已结束，但仍有可续采的剩余工作。"
      : "该运行已结束，保存只影响任务定义的下次运行。";

  return (
    <>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <span className="flex items-center gap-1.5 text-xs font-medium text-ink">
            <SlidersHorizontal size={14} aria-hidden="true" />
            运行配置
          </span>
          <Badge tone={taskStatusTone(config.state, config.outcome)}>
            {statusText}
          </Badge>
          <span className="font-mono text-[11px] text-ink-3">{config.task_id}</span>
          {config.definition ? (
            <span className="text-[11px] text-ink-3">
              定义：{config.definition.name}
            </span>
          ) : (
            <span className="text-[11px] text-ink-3">未加入任务树</span>
          )}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-ink-3">
          <span>
            已处理 <b className="tabular text-ink-2">{formatNumber(processed)}</b>
            {candidates > 0 ? (
              <>
                {" / "}
                <span className="tabular">{formatNumber(candidates)}</span>
              </>
            ) : null}
          </span>
          <span>
            待采 <b className="tabular text-ink-2">{formatNumber(pending)}</b>
          </span>
          <span>
            有效 <b className="tabular text-ink-2">{formatNumber(valid)}</b>
          </span>
          <span>
            失败 <b className="tabular text-ink-2">{formatNumber(failed)}</b>
          </span>
          <span>
            停止原因 <b className="text-ink-2">{stopReasonLabel(config.stop_reason)}</b>
          </span>
        </div>

        {config.stop_detail && config.stop_reason !== "NATURAL_END" ? (
          <div className="mt-2 flex items-start gap-2 rounded-control border border-warning/30 bg-warning-soft px-3 py-2 text-[11px] leading-5 text-ink-2">
            <AlertTriangle
              size={14}
              className="mt-0.5 shrink-0 text-warning"
              aria-hidden="true"
            />
            <span>{config.stop_detail}</span>
          </div>
        ) : null}

        {config.continue_hint && config.can_continue ? (
          <p className="mt-2 text-[11px] leading-5 text-ink-3">
            {config.continue_hint}
          </p>
        ) : null}

        {readOnly ? (
          <div className="mt-3">
            <ErrorNotice
              title="只读预览"
              message="当前服务以只读模式运行，不能修改运行配置。"
              compact
            />
          </div>
        ) : null}

        <div className="mt-3 grid gap-3 lg:grid-cols-2">
          <fieldset className="rounded-panel border border-line bg-surface-muted p-3">
            <legend className="px-1 text-xs font-medium text-ink-3">预算</legend>
            {isFormal ? (
              <div className="mb-2 flex items-start gap-2">
                <Checkbox
                  id="run-budget-enabled"
                  className="mt-0.5"
                  aria-describedby="run-budget-hint"
                  checked={budgetEnabled}
                  disabled={readOnly}
                  onChange={(event) => {
                    setBudgetEnabled(event.target.checked);
                    setLocalError("");
                  }}
                />
                <div className="min-w-0">
                  <label
                    htmlFor="run-budget-enabled"
                    className="text-[11px] leading-4 text-ink-2"
                  >
                    启用有限预算
                  </label>
                  <p
                    id="run-budget-hint"
                    className="mt-0.5 text-[10.5px] leading-4 text-ink-3"
                  >
                    {budgetEnabled
                      ? "开启后可填写商品数、时长和 URL；留空仍表示不限制。"
                      : currentBudgetText === "不限"
                        ? "关闭时不限制商品数、时长和 URL；当前已无限制。"
                        : `关闭时不限制商品数、时长和 URL；当前入队：${currentBudgetText}，保存后取消这些上限。`}
                  </p>
                </div>
              </div>
            ) : null}
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              {budgetEnabled ? (
                <>
                  <label className="text-[11px] text-ink-3" htmlFor="run-max-products">
                    最大商品数
                    <Input
                      id="run-max-products"
                      className="mt-1 h-8"
                      type="number"
                      min="1"
                      placeholder="不限制"
                      value={form.maxProducts}
                      disabled={readOnly}
                      onChange={(event) =>
                        patchForm({ maxProducts: event.target.value })
                      }
                    />
                  </label>
                  <label className="text-[11px] text-ink-3" htmlFor="run-max-seconds">
                    最大时长（秒）
                    <Input
                      id="run-max-seconds"
                      className="mt-1 h-8"
                      type="number"
                      min="1"
                      placeholder="不限制"
                      value={form.maxSeconds}
                      disabled={readOnly}
                      onChange={(event) =>
                        patchForm({ maxSeconds: event.target.value })
                      }
                    />
                  </label>
                  {config.task_type === "discovery" ? (
                    <label className="text-[11px] text-ink-3" htmlFor="run-max-urls">
                      最大 URL
                      <Input
                        id="run-max-urls"
                        className="mt-1 h-8"
                        type="number"
                        min="1"
                        placeholder="不限制"
                        value={form.maxUrls}
                        disabled={readOnly}
                        onChange={(event) => patchForm({ maxUrls: event.target.value })}
                      />
                    </label>
                  ) : null}
                </>
              ) : null}
              <label className="text-[11px] text-ink-3" htmlFor="run-max-attempts">
                最大尝试次数
                <Input
                  id="run-max-attempts"
                  className="mt-1 h-8"
                  type="number"
                  min="1"
                  max="10"
                  value={form.maxAttempts}
                  disabled={readOnly}
                  onChange={(event) => patchForm({ maxAttempts: event.target.value })}
                />
              </label>
            </div>
            <p className="mt-2 text-[10.5px] leading-4 text-ink-3">
              {isFormal
                ? budgetEnabled
                  ? "填写后启用有限预算；留空仍表示不限制。"
                  : "正式采集默认不设限；勾选“启用有限预算”后可填写商品数、时长和 URL。"
                : "留空表示不限制；时长 3600 秒 = 1 小时。"}
              {budgetEnabled || !isFormal
                ? "降低商品数或时长会在下一个工作项边界停止。"
                : null}
            </p>
          </fieldset>

          <fieldset className="rounded-panel border border-line bg-surface-muted p-3">
            <legend className="px-1 text-xs font-medium text-ink-3">速度与发现</legend>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-5">
              <label className="text-[11px] text-ink-3" htmlFor="run-concurrency">
                并发
                <Input
                  id="run-concurrency"
                  className="mt-1 h-8"
                  type="number"
                  min="1"
                  max="8"
                  value={form.concurrency}
                  disabled={readOnly}
                  onChange={(event) => patchForm({ concurrency: event.target.value })}
                />
              </label>
              <label className="text-[11px] text-ink-3" htmlFor="run-rps">
                每域 RPS
                <Input
                  id="run-rps"
                  className="mt-1 h-8"
                  type="number"
                  min="0.1"
                  max="10"
                  step="0.1"
                  value={form.perDomainRps}
                  disabled={readOnly}
                  onChange={(event) => patchForm({ perDomainRps: event.target.value })}
                />
              </label>
              <label className="text-[11px] text-ink-3" htmlFor="run-delay">
                请求间隔（毫秒）
                <Input
                  id="run-delay"
                  className="mt-1 h-8"
                  type="number"
                  min="0"
                  max="10000"
                  value={form.delayMs}
                  disabled={readOnly}
                  onChange={(event) => patchForm({ delayMs: event.target.value })}
                />
              </label>
              <label className="text-[11px] text-ink-3" htmlFor="run-max-navigation">
                最大导航数
                <Input
                  id="run-max-navigation"
                  className="mt-1 h-8"
                  type="number"
                  min="1"
                  value={form.maxNavigation}
                  disabled={readOnly}
                  onChange={(event) => patchForm({ maxNavigation: event.target.value })}
                />
              </label>
              <label className="text-[11px] text-ink-3" htmlFor="run-max-sitemaps">
                最大 sitemap 数
                <Input
                  id="run-max-sitemaps"
                  className="mt-1 h-8"
                  type="number"
                  min="1"
                  value={form.maxSitemaps}
                  disabled={readOnly}
                  onChange={(event) => patchForm({ maxSitemaps: event.target.value })}
                />
              </label>
            </div>
            <p className="mt-2 text-[10.5px] leading-4 text-ink-3">
              并发、RPS
              和请求间隔需暂停并继续后生效；发现上限对已结束的入口不会自动重跑。
            </p>
          </fieldset>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-2 text-[11px] text-ink-2">
          {config.definition ? (
            <div className="flex items-center gap-2">
              <Checkbox
                id="run-sync-definition"
                checked={syncDefinition}
                disabled={readOnly}
                onChange={(event) => {
                  setSyncDefinition(event.target.checked);
                  setLocalError("");
                }}
              />
              <label htmlFor="run-sync-definition">同步到任务定义，后续运行沿用</label>
            </div>
          ) : null}
          {config.can_continue ? (
            <div className="flex items-center gap-2">
              <Checkbox
                id="run-reset-discovery"
                checked={resetDiscovery}
                disabled={readOnly}
                onChange={(event) => {
                  setResetDiscovery(event.target.checked);
                  setLocalError("");
                }}
              />
              <label htmlFor="run-reset-discovery">
                重新发现（会重新请求入口、分类或 sitemap）
              </label>
            </div>
          ) : null}
        </div>

        <p className="mt-2 text-[10.5px] leading-5 text-ink-3">{stateHint}</p>
        {localError ? (
          <p className="mt-1 text-xs text-danger" role="alert">
            {localError}
          </p>
        ) : null}
        {notice ? (
          <p className="mt-1 text-xs text-success" role="status">
            {notice}
          </p>
        ) : null}
      </div>

      <footer className="flex flex-wrap items-center justify-end gap-2 border-t border-line bg-surface px-3 py-2">
        {config.can_continue ? (
          <Button
            variant="secondary"
            size="sm"
            disabled={!canSave || busy !== ""}
            onClick={() => void submit("save")}
          >
            <Save size={13} aria-hidden="true" />
            仅保存为下次运行
          </Button>
        ) : null}
        {config.can_continue ? (
          <Button
            variant="primary"
            size="sm"
            disabled={!canSave || busy !== ""}
            onClick={() => void submit("continue")}
          >
            <RotateCcw size={13} aria-hidden="true" />
            {busy === "continue" ? "续采中…" : "保存并继续采集"}
          </Button>
        ) : (
          <Button
            variant="primary"
            size="sm"
            disabled={!canSave || busy !== ""}
            onClick={() => void submit("save")}
          >
            <Save size={13} aria-hidden="true" />
            {busy === "save" ? "保存中…" : editable ? "保存并应用" : "保存为下次运行"}
          </Button>
        )}
      </footer>
    </>
  );
}
