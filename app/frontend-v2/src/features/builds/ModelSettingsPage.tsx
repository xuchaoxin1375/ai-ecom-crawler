import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import {
  checkBuildModel,
  getBuildConfig,
  resetBuildModels,
  updateBuildModels,
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

  const editable = Boolean(config.model_pool_editable);
  const hasOverride = Boolean(config.model_pool_override);
  const source = config.model_pool_source ?? "none";
  const presetEntry = catalog.find((entry) => entry.id === preset);
  const dirty = draftKey(draft) !== draftKey(toDraft(savedModels));
  const busy = saving || resetting || Boolean(checking);

  function applyConfig(next: BuildConfig) {
    queryClient.setQueryData(["build-config"], next);
    setDraft(toDraft(next.models));
  }

  function updateDraft(next: DraftModel[]) {
    setDraft(next);
    setNotice("");
  }

  function addModel() {
    setError("");
    setNotice("");
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
    if (!candidate?.id) {
      setError("请输入模型引用，格式为 provider/model#variant。");
      return;
    }
    const entry = catalog.find((item) => item.id === candidate!.id);
    if (entry && !candidate.variant) {
      candidate.variant = preferredVariant(entry.variants);
    }
    if (entry && !entry.variants.includes(candidate.variant)) {
      setError("请选择该模型支持的思考等级。");
      return;
    }
    if (draft.some((item) => item.id === candidate!.id)) {
      setError("该模型已在模型池中；每个模型只能配置一次。");
      return;
    }
    updateDraft([...draft, candidate]);
    setPreset("");
    setPresetVariant("");
    setCustomRef("");
    setCustomVariant("");
  }

  function removeModel(id: string) {
    updateDraft(draft.filter((item) => item.id !== id));
  }

  function changeVariant(id: string, variant: string) {
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
      );
      applyConfig(next);
      setNotice(
        "模型池已保存；新构建会使用新配置，已排队和运行中的构建保持入队时锁定的模型。",
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
        description="管理构建与规则修复使用的模型池、默认思考等级和可用性探测。凭据仍由 OpenCode 解析，本页不保存 API Key。"
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

        {draft.length === 0 ? (
          <EmptyState
            title="模型池为空"
            description="不配置模型池时，构建和修复使用单一的默认模型。添加至少两个模型后，新构建会按入队顺序轮转。"
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

      {editable ? (
        <section className="rounded-panel border border-line bg-surface">
          <div className="border-b border-line px-4 py-4">
            <h2 className="text-[17px] leading-6 font-semibold text-ink">添加模型</h2>
            <p className="mt-1 text-sm leading-6 text-ink-2">
              已知模型会给出可选思考等级；其他 OpenCode 已接入的模型可填自定义引用。
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
          模型池按一次入队的构建或修复轮转，不按商品或采集任务轮转。已排队和运行中的构建保留入队时锁定的模型，不会因保存而改派。
        </p>
        <p>
          保存会写入本地 SQLite
          账本；删除页面配置或点击“恢复环境变量配置”后，服务回到启动时的
          ECOM_BUILD_MODEL_POOL。探测状态保存在内存中，重启后恢复为未探测。
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
