import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Save, Search, Trash2 } from "lucide-react";
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
import { formatTime, type Tone } from "../../lib/format";
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
  const savedRefs = useMemo(
    () => new Set(savedModels.map((model) => modelRef(model.id, model.variant))),
    [savedModels],
  );
  const savedByKey = useMemo(
    () => new Map(savedModels.map((model) => [model.id, model])),
    [savedModels],
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
  const [showAvailable, setShowAvailable] = useState(false);
  const [refreshingAvailable, setRefreshingAvailable] = useState(false);

  const editable = Boolean(config.model_pool_editable);
  const hasOverride = Boolean(config.model_pool_override);
  const source = config.model_pool_source ?? "none";
  const presetEntry = catalog.find((entry) => entry.id === preset);
  const savedDefault = config.default_model ?? "";
  const dirty =
    draftKey(draft) !== draftKey(toDraft(savedModels)) || defaultRef !== savedDefault;
  const busy = saving || resetting || Boolean(checking);
  const availableModels = useMemo(() => {
    const query = modelSearch.trim().toLowerCase();
    return (modelsQuery.data?.models ?? []).filter((item) => {
      if (draft.some((model) => model.id === item.id)) return false;
      if (!query) return true;
      return [item.id, item.label, item.provider].some((value) =>
        value.toLowerCase().includes(query),
      );
    });
  }, [draft, modelSearch, modelsQuery.data]);
  const availableError =
    modelsQuery.data?.error ??
    (modelsQuery.isError ? errorText(modelsQuery.error) : "");
  const discoveredCount = modelsQuery.data?.models?.length ?? 0;
  const availableExpanded = showAvailable || Boolean(modelSearch.trim());
  const availablePage = availableModels.slice(0, 50);

  function applyConfig(next: BuildConfig) {
    queryClient.setQueryData(["build-config"], next);
    setDraft(toDraft(next.models));
    setDefaultRef(next.default_model ?? "");
  }

  function updateDraft(next: DraftModel[]) {
    setDraft(next);
    setNotice("");
  }

  function addCandidate(candidate: DraftModel): boolean {
    setError("");
    setNotice("");
    const id = candidate.id.trim();
    if (!id) {
      setError("请输入模型引用，格式为 provider/model#variant。");
      return false;
    }
    const entry = catalog.find((item) => item.id === id);
    const variant = entry
      ? candidate.variant || preferredVariant(entry.variants)
      : candidate.variant;
    if (entry && !entry.variants.includes(variant)) {
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
    if (!addCandidate({ id: entry.id, variant: preferredVariant(entry.variants) })) {
      return;
    }
    setNotice(`${entry.label} 已加入模型池；保存后生效。`);
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

  async function probe(item: DraftModel) {
    const ref = modelRef(item.id, item.variant);
    if (!editable || !savedRefs.has(ref) || checking) return;
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

  function probeText(item: DraftModel, saved: BuildModelOption | undefined): string {
    const ref = modelRef(item.id, item.variant);
    if (!savedRefs.has(ref)) return "保存后可测试";
    const result = checks[ref] ?? saved?.health[item.variant];
    if (!result) return "尚未探测";
    const verdict = result.status === "ok" ? "探测通过" : "探测失败";
    const detail = result.code
      ? ` · ${probeErrorLabels[result.code] ?? result.code}`
      : "";
    return `${verdict} · ${formatTime(result.checked_at)} · ${result.latency_ms} ms${detail}`;
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
        description="从 OpenCode 发现可用模型，管理活动模型池、固定或轮询分配、默认思考等级和可用性探测。凭据仍由 OpenCode 解析，本页不保存 API Key。"
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

      <section className="rounded-panel border border-line bg-surface">
        <div className="flex flex-col gap-3 border-b border-line px-4 py-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-[17px] leading-6 font-semibold text-ink">模型池</h2>
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
                const label = entry?.label ?? savedByKey.get(item.id)?.label ?? item.id;
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
              const label = entry?.label ?? saved?.label ?? item.id;
              const variants =
                entry?.variants ??
                saved?.variants ??
                (item.variant ? [item.variant] : [""]);
              const supported =
                entry?.probe_supported ?? saved?.probe_supported ?? false;
              const ref = modelRef(item.id, item.variant);
              const canProbe = editable && savedRefs.has(ref) && supported;
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
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <label className="flex items-center gap-2 text-xs text-ink-3">
                        <span>默认思考等级</span>
                        {entry ? (
                          <Select
                            className="h-8 w-36"
                            aria-label={`${label} 默认思考等级`}
                            value={item.variant}
                            disabled={!editable || busy}
                            onChange={(event) =>
                              changeVariant(item.id, event.target.value)
                            }
                          >
                            {variants.map((variant) => (
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
                  <div className="flex shrink-0 items-center gap-2">
                    {supported ? (
                      <Button
                        size="sm"
                        onClick={() => void probe(item)}
                        disabled={!canProbe || busy}
                        title={
                          canProbe
                            ? "发送一个有界的合成文本请求"
                            : "保存模型池后才能测试"
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
              读取当前已接入的供应商和模型；刷新不会发送模型请求，也不读取密钥。
            </p>
          </div>
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
        <div className="space-y-3 px-4 py-4">
          <div className="relative">
            <Search
              size={15}
              aria-hidden="true"
              className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-ink-3"
            />
            <Input
              aria-label="搜索可用模型"
              className="pl-9"
              placeholder="搜索 provider、模型或标签"
              value={modelSearch}
              onChange={(event) => setModelSearch(event.target.value)}
            />
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
          ) : !availableExpanded ? (
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <p className="text-xs leading-5 text-ink-3">
                共 {discoveredCount} 个可用模型；输入关键词搜索，或显示前 50 个。
              </p>
              <Button
                size="sm"
                className="shrink-0"
                onClick={() => setShowAvailable(true)}
                disabled={discoveredCount === 0}
              >
                显示前 50 个
              </Button>
            </div>
          ) : availableModels.length === 0 ? (
            <p className="text-xs leading-5 text-ink-3">
              {modelSearch
                ? "没有匹配的可用模型。"
                : "可用模型都已在模型池中；仍可在下方手动添加引用。"}
            </p>
          ) : (
            <>
              <ul className="divide-y divide-line rounded-control border border-line">
                {availablePage.map((entry) => (
                  <li
                    key={entry.id}
                    className="flex flex-col gap-3 px-3 py-3 sm:flex-row sm:items-center sm:justify-between"
                  >
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <p className="text-sm font-semibold text-ink">{entry.label}</p>
                        <Badge tone={entry.known ? "info" : "neutral"} dot={false}>
                          {entry.known ? "已知元数据" : "未验证档位"}
                        </Badge>
                      </div>
                      <code className="mt-0.5 block break-all font-mono text-[11px] text-ink-3">
                        {entry.id}
                      </code>
                      <p className="mt-1 text-xs leading-5 text-ink-3">
                        {entry.known
                          ? `档位：${entry.variants.join(" / ")}`
                          : "档位未验证，可加入后自由填写"}
                        {" · "}
                        {entry.probe_supported ? "可测试" : "未配置小请求探测"}
                      </p>
                    </div>
                    <Button
                      size="sm"
                      className="shrink-0"
                      onClick={() => addAvailable(entry)}
                      disabled={!editable || busy}
                    >
                      加入模型池
                    </Button>
                  </li>
                ))}
              </ul>
              {availableModels.length > 50 ? (
                <p className="text-xs leading-5 text-ink-3">
                  显示前 50 个，共 {availableModels.length} 个匹配；输入关键词缩小范围。
                </p>
              ) : null}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowAvailable(false)}
                disabled={Boolean(modelSearch.trim())}
              >
                收起列表
              </Button>
            </>
          )}
          <p className="text-xs leading-5 text-ink-3">
            OpenCode
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
