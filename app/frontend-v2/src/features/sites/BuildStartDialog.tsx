import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Hammer, Wrench, X } from "lucide-react";
import {
  checkBuildModel,
  startSiteBuild,
  type BatchSite,
  type BuildConfig,
  type BuildModelHealth,
  type BuildResponse,
} from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { Checkbox, Input, Select } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { formatTime } from "../../lib/format";
import { modelRef as modelRefString, probeErrorLabels } from "../builds/modelHealth";

interface BuildStartDialogProps {
  open: boolean;
  batchId: string;
  site: BatchSite;
  config: BuildConfig | null;
  initialMode: "build" | "repair";
  onOpenChange: (open: boolean) => void;
  onStarted: (response: BuildResponse) => void;
}

export function BuildStartDialog({
  open,
  batchId,
  site,
  config,
  initialMode,
  onOpenChange,
  onStarted,
}: BuildStartDialogProps) {
  const queryClient = useQueryClient();
  const [mode] = useState<"build" | "repair">(initialMode);
  const [proxy, setProxy] = useState("");
  const [reason, setReason] = useState("");
  const [captureReasoning, setCaptureReasoning] = useState(
    Boolean(config?.reasoning_capture_enabled),
  );
  const [autoRepair, setAutoRepair] = useState(true);
  const [catalogFull, setCatalogFull] = useState(false);
  const [archiveSample, setArchiveSample] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [modelId, setModelId] = useState("");
  const [variantOverride, setVariantOverride] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkError, setCheckError] = useState("");
  const [checks, setChecks] = useState<Record<string, BuildModelHealth>>({});

  const available = config?.available !== false;
  const reasoningDisabled =
    Boolean(config && !config.reasoning_capture_enabled) || busy;
  const repairDisabled = Boolean(config && config.max_repair_rounds < 1) || busy;
  const isRepair = mode === "repair";
  const models = config?.models ?? [];
  const selected = models.find((model) => model.id === modelId);
  const variant = variantOverride ?? selected?.variant ?? "";
  const modelRef = modelId ? modelRefString(modelId, variant) : undefined;
  const blocked =
    !selected &&
    models.length > 0 &&
    models.every((model) => {
      const ref = modelRefString(model.id, model.variant);
      return (checks[ref] ?? model.health[model.variant])?.status === "failed";
    });

  async function runCheck() {
    if (!modelRef || !available || busy || checking) return;
    setChecking(true);
    setCheckError("");
    try {
      const result = await checkBuildModel(modelRef);
      setChecks((previous) => ({ ...previous, [modelRef]: result }));
      void queryClient.invalidateQueries({ queryKey: ["build-config"] });
    } catch (exc) {
      setCheckError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setChecking(false);
    }
  }

  async function runStart() {
    if (!available || busy || checking || blocked) return;
    setBusy(true);
    setError("");
    try {
      const response = await startSiteBuild(batchId, site.site_key, {
        mode,
        model_ref: modelRef,
        reason: isRepair ? reason.trim() || undefined : undefined,
        max_products: 6,
        max_seconds: catalogFull ? 900 : 600,
        proxy: proxy.trim() || undefined,
        capture_reasoning: captureReasoning && !reasoningDisabled,
        repair_rounds: autoRepair && !repairDisabled ? 1 : 0,
        archive_mode: archiveSample ? "sample" : "off",
        archive_sample_limit: 20,
        ...(isRepair
          ? {}
          : {
              catalog_scope: catalogFull ? ("full" as const) : ("sample" as const),
              catalog_products: 3000,
            }),
      });
      onStarted(response);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 flex max-h-[92vh] w-[min(680px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("build-start-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:gap-6 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                {isRepair ? <Wrench size={17} /> : <Hammer size={17} />}
              </span>
              <div>
                <Dialog.Title className="text-[22px] leading-8 font-semibold tracking-[-0.01em] text-ink">
                  {isRepair ? "重新验证／修复规则" : "启动方案构建"}
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  {isRepair
                    ? `把已安装规则和样例页交给构建 Agent，只做定向修复并重新验证；失败保留原规则和已有采集数据。`
                    : `构建会读取 ${site.domain}、生成候选规则并做有界验证；通过后站点才变为可采。`}
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭构建对话框"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6">
            {!available ? (
              <ErrorNotice
                title="构建不可用"
                message="服务端未配置构建 Agent。请用 --rules-dir 启动服务后再试。"
                compact
              />
            ) : null}

            {models.length === 0 ? (
              <p className="text-xs leading-5 text-ink-3">
                未配置模型池，本次使用默认模型；可在{" "}
                <a className="font-medium text-accent hover:underline" href="#/models">
                  模型配置
                </a>{" "}
                添加模型。
              </p>
            ) : null}

            {models.length > 0 ? (
              <fieldset
                className="min-w-0 space-y-2"
                disabled={busy || checking || !available}
              >
                <legend className="mb-1 text-sm font-medium text-ink">构建模型</legend>
                <div className="grid min-w-0 gap-2 sm:grid-cols-2">
                  <Select
                    aria-label="分配方式或模型"
                    value={modelId}
                    onChange={(event) => {
                      setModelId(event.target.value);
                      setVariantOverride(null);
                      setCheckError("");
                    }}
                  >
                    <option value="">均衡分配（默认）</option>
                    {models.map((model) => (
                      <option key={model.id} value={model.id}>
                        {model.label}
                      </option>
                    ))}
                  </Select>
                  {selected ? (
                    <Select
                      aria-label="思考等级"
                      value={variant}
                      onChange={(event) => {
                        setVariantOverride(event.target.value);
                        setCheckError("");
                      }}
                    >
                      {selected.variants.map((level) => (
                        <option key={level} value={level}>
                          {level || "供应商默认"}
                        </option>
                      ))}
                    </Select>
                  ) : null}
                </div>
                {!selected ? (
                  <p className="text-xs leading-5 text-ink-3">
                    按新建的站点规则构建或修复轮流分配。只分配一次，不影响已有规则的采集。
                  </p>
                ) : null}
                <ul
                  className="space-y-1 break-words text-xs leading-5 text-ink-2"
                  aria-live="polite"
                >
                  {(selected ? [selected] : models).map((model) => {
                    const level = selected ? variant : model.variant;
                    const ref = modelRefString(model.id, level);
                    const result = checks[ref] ?? model.health[level];
                    return (
                      <li key={model.id}>
                        {model.label} · {level || "供应商默认"} ·{" "}
                        {result
                          ? `${result.status === "ok" ? "探测通过" : "探测失败"} · ${formatTime(result.checked_at)} · ${result.latency_ms} ms${result.code ? ` · ${probeErrorLabels[result.code] ?? result.code}` : ""}`
                          : "已配置，尚未探测"}
                      </li>
                    );
                  })}
                </ul>
                {selected?.probe_supported ? (
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="secondary" onClick={() => void runCheck()}>
                      {checking ? "正在测试…" : "测试可用性"}
                    </Button>
                    <span className="text-xs text-ink-3">
                      不启动构建；短请求可能计费。
                    </span>
                  </div>
                ) : null}
                {checkError ? (
                  <ErrorNotice title="未完成探测" message={checkError} compact />
                ) : null}
                {blocked ? (
                  <p className="text-xs text-warning">
                    默认档位均探测失败。请选择模型重测，或手动指定。
                  </p>
                ) : null}
              </fieldset>
            ) : null}

            <div>
              <label
                className="mb-1 block text-xs font-medium text-ink-3"
                htmlFor="build-proxy"
              >
                出口代理（可选）
              </label>
              <Input
                id="build-proxy"
                value={proxy}
                placeholder="http://127.0.0.1:17211"
                autoComplete="off"
                spellCheck={false}
                disabled={busy}
                onChange={(event) => setProxy(event.target.value)}
              />
              <p className="mt-1 text-xs leading-5 text-ink-3">
                构建和主机验证使用同一出口；留空使用服务默认或直连。市场本地化价格请按批次市场选择出口。
              </p>
            </div>

            {isRepair ? (
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="build-reason"
                >
                  修复原因（可选）
                </label>
                <Input
                  id="build-reason"
                  value={reason}
                  placeholder="例如：产品描述只采到成分，缺少规格块"
                  autoComplete="off"
                  disabled={busy}
                  onChange={(event) => setReason(event.target.value)}
                />
                <p className="mt-1 text-xs leading-5 text-ink-3">
                  会作为修复 brief 发给构建
                  Agent；留空使用默认的“检查并补齐描述块和缺失字段”。
                </p>
              </div>
            ) : null}

            <div className="space-y-3 rounded-panel border border-line bg-surface-muted px-4 py-3">
              <label
                className="flex items-start gap-3"
                htmlFor="build-capture-reasoning"
              >
                <Checkbox
                  id="build-capture-reasoning"
                  className="mt-1"
                  checked={captureReasoning}
                  disabled={reasoningDisabled}
                  onChange={(event) => setCaptureReasoning(event.target.checked)}
                />
                <span>
                  <span className="block text-sm font-medium text-ink">实时思考</span>
                  <span className="mt-0.5 block text-xs leading-5 text-ink-3">
                    在构建时间线里实时显示模型思考；默认只用于本次展示，不写入
                    trace。需服务端以
                    <code className="mx-1 rounded bg-surface px-1 font-mono text-[11px]">
                      ECOM_BUILD_CAPTURE_REASONING=1
                    </code>
                    启动。
                    {config && !config.reasoning_capture_enabled
                      ? "当前服务端未开启，勾选不会生效。"
                      : ""}
                  </span>
                </span>
              </label>

              <label className="flex items-start gap-3" htmlFor="build-auto-repair">
                <Checkbox
                  id="build-auto-repair"
                  className="mt-1"
                  checked={autoRepair}
                  disabled={repairDisabled}
                  onChange={(event) => setAutoRepair(event.target.checked)}
                />
                <span>
                  <span className="block text-sm font-medium text-ink">
                    验证失败后自动修复 1 轮
                  </span>
                  <span className="mt-0.5 block text-xs leading-5 text-ink-3">
                    预检规则选择器；验证失败时把精确错误回给同一模型会话修复一次，再重新验证。会多一次模型调用。
                    {config && config.max_repair_rounds < 1
                      ? "当前服务端未启用自动修复。"
                      : ""}
                  </span>
                </span>
              </label>

              {!isRepair ? (
                <label className="flex items-start gap-3" htmlFor="build-catalog-full">
                  <Checkbox
                    id="build-catalog-full"
                    className="mt-1"
                    checked={catalogFull}
                    disabled={busy}
                    onChange={(event) => setCatalogFull(event.target.checked)}
                  />
                  <span>
                    <span className="block text-sm font-medium text-ink">全量目录</span>
                    <span className="mt-0.5 block text-xs leading-5 text-ink-3">
                      按顶层分类和分页生成发现源；目标商品数按 3000
                      写入规则。构建仍只验证 6 个商品，通过后再从批次详情启动全量任务。
                    </span>
                  </span>
                </label>
              ) : null}

              <label className="flex items-start gap-3" htmlFor="build-archive-sample">
                <Checkbox
                  id="build-archive-sample"
                  className="mt-1"
                  checked={archiveSample}
                  disabled={busy}
                  onChange={(event) => setArchiveSample(event.target.checked)}
                />
                <span>
                  <span className="block text-sm font-medium text-ink">
                    归档样例页面
                  </span>
                  <span className="mt-0.5 block text-xs leading-5 text-ink-3">
                    入口／分类／商品页，最多 20 页；后续规则复验优先复用，减少重复请求。
                  </span>
                </span>
              </label>
            </div>

            <p className="rounded-control border border-warning/25 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning">
              构建会调用模型并产生费用；构建会话与采集任务分开，默认只运行一个构建。
            </p>

            {error ? (
              <ErrorNotice title="构建启动失败" message={error} compact />
            ) : null}
          </div>

          <footer className="flex flex-col items-start gap-3 border-t border-line px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <p className="text-xs text-ink-3">
              {isRepair
                ? "修复失败会保留原规则和已有采集数据。"
                : "构建完成后自动做一次有界验证；失败会保留原因。"}
            </p>
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
              <Button
                id="build-start-cancel"
                variant="ghost"
                onClick={() => onOpenChange(false)}
                disabled={busy}
              >
                取消
              </Button>
              <Button
                variant="primary"
                onClick={() => void runStart()}
                disabled={!available || busy || checking || blocked}
              >
                {busy ? "启动中…" : isRepair ? "启动修复" : "启动构建"}
              </Button>
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
