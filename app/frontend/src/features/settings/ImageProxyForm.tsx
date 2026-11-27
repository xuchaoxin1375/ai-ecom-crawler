import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import {
  getImageProxy,
  setImageProxy,
  type ImageProxyMode,
  type ImageProxySettings as ImageProxyConfig,
} from "../../lib/api";
import { cn } from "../../lib/cn";
import { Button } from "../../components/ui/Button";
import { Input, Select } from "../../components/ui/Input";

interface Draft {
  mode: ImageProxyMode;
  proxy: string;
}

const MODE_LABELS: Record<ImageProxyMode, string> = {
  auto: "自动",
  specified: "指定代理",
  direct: "直连",
};

function initialDraft(settings: ImageProxyConfig): Draft {
  return { mode: settings.mode, proxy: settings.proxy ?? "" };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function validateDraft(draft: Draft): string {
  if (draft.mode !== "specified") return "";
  const proxy = draft.proxy.trim();
  if (!proxy) return "指定代理模式需要填写代理 URL。";
  if (!/^(https?|socks5):\/\//i.test(proxy)) {
    return "代理 URL 只支持 http、https 或 socks5。";
  }
  if (proxy.includes("@")) return "代理 URL 不能包含账号或密码。";
  return "";
}

export function ImageProxyForm({
  onSaved,
  className,
}: {
  onSaved?: () => void;
  className?: string;
}) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["image-proxy"],
    queryFn: ({ signal }) => getImageProxy(signal),
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState("");
  const save = useMutation({
    mutationFn: (value: Draft) =>
      setImageProxy({
        mode: value.mode,
        proxy: value.proxy.trim() || null,
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["image-proxy"], data);
      setDraft(null);
      setNotice("已保存；之后加载的商品图片立即使用新设置。");
      onSaved?.();
    },
  });
  const { mutate: saveSettings, isPending, isError, error, reset } = save;

  if (query.isPending) {
    return (
      <p className="text-sm text-ink-2" role="status">
        正在读取图片代理设置…
      </p>
    );
  }
  if (query.isError || !query.data) {
    return (
      <p className="text-sm text-danger" role="alert">
        读取图片代理设置失败：{errorText(query.error)}
      </p>
    );
  }

  const current = draft ?? initialDraft(query.data);
  const validationError = validateDraft(current);
  const proxyDisabled = current.mode === "direct";

  function change(patch: Partial<Draft>) {
    setDraft((value) => ({ ...(value ?? initialDraft(query.data!)), ...patch }));
    setNotice("");
    reset();
  }

  return (
    <div className={cn("space-y-4", className)}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1 text-sm text-ink-2">
          <label className="font-medium text-ink" htmlFor="image-proxy-mode">
            取图方式
          </label>
          <Select
            id="image-proxy-mode"
            value={current.mode}
            onChange={(event) => change({ mode: event.target.value as ImageProxyMode })}
          >
            {(Object.entries(MODE_LABELS) as Array<[ImageProxyMode, string]>).map(
              ([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ),
            )}
          </Select>
          <p className="text-xs leading-5 text-ink-3">
            {current.mode === "auto"
              ? "任务或站点已配置的代理优先；没有任务代理时用服务默认代理，再用下面设置的系统图片代理。"
              : current.mode === "specified"
                ? "所有图片只走下面填写的代理；代理不可用时显示图片加载失败，不会静默直连。"
                : "所有图片直接连接来源站；适合确认图片 CDN 不需要代理时使用。"}
          </p>
        </div>
        <div className="space-y-1 text-sm text-ink-2">
          <label className="font-medium text-ink" htmlFor="image-proxy-url">
            系统图片代理
          </label>
          <Input
            id="image-proxy-url"
            placeholder="http://127.0.0.1:7890"
            value={current.proxy}
            disabled={proxyDisabled}
            onChange={(event) => change({ proxy: event.target.value })}
          />
          <p className="text-xs leading-5 text-ink-3">
            支持 http、https、socks5，不接受内嵌账号或密码。自动模式下可留空。
          </p>
        </div>
      </div>
      <div className="space-y-2 rounded-panel border border-line bg-surface-muted px-4 py-3 text-xs leading-5 text-ink-3">
        <p>
          服务默认代理：{" "}
          <span className="font-medium text-ink-2">
            {query.data.service_proxy_configured ? "已配置" : "未配置"}
          </span>
        </p>
        <p>
          当前生效：{MODE_LABELS[current.mode]}
          {current.mode !== "direct" && current.proxy.trim()
            ? ` · ${current.proxy.trim()}`
            : ""}
        </p>
        <p>
          任务或站点代理来自任务定义，优先于这里；修改后对正在加载的图片立即生效，不需要重启服务。
        </p>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-xs leading-5 text-ink-3">
          图片只通过本机服务取回，不会把任务账本或 Cookie 发给图片站点。
        </p>
        <Button
          size="sm"
          variant="primary"
          disabled={isPending || Boolean(validationError)}
          onClick={() => saveSettings(current)}
        >
          {isPending ? "保存中…" : "保存图片代理"}
        </Button>
      </div>
      {validationError ? (
        <p className="text-sm text-danger" role="alert">
          {validationError}
        </p>
      ) : null}
      {isError ? (
        <p className="text-sm text-danger" role="alert">
          {errorText(error)}
        </p>
      ) : null}
      {notice ? (
        <p className="text-sm text-success" role="status">
          {notice}
        </p>
      ) : null}
    </div>
  );
}
