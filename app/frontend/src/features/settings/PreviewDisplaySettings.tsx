import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import {
  getPreviewSettings,
  setPreviewSettings,
  type PreviewSettings,
} from "../../lib/api";
import {
  DEFAULT_REALTIME_BATCH_SIZE,
  DEFAULT_REALTIME_LIMIT,
  PREVIEW_SETTINGS_QUERY_KEY,
  REALTIME_LIMIT_MAX,
  REALTIME_LIMIT_MIN,
  REALTIME_LIMIT_PRESETS,
} from "../../lib/previewSettings";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input, Select } from "../../components/ui/Input";
import { Switch } from "../../components/ui/Switch";

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

interface SaveInput {
  settings: PreviewSettings;
  notice: string;
}

interface PresetLimitControlProps {
  idPrefix: string;
  label: string;
  description: string;
  value: number;
  disabled: boolean;
  onSave: (next: number) => Promise<boolean>;
}

function PresetLimitControl({
  idPrefix,
  label,
  description,
  value,
  disabled,
  onSave,
}: PresetLimitControlProps) {
  const instanceId = useId();
  const selectId = `${idPrefix}-${instanceId}`;
  const customId = `${idPrefix}-custom-${instanceId}`;
  const descriptionId = `${idPrefix}-description-${instanceId}`;
  const errorId = `${idPrefix}-error-${instanceId}`;
  const [draft, setDraft] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const presetValue = (REALTIME_LIMIT_PRESETS as readonly number[]).includes(value)
    ? String(value)
    : "custom";
  const customMode = draft !== null || presetValue === "custom";
  const customValue = draft ?? String(value);
  const busy = disabled || saving;

  async function apply(next: number) {
    setError("");
    if (next === value) {
      setDraft(null);
      return;
    }
    setSaving(true);
    const saved = await onSave(next);
    setSaving(false);
    if (saved) setDraft(null);
  }

  function applyCustom() {
    const parsed = Number(customValue);
    if (
      !Number.isInteger(parsed) ||
      parsed < REALTIME_LIMIT_MIN ||
      parsed > REALTIME_LIMIT_MAX
    ) {
      setError(`请输入 ${REALTIME_LIMIT_MIN}–${REALTIME_LIMIT_MAX} 之间的整数。`);
      return;
    }
    void apply(parsed);
  }

  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <label htmlFor={selectId} className="text-sm font-medium text-ink">
          {label}
        </label>
        <p id={descriptionId} className="mt-1 max-w-2xl text-xs leading-5 text-ink-3">
          {description}
        </p>
        {error ? (
          <p id={errorId} className="mt-1 text-xs text-danger" role="alert">
            {error}
          </p>
        ) : null}
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <Select
          id={selectId}
          className="w-32"
          value={customMode ? "custom" : presetValue}
          disabled={busy}
          aria-describedby={error ? `${descriptionId} ${errorId}` : descriptionId}
          onChange={(event) => {
            setError("");
            if (event.target.value === "custom") {
              setDraft(String(value));
              return;
            }
            setDraft(null);
            void apply(Number(event.target.value));
          }}
        >
          {REALTIME_LIMIT_PRESETS.map((preset) => (
            <option key={preset} value={String(preset)}>
              {preset} 条
            </option>
          ))}
          <option value="custom">自定义…</option>
        </Select>
        {customMode ? (
          <>
            <Input
              id={customId}
              type="number"
              min={REALTIME_LIMIT_MIN}
              max={REALTIME_LIMIT_MAX}
              step={1}
              inputMode="numeric"
              className="w-24"
              aria-label={`自定义${label}`}
              aria-describedby={error ? `${descriptionId} ${errorId}` : descriptionId}
              value={customValue}
              disabled={busy}
              onChange={(event) => {
                setDraft(event.target.value);
                setError("");
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  applyCustom();
                }
              }}
            />
            <Button
              size="sm"
              disabled={busy}
              aria-label={`应用${label}`}
              onClick={applyCustom}
            >
              应用
            </Button>
          </>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Shared form for the system settings card and the in-page preview dialog.
 * Both entries read and write the same server-side preview setting.
 */
export function PreviewDisplayForm({ readOnly = false }: { readOnly?: boolean }) {
  const queryClient = useQueryClient();
  const formId = useId();
  const thumbnailsDescriptionId = `preview-thumbnails-description-${formId}`;
  const [notice, setNotice] = useState("");
  const query = useQuery({
    queryKey: PREVIEW_SETTINGS_QUERY_KEY,
    queryFn: ({ signal }) => getPreviewSettings(signal),
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
  const save = useMutation({
    mutationFn: ({ settings }: SaveInput) => setPreviewSettings(settings),
    onSuccess: (data, input) => {
      queryClient.setQueryData(PREVIEW_SETTINGS_QUERY_KEY, data);
      setNotice(input.notice);
    },
  });

  const checked = query.data?.thumbnails_enabled ?? true;
  const realtimeLimit = query.data?.realtime_limit ?? DEFAULT_REALTIME_LIMIT;
  const realtimeBatchSize =
    query.data?.realtime_batch_size ?? DEFAULT_REALTIME_BATCH_SIZE;
  const loadError = query.isError && !query.data;
  const disabled = readOnly || query.isPending || loadError || save.isPending;

  function currentSettings(patch: Partial<PreviewSettings> = {}): PreviewSettings {
    return {
      thumbnails_enabled: checked,
      realtime_limit: realtimeLimit,
      realtime_batch_size: realtimeBatchSize,
      ...patch,
    };
  }

  async function saveSettings(
    patch: Partial<PreviewSettings>,
    message: string,
  ): Promise<boolean> {
    setNotice("");
    try {
      await save.mutateAsync({ settings: currentSettings(patch), notice: message });
      return true;
    } catch {
      return false;
    }
  }

  return (
    <div>
      {query.isPending ? (
        <p className="text-sm text-ink-2" role="status">
          正在读取列表与预览设置…
        </p>
      ) : loadError ? (
        <ErrorNotice
          title="读取列表与预览设置失败"
          message={errorText(query.error)}
          compact
          onRetry={() => void query.refetch()}
        />
      ) : (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <p className="text-sm font-medium text-ink">在列表中加载商品缩略图</p>
              <p
                id={thumbnailsDescriptionId}
                className="mt-1 max-w-2xl text-xs leading-5 text-ink-3"
              >
                关闭后，工作台实时数据和任务 CSV
                的商品列显示占位块，不再预加载图片；点击占位块或「图片」链接仍可打开预览，弹窗内只加载当前大图，不显示底部缩略图轨道。
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="text-xs text-ink-3">
                {checked ? "已开启" : "已关闭"}
              </span>
              <Switch
                checked={checked}
                disabled={disabled}
                label="在列表中加载商品缩略图"
                describedBy={thumbnailsDescriptionId}
                onChange={(next) => {
                  void saveSettings(
                    { thumbnails_enabled: next },
                    next
                      ? "已开启列表缩略图；当前页面立即生效。"
                      : "已关闭列表缩略图；列表改为占位块，点击后仍可预览。",
                  );
                }}
              />
            </div>
          </div>

          <div className="mt-4 border-t border-line pt-4">
            <PresetLimitControl
              idPrefix="preview-realtime-limit"
              label="初始预览条数"
              description={`工作台「实时数据」首次显示多少条最新商品。可选预设，也可自定义 ${REALTIME_LIMIT_MIN}–${REALTIME_LIMIT_MAX} 条。`}
              value={realtimeLimit}
              disabled={disabled}
              onSave={(next) =>
                saveSettings(
                  { realtime_limit: next },
                  `已设置初始预览 ${next} 条；当前页面立即生效。`,
                )
              }
            />
          </div>

          <div className="mt-4 border-t border-line pt-4">
            <PresetLimitControl
              idPrefix="preview-realtime-batch"
              label="滚动加载批量"
              description={`在实时数据列表向下滚动时，每次追加多少条更早的商品。可选预设，也可自定义 ${REALTIME_LIMIT_MIN}–${REALTIME_LIMIT_MAX} 条。`}
              value={realtimeBatchSize}
              disabled={disabled}
              onSave={(next) =>
                saveSettings(
                  { realtime_batch_size: next },
                  `已设置滚动加载批量 ${next} 条；下次加载更早商品时生效。`,
                )
              }
            />
          </div>

          <div className="mt-4 rounded-panel border border-line bg-surface-muted px-4 py-3 text-xs leading-5 text-ink-3">
            <p>
              设置保存在服务端，所有浏览器共享；当前页面立即切换，其他浏览器刷新或重新聚焦后读取。
            </p>
            {readOnly ? (
              <p className="mt-1 text-warning">只读预览不能修改列表与预览设置。</p>
            ) : null}
            {save.isPending ? (
              <p className="mt-1" role="status">
                正在保存列表与预览设置…
              </p>
            ) : null}
          </div>
        </>
      )}
      {save.isError ? (
        <p className="mt-2 text-sm text-danger" role="alert">
          保存列表与预览设置失败：{errorText(save.error)}
        </p>
      ) : null}
      {notice ? (
        <p className="mt-2 text-sm text-success" role="status">
          {notice}
        </p>
      ) : null}
    </div>
  );
}

export function PreviewDisplaySettings({ readOnly = false }: { readOnly?: boolean }) {
  return (
    <section
      id="preview-display"
      className="scroll-mt-20 rounded-panel border border-line bg-surface"
    >
      <header className="border-b border-line px-4 py-4 sm:px-6">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">列表与预览</h2>
        <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">
          控制商品列表是否预加载缩略图、工作台实时数据首次读取多少条，以及向下滚动时每次追加多少条。设置保存在服务端，所有浏览器共享。
        </p>
      </header>
      <div className="px-4 py-4 sm:px-6">
        <PreviewDisplayForm readOnly={readOnly} />
      </div>
    </section>
  );
}
