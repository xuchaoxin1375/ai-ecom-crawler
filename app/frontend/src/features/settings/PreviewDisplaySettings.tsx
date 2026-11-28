import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useId, useState } from "react";
import {
  getPreviewSettings,
  setPreviewSettings,
  type PreviewSettings,
} from "../../lib/api";
import {
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

interface SaveIntent {
  settings: PreviewSettings;
  notice: string;
  resetCustom?: boolean;
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isPresetLimit(value: number): boolean {
  return REALTIME_LIMIT_PRESETS.some((preset) => preset === value);
}

/**
 * Shared form for the system settings card and the in-page preview dialog.
 * Both entries read and write the same server-side preview setting.
 */
export function PreviewDisplayForm({ readOnly = false }: { readOnly?: boolean }) {
  const queryClient = useQueryClient();
  const instanceId = useId();
  const descriptionId = `preview-thumbnails-description-${instanceId}`;
  const limitSelectId = `preview-realtime-limit-${instanceId}`;
  const customLimitId = `preview-realtime-limit-custom-${instanceId}`;
  const [notice, setNotice] = useState("");
  const [customMode, setCustomMode] = useState(false);
  const [customLimit, setCustomLimit] = useState<string | null>(null);
  const [limitError, setLimitError] = useState("");
  const query = useQuery({
    queryKey: PREVIEW_SETTINGS_QUERY_KEY,
    queryFn: ({ signal }) => getPreviewSettings(signal),
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: true,
  });
  const save = useMutation({
    mutationFn: (intent: SaveIntent) => setPreviewSettings(intent.settings),
    onSuccess: (data, intent) => {
      queryClient.setQueryData(PREVIEW_SETTINGS_QUERY_KEY, data);
      setNotice(intent.notice);
      if (intent.resetCustom) {
        setCustomMode(false);
        setCustomLimit(null);
      }
    },
  });

  const thumbnailsEnabled = query.data?.thumbnails_enabled ?? true;
  const realtimeLimit = query.data?.realtime_limit ?? DEFAULT_REALTIME_LIMIT;
  const loadError = query.isError && !query.data;
  const disabled = readOnly || query.isPending || loadError || save.isPending;
  const showCustom = customMode || !isPresetLimit(realtimeLimit);
  const selectValue = showCustom ? "custom" : String(realtimeLimit);
  const customLimitValue = customLimit ?? String(realtimeLimit);

  function currentSettings(patch: Partial<PreviewSettings> = {}): PreviewSettings {
    return {
      thumbnails_enabled: thumbnailsEnabled,
      realtime_limit: realtimeLimit,
      ...patch,
    };
  }

  function applyLimit(value: number) {
    setLimitError("");
    setNotice("");
    save.mutate({
      settings: currentSettings({ realtime_limit: value }),
      notice: `已设置实时数据预览 ${value} 条；工作台下次刷新时按此数量读取。`,
      resetCustom: true,
    });
  }

  function changeLimitMode(value: string) {
    setNotice("");
    setLimitError("");
    if (value === "custom") {
      setCustomMode(true);
      setCustomLimit(String(realtimeLimit));
      return;
    }
    setCustomMode(false);
    setCustomLimit(null);
    applyLimit(Number(value));
  }

  function applyCustomLimit() {
    const text = customLimitValue.trim();
    const value = Number(text);
    if (
      !/^\d+$/.test(text) ||
      !Number.isInteger(value) ||
      value < REALTIME_LIMIT_MIN ||
      value > REALTIME_LIMIT_MAX
    ) {
      setLimitError(`请输入 ${REALTIME_LIMIT_MIN}–${REALTIME_LIMIT_MAX} 之间的整数。`);
      return;
    }
    applyLimit(value);
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
                id={descriptionId}
                className="mt-1 max-w-2xl text-xs leading-5 text-ink-3"
              >
                关闭后，工作台实时数据和任务 CSV
                的商品列显示占位块，不再预加载图片；点击占位块或「图片」链接仍可打开预览，弹窗内只加载当前大图，不显示底部缩略图轨道。
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-3">
              <span className="text-xs text-ink-3">
                {thumbnailsEnabled ? "已开启" : "已关闭"}
              </span>
              <Switch
                checked={thumbnailsEnabled}
                disabled={disabled}
                label="在列表中加载商品缩略图"
                describedBy={descriptionId}
                onChange={(next) => {
                  setNotice("");
                  save.mutate({
                    settings: currentSettings({ thumbnails_enabled: next }),
                    notice: next
                      ? "已开启列表缩略图；当前页面立即生效。"
                      : "已关闭列表缩略图；列表改为占位块，点击后仍可预览。",
                  });
                }}
              />
            </div>
          </div>
          <div className="mt-4 border-t border-line pt-4">
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_200px] sm:items-start">
              <div>
                <label className="text-sm font-medium text-ink" htmlFor={limitSelectId}>
                  实时数据预览条数
                </label>
                <p className="mt-1 text-xs leading-5 text-ink-3">
                  控制工作台底部「实时数据」一次读取的商品数量；不改动采集结果。
                </p>
              </div>
              <Select
                id={limitSelectId}
                value={selectValue}
                disabled={disabled}
                onChange={(event) => changeLimitMode(event.target.value)}
              >
                {REALTIME_LIMIT_PRESETS.map((value) => (
                  <option key={value} value={String(value)}>
                    {value} 条
                  </option>
                ))}
                <option value="custom">自定义…</option>
              </Select>
            </div>
            {showCustom ? (
              <div className="mt-3 flex flex-wrap items-end gap-2">
                <div>
                  <label className="text-xs text-ink-3" htmlFor={customLimitId}>
                    自定义实时数据预览条数
                  </label>
                  <Input
                    id={customLimitId}
                    type="number"
                    min={REALTIME_LIMIT_MIN}
                    max={REALTIME_LIMIT_MAX}
                    value={customLimitValue}
                    disabled={disabled}
                    className="mt-1 w-32"
                    onChange={(event) => {
                      setCustomLimit(event.target.value);
                      setLimitError("");
                    }}
                  />
                </div>
                <Button
                  type="button"
                  size="sm"
                  variant="primary"
                  disabled={disabled}
                  onClick={applyCustomLimit}
                >
                  应用
                </Button>
              </div>
            ) : null}
            {limitError ? (
              <p className="mt-2 text-sm text-danger" role="alert">
                {limitError}
              </p>
            ) : null}
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
          控制商品列表是否预加载缩略图，以及工作台实时数据一次读取多少条。关闭缩略图后列表只显示占位块，需要时再打开大图，减少长列表的图片请求和资源占用。
        </p>
      </header>
      <div className="px-4 py-4 sm:px-6">
        <PreviewDisplayForm readOnly={readOnly} />
      </div>
    </section>
  );
}
