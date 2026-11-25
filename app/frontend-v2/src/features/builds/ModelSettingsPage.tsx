import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Plus,
  RefreshCw,
  Save,
  Search,
  Star,
  Trash2,
} from "lucide-react";
import {
  checkBuildModel,
  getAvailableBuildModels,
  getBuildConfig,
  resetBuildModels,
  updateBuildModels,
  type AvailableBuildModel,
  type BuildConfig,
  type BuildModelHealth,
  type BuildModelOption,
} from "../../lib/api";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { Input, Select } from "../../components/ui/Input";
import { PageHeader } from "../../components/ui/PageHeader";
import { formatNumber, formatTime, type Tone } from "../../lib/format";
import { modelRef, probeErrorLabels } from "./modelHealth";

interface DraftModel {
  id: string;
  variant: string;
}

const SOURCE_LABELS: Record<string, string> = {
  settings: "页面配置",
  env: "环境变量",
  none: "未配置",
};

const SOURCE_TONES: Record<string, Tone> = {
  settings: "info",
  env: "neutral",
  none: "warning",
};

const PREFERRED_VARIANTS = ["medium", "high", "low"];
const AVAILABLE_PAGE_SIZE = 20;
const PAGE_SIZE_OPTIONS = [10, 20, 50];
type PageItem = number | "ellipsis";
type MetadataFilter = "all" | "known" | "unknown" | "probe";
type PoolFilter = "all" | "available" | "inPool";

function providerOf(model: AvailableBuildModel): string {
  return model.provider || model.id.split("/")[0] || "unknown";
}

function paginationItems(current: number, total: number): PageItem[] {
  if (total <= 7) {
    return Array.from({ length: total }, (_, index) => index + 1);
  }
  const pages = [...new Set([1, current - 1, current, current + 1, total])]
    .filter((page) => page >= 1 && page <= total)
    .sort((left, right) => left - right);
  const items: PageItem[] = [];
  let previous = 0;
  for (const page of pages) {
    if (previous && page - previous > 1) items.push("ellipsis");
    items.push(page);
    previous = page;
  }
  return items;
}

function toDraft(models: BuildModelOption[] | undefined): DraftModel[] {
  return (models ?? []).map((model) => ({
    id: model.id,
    variant: model.variant,
  }));
}

function draftKey(models: DraftModel[]): string {
  return models.map((model) => modelRef(model.id, model.variant)).join("\n");
}

function preferredVariant(variants: string[]): string {
  return (
    PREFERRED_VARIANTS.find((variant) => variants.includes(variant)) ??
    variants[0] ??
    ""
  );
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function probeResultText(result: BuildModelHealth | undefined): string {
  if (!result) return "";
  const verdict = result.status === "ok" ? "探测通过" : "探测失败";
  const detail = result.code
    ? ` · ${probeErrorLabels[result.code] ?? result.code}`
    : "";
  return `${verdict} · ${formatTime(result.checked_at)} · ${result.latency_ms} ms${detail}`;
}

function modelLimitText(entry: AvailableBuildModel): string {
  const bits = [`供应商：${entry.provider}`];
  bits.push(
    `档位：${entry.variants.length ? entry.variants.join(" / ") : "供应商默认"}`,
  );
  if (entry.context_window) {
    bits.push(`上下文：${formatNumber(entry.context_window)}`);
  }
  if (entry.max_output_tokens) {
    bits.push(`输出：${formatNumber(entry.max_output_tokens)}`);
  }
  return bits.join(" · ");
}

function modelCapabilityText(entry: AvailableBuildModel): string {
  if (!entry.capabilities) return "";
  const bits = [entry.capabilities.tools ? "工具：支持" : "工具：不支持"];
  if (entry.capabilities.input.length) {
    bits.push(`输入：${entry.capabilities.input.join(" / ")}`);
  }
  return bits.join(" · ");
}

interface ModelSettingsFormProps {
  config: BuildConfig;
  refreshing: boolean;
  onRefresh: () => void;
}

function ModelSettingsForm({ config, refreshing, onRefresh }: ModelSettingsFormProps) {
  const queryClient = useQueryClient();
  const modelsQuery = useQuery({
    queryKey: ["build-models"],
    queryFn: () => getAvailableBuildModels(false),
    staleTime: 60_000,
  });
  const catalog = useMemo(() => config.model_catalog ?? [], [config.model_catalog]);
  const savedModels = useMemo(() => config.models ?? [], [config.models]);
  const savedByKey = useMemo(
    () => new Map(savedModels.map((model) => [model.id, model])),
    [savedModels],
  );
  const discoveredByKey = useMemo(
    () => new Map((modelsQuery.data?.models ?? []).map((model) => [model.id, model])),
    [modelsQuery.data],
  );

  const [draft, setDraft] = useState<DraftModel[]>(() => toDraft(config.models));
  const [defaultRef, setDefaultRef] = useState(config.default_model ?? "");
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [checking, setChecking] = useState("");
  const [checks, setChecks] = useState<Record<string, BuildModelHealth>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [preset, setPreset] = useState("");
  const [presetVariant, setPresetVariant] = useState("");
  const [customRef, setCustomRef] = useState("");
  const [customVariant, setCustomVariant] = useState("");
  const [modelSearch, setModelSearch] = useState("");
  const [providerFilter, setProviderFilter] = useState("all");
  const [metadataFilter, setMetadataFilter] = useState<MetadataFilter>("all");
  const [poolFilter, setPoolFilter] = useState<PoolFilter>("all");
  const [availablePageSize, setAvailablePageSize] = useState(AVAILABLE_PAGE_SIZE);
  const [availablePageNumber, setAvailablePageNumber] = useState(1);
  const [pageJump, setPageJump] = useState("");
  const [refreshingAvailable, setRefreshingAvailable] = useState(false);

  const editable = Boolean(config.model_pool_editable);
  const hasOverride = Boolean(config.model_pool_override);
  const source = config.model_pool_source ?? "none";
  const presetEntry = catalog.find((entry) => entry.id === preset);
  const savedDefault = config.default_model ?? "";
  const dirty =
    draftKey(draft) !== draftKey(toDraft(savedModels)) || defaultRef !== savedDefault;
  const busy = saving || resetting || Boolean(checking);
  const discoveredModels = useMemo(
    () => modelsQuery.data?.models ?? [],
    [modelsQuery.data],
  );
  const inPool = useMemo(() => new Set(draft.map((model) => model.id)), [draft]);
  const poolByKey = useMemo(
    () => new Map(draft.map((model) => [model.id, model])),
    [draft],
  );
  const providers = useMemo(
    () =>
      [...new Set(discoveredModels.map(providerOf))].sort((left, right) =>
        left.localeCompare(right),
      ),
    [discoveredModels],
  );
  const providerCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const model of discoveredModels) {
      const provider = providerOf(model);
      counts.set(provider, (counts.get(provider) ?? 0) + 1);
    }
    return counts;
  }, [discoveredModels]);
  const metadataCounts = useMemo(() => {
    let known = 0;
    let unknown = 0;
    let probe = 0;
    for (const model of discoveredModels) {
      if (model.known) known += 1;
      else unknown += 1;
      if (model.probe_supported) probe += 1;
    }
    return { known, unknown, probe };
  }, [discoveredModels]);
  const inPoolDiscoveredCount = useMemo(
    () =>
      discoveredModels.reduce(
        (count, model) => count + (inPool.has(model.id) ? 1 : 0),
        0,
      ),
    [discoveredModels, inPool],
  );
  const availableModels = useMemo(() => {
    const query = modelSearch.trim().toLowerCase();
    return discoveredModels.filter((item) => {
      if (providerFilter !== "all" && providerOf(item) !== providerFilter) return false;
      if (metadataFilter === "known" && !item.known) return false;
      if (metadataFilter === "unknown" && item.known) return false;
      if (metadataFilter === "probe" && !item.probe_supported) return false;
      const added = inPool.has(item.id);
      if (poolFilter === "available" && added) return false;
      if (poolFilter === "inPool" && !added) return false;
      if (!query) return true;
      return [item.id, item.label, item.provider].some((value) =>
        value.toLowerCase().includes(query),
      );
    });
  }, [
    discoveredModels,
    inPool,
    metadataFilter,
    modelSearch,
    poolFilter,
    providerFilter,
  ]);
  const availableError =
    modelsQuery.data?.error ??
    (modelsQuery.isError ? errorText(modelsQuery.error) : "");
  const discoveredCount = discoveredModels.length;
  const hasAvailableFilters =
    Boolean(modelSearch.trim()) ||
    providerFilter !== "all" ||
    metadataFilter !== "all" ||
    poolFilter !== "all";
  const totalPages = Math.max(1, Math.ceil(availableModels.length / availablePageSize));
  const currentPage = Math.min(Math.max(1, availablePageNumber), totalPages);
  const pageStart = (currentPage - 1) * availablePageSize;
  const pageModels = availableModels.slice(pageStart, pageStart + availablePageSize);

  function applyConfig(next: BuildConfig) {
    queryClient.setQueryData(["build-config"], next);
    setDraft(toDraft(next.models));
    setDefaultRef(next.default_model ?? "");
  }

  function updateDraft(next: DraftModel[]) {
    setDraft(next);
    setNotice("");
  }

  function addCandidate(candidate: DraftModel, knownVariants?: string[]): boolean {
    setError("");
    setNotice("");
    const id = candidate.id.trim();
    if (!id) {
      setError("请输入模型引用，格式为 provider/model#variant。");
      return false;
    }
    const entry = catalog.find((item) => item.id === id);
    const choices = knownVariants ?? entry?.variants;
    const variant =
      choices && choices.length > 0
        ? candidate.variant || preferredVariant(choices)
        : candidate.variant;
    if (choices && choices.length > 0 && !choices.includes(variant)) {
      setError("请选择该模型支持的思考等级。");
      return false;
    }
    if (draft.some((item) => item.id === id)) {
      setError("该模型已在模型池中；每个模型只能配置一次。");
      return false;
    }
    updateDraft([...draft, { id, variant }]);
    return true;
  }

  function addModel() {
    let candidate: DraftModel | null = null;
    if (preset) {
      candidate = { id: preset, variant: presetVariant };
    } else {
      const raw = customRef.trim();
      if (raw) {
        const [id, ...rest] = raw.split("#");
        candidate = {
          id: id.trim(),
          variant: rest.join("#").trim() || customVariant.trim(),
        };
      }
    }
    if (!candidate || !addCandidate(candidate)) return;
    setPreset("");
    setPresetVariant("");
    setCustomRef("");
    setCustomVariant("");
  }

  function addAvailable(entry: AvailableBuildModel) {
    if (
      !addCandidate(
        { id: entry.id, variant: preferredVariant(entry.variants) },
        entry.variants,
      )
    ) {
      return;
    }
    setNotice(`${entry.label} 已加入模型池；保存后生效。`);
  }

  function updateSearch(next: string) {
    setModelSearch(next);
    setAvailablePageNumber(1);
    setPageJump("");
  }

  function updateProviderFilter(next: string) {
    setProviderFilter(next);
    setAvailablePageNumber(1);
    setPageJump("");
  }

  function updateMetadataFilter(next: MetadataFilter) {
    setMetadataFilter(next);
    setAvailablePageNumber(1);
    setPageJump("");
  }

  function updatePoolFilter(next: PoolFilter) {
    setPoolFilter(next);
    setAvailablePageNumber(1);
    setPageJump("");
  }

  function updatePageSize(next: number) {
    setAvailablePageSize(next);
    setAvailablePageNumber(1);
    setPageJump("");
  }

  function jumpToPage() {
    const parsed = Number.parseInt(pageJump, 10);
    if (!Number.isFinite(parsed)) return;
    setAvailablePageNumber(Math.min(Math.max(1, parsed), totalPages));
    setPageJump("");
  }

  function clearAvailableFilters() {
    setModelSearch("");
    setProviderFilter("all");
    setMetadataFilter("all");
    setPoolFilter("all");
    setAvailablePageNumber(1);
    setPageJump("");
  }

  function scrollToPool() {
    const heading = document.getElementById("model-pool-heading");
    heading?.scrollIntoView({ block: "start" });
    heading?.focus({ preventScroll: true });
  }

  async function refreshAvailable() {
    setRefreshingAvailable(true);
    setError("");
    try {
      const next = await getAvailableBuildModels(true);
      queryClient.setQueryData(["build-models"], next);
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setRefreshingAvailable(false);
    }
  }

  function removeModel(id: string) {
    const removed = draft.find((item) => item.id === id);
    if (removed && defaultRef === modelRef(removed.id, removed.variant)) {
      setDefaultRef("");
    }
    updateDraft(draft.filter((item) => item.id !== id));
  }

  function changeVariant(id: string, variant: string) {
    const current = draft.find((item) => item.id === id);
    if (current && defaultRef === modelRef(current.id, current.variant)) {
      setDefaultRef(modelRef(current.id, variant));
    }
    updateDraft(draft.map((item) => (item.id === id ? { ...item, variant } : item)));
  }

  function chooseDefault(ref: string, label: string) {
    setError("");
    setDefaultRef(ref);
    setNotice(`已将 ${label} 设为默认模型；保存后生效。`);
  }

  async function save() {
    if (!editable || saving || checking) return;
    setSaving(true);
    setError("");
    setNotice("");
    try {
      const next = await updateBuildModels(
        draft.map((item) => modelRef(item.id, item.variant)),
        defaultRef || null,
      );
      applyConfig(next);
      setNotice(
        "模型池和默认模型已保存；新构建会使用新配置，已排队和运行中的构建保持入队时锁定的模型。",
      );
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setSaving(false);
    }
  }

  async function reset() {
    if (!editable || resetting || checking) return;
    setResetting(true);
    setError("");
    setNotice("");
    try {
      const next = await resetBuildModels();
      applyConfig(next);
      setNotice("已恢复为服务启动时的环境变量配置。");
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setResetting(false);
    }
  }

  async function runProbe(ref: string) {
    if (!editable || checking) return;
    setChecking(ref);
    setError("");
    try {
      const result = await checkBuildModel(ref);
      setChecks((previous) => ({ ...previous, [ref]: result }));
      void queryClient.invalidateQueries({ queryKey: ["build-config"] });
    } catch (exc) {
      setError(errorText(exc));
    } finally {
      setChecking("");
    }
  }

  async function probe(item: DraftModel) {
    await runProbe(modelRef(item.id, item.variant));
  }

  async function probeAvailable(entry: AvailableBuildModel) {
    await runProbe(modelRef(entry.id, preferredVariant(entry.variants)));
  }

  function probeText(item: DraftModel, saved: BuildModelOption | undefined): string {
    const ref = modelRef(item.id, item.variant);
    if (checking === ref) return "测试中…";
    return probeResultText(checks[ref] ?? saved?.health[item.variant]) || "尚未探测";
  }

  function availableProbeText(entry: AvailableBuildModel): string {
    if (!entry.probe_supported) return "不可测试";
    const ref = modelRef(entry.id, preferredVariant(entry.variants));
    if (checking === ref) return "测试中…";
    return probeResultText(checks[ref]) || "尚未测试";
  }

  const sourceDescription =
    source === "settings"
      ? "配置保存在本地账本中；保存后新构建立即使用，已排队和运行中的构建保持入队时锁定的模型。"
      : source === "env"
        ? "当前来自服务进程的 ECOM_BUILD_MODEL_POOL；在页面保存后，页面配置优先。"
        : "尚未配置模型池，新构建使用单一默认模型。";

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="构建设置"
        title="模型配置"
        description="从 OpenCode 读取模型名称、思考档位、上下文和可用性；管理活动模型池、固定或轮询分配，并可在加入前测试。凭据仍由 OpenCode 解析，本页不保存 API Key。"
        actions={
          <Button onClick={onRefresh} disabled={refreshing || busy}>
            <RefreshCw
              size={14}
              aria-hidden="true"
              className={refreshing ? "animate-spin" : undefined}
            />
            刷新
          </Button>
        }
      />

      {error ? (
        <InlineNotice tone="danger" title="操作未完成">
          {error}
        </InlineNotice>
      ) : null}
      {notice ? (
        <InlineNotice tone="success" title="已更新">
          {notice}
        </InlineNotice>
      ) : null}
      {!editable ? (
        <InlineNotice tone="warning" title="当前配置只读">
          服务以只读模式启动，或构建服务已停用；只能查看模型池，不能保存修改。
        </InlineNotice>
      ) : null}

      <section
        id="model-pool"
        aria-label="模型池"
        className="scroll-mt-4 rounded-panel border border-line bg-surface"
      >
        <div className="flex flex-col gap-3 border-b border-line px-4 py-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2
                id="model-pool-heading"
                tabIndex={-1}
                className="text-[17px] leading-6 font-semibold text-ink"
              >
                模型池
              </h2>
              <Badge tone={SOURCE_TONES[source] ?? "neutral"} dot={false}>
                {SOURCE_LABELS[source] ?? source}
              </Badge>
              <span className="text-xs text-ink-3">{draft.length} 个模型</span>
            </div>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">
              {sourceDescription}
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              onClick={() => void reset()}
              disabled={!editable || busy || !hasOverride}
            >
              {resetting ? "恢复中…" : "恢复环境变量配置"}
            </Button>
            <Button
              variant="primary"
              onClick={() => void save()}
              disabled={!editable || busy || !dirty}
            >
              <Save size={14} aria-hidden="true" />
              {saving ? "保存中…" : "保存配置"}
            </Button>
          </div>
        </div>

        <div className="flex flex-col gap-3 border-b border-line px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <p id="assignment-label" className="text-sm font-medium text-ink">
              分配方式
            </p>
            <p className="mt-0.5 text-xs leading-5 text-ink-3">
              固定后新构建和修复始终使用该模型；轮询按入队顺序分配。已排队和运行中的构建保持锁定。
            </p>
            <div
              role="radiogroup"
              aria-labelledby="assignment-label"
              className="mt-2 flex flex-wrap gap-4"
            >
              <label className="flex items-center gap-2 text-sm text-ink-2">
                <input
                  type="radio"
                  name="model-assignment"
                  checked={!defaultRef}
                  disabled={!editable || busy}
                  onChange={() => {
                    setDefaultRef("");
                    setNotice("");
                  }}
                />
                轮询全部模型
              </label>
              <label className="flex items-center gap-2 text-sm text-ink-2">
                <input
                  type="radio"
                  name="model-assignment"
                  checked={Boolean(defaultRef)}
                  disabled={!editable || busy || draft.length === 0}
                  onChange={() => {
                    const first = draft[0];
                    if (first) {
                      setDefaultRef(modelRef(first.id, first.variant));
                      setNotice("");
                    }
                  }}
                />
                固定默认模型
              </label>
            </div>
          </div>
          {defaultRef ? (
            <Select
              aria-label="默认模型"
              className="h-9 w-full shrink-0 sm:w-80"
              value={defaultRef}
              disabled={!editable || busy || draft.length === 0}
              onChange={(event) => {
                setDefaultRef(event.target.value);
                setNotice("");
              }}
            >
              {draft.map((item) => {
                const entry = catalog.find((model) => model.id === item.id);
                const discovered = discoveredByKey.get(item.id);
                const label =
                  entry?.label ??
                  savedByKey.get(item.id)?.label ??
                  (discovered?.known ? discovered.label : undefined) ??
                  item.id;
                return (
                  <option
                    key={modelRef(item.id, item.variant)}
                    value={modelRef(item.id, item.variant)}
                  >
                    {label}
                    {item.variant ? ` · ${item.variant}` : ""}
                  </option>
                );
              })}
            </Select>
          ) : null}
        </div>

        {draft.length === 0 ? (
          <EmptyState
            title="模型池为空"
            description="不配置模型池时，构建和修复使用单一的默认模型。添加模型后可选择固定默认模型，或保留轮询。"
          />
        ) : (
          <ul className="divide-y divide-line">
            {draft.map((item) => {
              const saved = savedByKey.get(item.id);
              const entry = catalog.find((model) => model.id === item.id);
              const discovered = discoveredByKey.get(item.id);
              const label =
                entry?.label ??
                saved?.label ??
                (discovered?.known ? discovered.label : undefined) ??
                item.id;
              const hasMetadata = Boolean(entry || saved?.known || discovered?.known);
              const variants = entry?.variants?.length
                ? entry.variants
                : saved?.variants?.length
                  ? saved.variants
                  : discovered?.variants?.length
                    ? discovered.variants
                    : [item.variant || ""];
              const variantOptions = variants.includes(item.variant)
                ? variants
                : [item.variant, ...variants];
              const supported =
                entry?.probe_supported ??
                saved?.probe_supported ??
                discovered?.probe_supported ??
                false;
              const contextWindow = saved?.context_window ?? discovered?.context_window;
              const maxOutput =
                saved?.max_output_tokens ?? discovered?.max_output_tokens;
              const capabilities = saved?.capabilities ?? discovered?.capabilities;
              const limitText = [
                contextWindow ? `上下文 ${formatNumber(contextWindow)}` : "",
                maxOutput ? `输出 ${formatNumber(maxOutput)}` : "",
                capabilities?.tools ? "工具：支持" : "",
              ]
                .filter(Boolean)
                .join(" · ");
              const ref = modelRef(item.id, item.variant);
              const canProbe = editable && supported;
              return (
                <li
                  key={item.id}
                  className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-start sm:justify-between"
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-semibold text-ink">{label}</p>
                      <code className="break-all font-mono text-[11px] text-ink-3">
                        {item.id}
                      </code>
                      {defaultRef === ref ? (
                        <Badge tone="info" dot={false}>
                          默认
                        </Badge>
                      ) : null}
                    </div>
                    {limitText ? (
                      <p className="mt-1 text-xs leading-5 text-ink-3">{limitText}</p>
                    ) : null}
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <label className="flex items-center gap-2 text-xs text-ink-3">
                        <span>默认思考等级</span>
                        {hasMetadata ? (
                          <Select
                            className="h-8 w-36"
                            aria-label={`${label} 默认思考等级`}
                            value={item.variant}
                            disabled={!editable || busy}
                            onChange={(event) =>
                              changeVariant(item.id, event.target.value)
                            }
                          >
                            {variantOptions.map((variant) => (
                              <option key={variant} value={variant}>
                                {variant || "供应商默认"}
                              </option>
                            ))}
                          </Select>
                        ) : (
                          <Input
                            className="h-8 w-40"
                            aria-label={`${label} 默认思考等级`}
                            value={item.variant}
                            placeholder="供应商默认"
                            disabled={!editable || busy}
                            onChange={(event) =>
                              changeVariant(item.id, event.target.value)
                            }
                          />
                        )}
                      </label>
                      <span className="text-xs text-ink-3">
                        {probeText(item, saved)}
                      </span>
                    </div>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {defaultRef !== ref ? (
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={!editable || busy}
                        onClick={() => chooseDefault(ref, label)}
                      >
                        <Star size={14} aria-hidden="true" />
                        设为默认
                      </Button>
                    ) : null}
                    {supported ? (
                      <Button
                        size="sm"
                        onClick={() => void probe(item)}
                        disabled={!canProbe || busy}
                        title={
                          canProbe
                            ? "发送一个有界的合成文本请求"
                            : "当前配置只读或模型不可测试"
                        }
                      >
                        {checking === ref ? "测试中…" : "测试可用性"}
                      </Button>
                    ) : (
                      <span className="text-xs text-ink-3">未配置小请求探测</span>
                    )}
                    <Button
                      variant="ghost"
                      size="sm"
                      aria-label={`移除 ${label}`}
                      disabled={!editable || busy}
                      onClick={() => removeModel(item.id)}
                    >
                      <Trash2 size={14} aria-hidden="true" />
                    </Button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section
        aria-label="可用模型"
        className="rounded-panel border border-line bg-surface"
      >
        <div className="flex flex-col gap-3 border-b border-line px-4 py-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <h2 className="text-[17px] leading-6 font-semibold text-ink">可用模型</h2>
            <p className="mt-1 text-sm leading-6 text-ink-2">
              从 OpenCode
              的模型快照读取名称、思考档位、上下文和模态；刷新不会发送模型请求，也不读取密钥。
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={scrollToPool}
              disabled={draft.length === 0}
            >
              查看模型池（{draft.length}）
            </Button>
            <Button
              size="sm"
              onClick={() => void refreshAvailable()}
              disabled={refreshingAvailable}
            >
              <RefreshCw
                size={14}
                aria-hidden="true"
                className={refreshingAvailable ? "animate-spin" : undefined}
              />
              {refreshingAvailable ? "读取中…" : "刷新可用模型"}
            </Button>
          </div>
        </div>
        <div className="space-y-3 px-4 py-4">
          <div className="space-y-3">
            <div className="relative">
              <Search
                size={15}
                aria-hidden="true"
                className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-3"
              />
              <Input
                aria-label="搜索可用模型"
                className="pl-9"
                placeholder="搜索供应商、模型或标签"
                value={modelSearch}
                onChange={(event) => updateSearch(event.target.value)}
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Select
                aria-label="按供应商筛选"
                value={providerFilter}
                disabled={modelsQuery.isPending || discoveredCount === 0}
                onChange={(event) => updateProviderFilter(event.target.value)}
              >
                <option value="all">
                  全部供应商（{formatNumber(discoveredCount)}）
                </option>
                {providers.map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}（{formatNumber(providerCounts.get(provider) ?? 0)}）
                  </option>
                ))}
              </Select>
              <Select
                aria-label="按元数据状态筛选"
                value={metadataFilter}
                disabled={modelsQuery.isPending || discoveredCount === 0}
                onChange={(event) =>
                  updateMetadataFilter(event.target.value as MetadataFilter)
                }
              >
                <option value="all">全部状态（{formatNumber(discoveredCount)}）</option>
                <option value="known">
                  OpenCode 元数据（{formatNumber(metadataCounts.known)}）
                </option>
                <option value="unknown">
                  缺少元数据（{formatNumber(metadataCounts.unknown)}）
                </option>
                <option value="probe">
                  可测试（{formatNumber(metadataCounts.probe)}）
                </option>
              </Select>
              <Select
                aria-label="按模型池状态筛选"
                value={poolFilter}
                disabled={modelsQuery.isPending || discoveredCount === 0}
                onChange={(event) => updatePoolFilter(event.target.value as PoolFilter)}
              >
                <option value="all">全部模型（{formatNumber(discoveredCount)}）</option>
                <option value="available">
                  未加入（{formatNumber(discoveredCount - inPoolDiscoveredCount)}）
                </option>
                <option value="inPool">
                  已在模型池（{formatNumber(inPoolDiscoveredCount)}）
                </option>
              </Select>
            </div>
          </div>
          {availableError ? (
            <p className="text-xs leading-5 text-danger">
              读取可用模型失败：{availableError}
            </p>
          ) : null}
          {modelsQuery.isPending ? (
            <p className="text-xs leading-5 text-ink-3" role="status">
              正在读取 OpenCode 模型…
            </p>
          ) : discoveredCount === 0 ? (
            <p className="text-xs leading-5 text-ink-3">
              OpenCode 没有返回可用模型；仍可在下方手动添加引用。
            </p>
          ) : availableModels.length === 0 ? (
            <div className="flex flex-col gap-2 rounded-control border border-dashed border-line px-3 py-4 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-ink-3">没有匹配的可用模型。</p>
              <Button
                size="sm"
                variant="ghost"
                className="shrink-0"
                onClick={clearAvailableFilters}
              >
                清除筛选
              </Button>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
                <p className="text-xs leading-5 text-ink-3" role="status">
                  共 {formatNumber(discoveredCount)} 个模型
                  {hasAvailableFilters
                    ? `，筛选后 ${formatNumber(availableModels.length)} 个`
                    : ""}
                </p>
                <p className="text-xs leading-5 text-ink-3">
                  显示第 {formatNumber(pageStart + 1)}–
                  {formatNumber(pageStart + pageModels.length)} 个
                </p>
              </div>
              <ul className="divide-y divide-line rounded-control border border-line">
                {pageModels.map((entry) => {
                  const pooled = poolByKey.get(entry.id);
                  const added = Boolean(pooled);
                  const pooledRef = pooled ? modelRef(pooled.id, pooled.variant) : "";
                  const isDefault = added && defaultRef === pooledRef;
                  const probeRef = modelRef(entry.id, preferredVariant(entry.variants));
                  return (
                    <li
                      key={entry.id}
                      className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-2">
                          <p className="text-sm font-semibold text-ink">
                            {entry.label}
                          </p>
                          <Badge tone={entry.known ? "info" : "neutral"} dot={false}>
                            {entry.known ? "OpenCode 元数据" : "缺少元数据"}
                          </Badge>
                          {added ? (
                            <Badge tone="success" dot={false}>
                              已在模型池
                            </Badge>
                          ) : null}
                        </div>
                        <code className="mt-0.5 block break-all font-mono text-[11px] text-ink-3">
                          {entry.id}
                        </code>
                        {entry.known ? (
                          <>
                            <p className="mt-1 text-xs leading-5 text-ink-3">
                              {modelLimitText(entry)}
                            </p>
                            {modelCapabilityText(entry) ? (
                              <p className="mt-0.5 text-xs leading-5 text-ink-3">
                                {modelCapabilityText(entry)}
                              </p>
                            ) : null}
                          </>
                        ) : (
                          <p className="mt-1 text-xs leading-5 text-ink-3">
                            OpenCode
                            未返回该模型的名称、档位或上下文元数据；可加入后手动填写档位。
                          </p>
                        )}
                        {!added ? (
                          <p className="mt-0.5 text-xs leading-5 text-ink-3">
                            {availableProbeText(entry)}
                          </p>
                        ) : null}
                      </div>
                      {added ? (
                        isDefault ? (
                          <Badge
                            tone="info"
                            dot={false}
                            className="shrink-0 self-start sm:self-auto"
                          >
                            当前默认
                          </Badge>
                        ) : (
                          <Button
                            size="sm"
                            variant="secondary"
                            className="shrink-0"
                            disabled={!editable || busy}
                            onClick={() => chooseDefault(pooledRef, entry.label)}
                          >
                            <Star size={14} aria-hidden="true" />
                            设为默认
                          </Button>
                        )
                      ) : (
                        <div className="flex shrink-0 flex-wrap items-center gap-2">
                          {entry.probe_supported ? (
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={!editable || busy}
                              onClick={() => void probeAvailable(entry)}
                            >
                              {checking === probeRef ? "测试中…" : "测试可用性"}
                            </Button>
                          ) : null}
                          <Button
                            size="sm"
                            onClick={() => addAvailable(entry)}
                            disabled={!editable || busy}
                          >
                            加入模型池
                          </Button>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ul>
              <div className="flex flex-col gap-2 border-t border-line pt-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex flex-wrap items-center gap-3 text-xs text-ink-3">
                  <p>
                    第 {currentPage} / {totalPages} 页
                  </p>
                  <label className="flex items-center gap-1.5 whitespace-nowrap">
                    每页
                    <Select
                      aria-label="每页显示条数"
                      className="h-9 w-20 lg:h-8"
                      value={availablePageSize}
                      onChange={(event) => updatePageSize(Number(event.target.value))}
                    >
                      {PAGE_SIZE_OPTIONS.map((size) => (
                        <option key={size} value={size}>
                          {size}
                        </option>
                      ))}
                    </Select>
                    条
                  </label>
                  {totalPages > 1 ? (
                    <div className="flex items-center gap-1.5 whitespace-nowrap">
                      <label htmlFor="model-page-jump">跳至</label>
                      <Input
                        id="model-page-jump"
                        type="number"
                        min={1}
                        max={totalPages}
                        inputMode="numeric"
                        className="h-9 w-16 px-2 text-center lg:h-8"
                        value={pageJump}
                        onChange={(event) =>
                          setPageJump(event.target.value.replace(/[^\d]/g, ""))
                        }
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            jumpToPage();
                          }
                        }}
                      />
                      <span>页</span>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={jumpToPage}
                        disabled={!pageJump.trim()}
                      >
                        跳转
                      </Button>
                    </div>
                  ) : null}
                </div>
                {totalPages > 1 ? (
                  <nav
                    aria-label="可用模型分页"
                    className="flex flex-wrap items-center gap-1.5"
                  >
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label="上一页"
                      disabled={currentPage <= 1}
                      onClick={() => setAvailablePageNumber(currentPage - 1)}
                    >
                      <ChevronLeft size={14} aria-hidden="true" />
                      <span className="hidden sm:inline">上一页</span>
                    </Button>
                    {paginationItems(currentPage, totalPages).map((item, index) =>
                      item === "ellipsis" ? (
                        <span
                          key={`gap-${index}`}
                          className="px-1 text-xs text-ink-3"
                          aria-hidden="true"
                        >
                          …
                        </span>
                      ) : item === currentPage ? (
                        <span
                          key={item}
                          aria-current="page"
                          className="inline-flex h-10 min-w-9 items-center justify-center rounded-control border border-accent bg-accent px-2 text-xs font-medium text-white lg:h-8"
                        >
                          {item}
                        </span>
                      ) : (
                        <Button
                          key={item}
                          size="sm"
                          variant="ghost"
                          className="min-w-9 px-2"
                          aria-label={`第 ${item} 页`}
                          onClick={() => setAvailablePageNumber(item)}
                        >
                          {item}
                        </Button>
                      ),
                    )}
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label="下一页"
                      disabled={currentPage >= totalPages}
                      onClick={() => setAvailablePageNumber(currentPage + 1)}
                    >
                      <span className="hidden sm:inline">下一页</span>
                      <ChevronRight size={14} aria-hidden="true" />
                    </Button>
                  </nav>
                ) : null}
              </div>
            </>
          )}
          <p className="text-xs leading-5 text-ink-3">
            测试会发送一次有界的合成请求，可能产生少量模型调用费用。 OpenCode
            供应商配置变更由下一次构建读取；这里刷新只更新列表，不需要重启采集服务。
          </p>
        </div>
      </section>

      {editable ? (
        <section className="rounded-panel border border-line bg-surface">
          <div className="border-b border-line px-4 py-4">
            <h2 className="text-[17px] leading-6 font-semibold text-ink">手动添加</h2>
            <p className="mt-1 text-sm leading-6 text-ink-2">
              可用模型列表未出现时，可按预设或自定义引用手动添加；未知模型的档位可自由填写。
            </p>
          </div>
          <div className="space-y-3 px-4 py-4">
            <div className="flex flex-col gap-3 lg:flex-row lg:flex-wrap lg:items-end">
              <div className="min-w-48 flex-1">
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="model-preset"
                >
                  预设模型
                </label>
                <Select
                  id="model-preset"
                  value={preset}
                  disabled={busy}
                  onChange={(event) => {
                    const next = event.target.value;
                    setPreset(next);
                    const entry = catalog.find((item) => item.id === next);
                    setPresetVariant(entry ? preferredVariant(entry.variants) : "");
                  }}
                >
                  <option value="">自定义引用</option>
                  {catalog.map((entry) => (
                    <option key={entry.id} value={entry.id}>
                      {entry.label}
                    </option>
                  ))}
                </Select>
              </div>
              {presetEntry ? (
                <div className="min-w-40 flex-1">
                  <label
                    className="mb-1 block text-xs font-medium text-ink-3"
                    htmlFor="model-preset-variant"
                  >
                    默认思考等级
                  </label>
                  <Select
                    id="model-preset-variant"
                    value={presetVariant}
                    disabled={busy}
                    onChange={(event) => setPresetVariant(event.target.value)}
                  >
                    {presetEntry.variants.map((variant) => (
                      <option key={variant} value={variant}>
                        {variant || "供应商默认"}
                      </option>
                    ))}
                  </Select>
                </div>
              ) : (
                <>
                  <div className="min-w-48 flex-1">
                    <label
                      className="mb-1 block text-xs font-medium text-ink-3"
                      htmlFor="custom-model-ref"
                    >
                      模型引用
                    </label>
                    <Input
                      id="custom-model-ref"
                      value={customRef}
                      placeholder="provider/model#variant"
                      disabled={busy}
                      onChange={(event) => setCustomRef(event.target.value)}
                    />
                  </div>
                  <div className="min-w-40 flex-1">
                    <label
                      className="mb-1 block text-xs font-medium text-ink-3"
                      htmlFor="custom-model-variant"
                    >
                      思考等级（可选）
                    </label>
                    <Input
                      id="custom-model-variant"
                      value={customVariant}
                      placeholder="如 high"
                      disabled={busy}
                      onChange={(event) => setCustomVariant(event.target.value)}
                    />
                  </div>
                </>
              )}
              <Button
                className="shrink-0"
                onClick={addModel}
                disabled={!editable || busy}
              >
                <Plus size={14} aria-hidden="true" />
                添加
              </Button>
            </div>
            <p className="text-xs leading-5 text-ink-3">
              思考等级必须属于模型的可选范围；未知模型只校验引用格式。保存前可以继续调整，移除和档位修改不会立即影响构建。
            </p>
          </div>
        </section>
      ) : null}

      <section className="space-y-2 text-xs leading-5 text-ink-3">
        <p>
          固定默认模型时，新构建和修复始终使用该模型；选择轮询时按一次入队的构建或修复轮转，不按商品或采集任务轮转。已排队和运行中的构建保留入队时锁定的模型，不会因保存而改派。
        </p>
        <p>
          固定模型即使最近探测失败也不会自动换模型；轮询会跳过标记失败的档位。未验证档位以可用模型列表的标记为准。
        </p>
        <p>
          可用模型由 OpenCode 在请求时读取；刷新只重新启动短生命周期的 OpenCode
          进程，不调用模型。供应商配置变更由下一次构建读取，不需要重启采集服务；页面保存后模型池和分配方式对新构建热生效。
        </p>
        <p>
          保存会写入本地 SQLite
          账本；删除页面配置或点击“恢复环境变量配置”后，服务回到启动时的
          ECOM_BUILD_MODEL_POOL。只有服务代码或环境变量变更需要重启采集服务；探测状态保存在内存中，重启后恢复为未探测。
        </p>
        <p>
          探测会发送一个有界的合成文本请求，不包含构建提示、规则或站点信息，可能产生少量模型调用费用。
        </p>
      </section>
    </div>
  );
}

export function ModelSettingsPage() {
  const query = useQuery({
    queryKey: ["build-config"],
    queryFn: ({ signal }) => getBuildConfig(signal),
  });

  if (query.isPending) {
    return (
      <p className="py-6 text-sm text-ink-2" role="status">
        正在读取模型配置…
      </p>
    );
  }

  if (query.isError || !query.data) {
    return (
      <ErrorNotice
        title="读取模型配置失败"
        message={
          query.error instanceof Error
            ? query.error.message
            : "服务没有返回模型池配置。"
        }
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <ModelSettingsForm
      config={query.data}
      refreshing={query.isFetching}
      onRefresh={() => void query.refetch()}
    />
  );
}
