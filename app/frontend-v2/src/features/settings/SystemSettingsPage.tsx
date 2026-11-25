import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Check, Copy, KeyRound, RefreshCw, ShieldCheck, X } from "lucide-react";
import {
  getSystemInfo,
  rotateSystemToken,
  setSystemAccess,
  type SystemAccess,
  type SystemInfo,
} from "../../lib/api";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { PageHeader } from "../../components/ui/PageHeader";
import { cn } from "../../lib/cn";
import {
  formatBytes,
  formatDuration,
  formatNumber,
  formatTime,
  type Tone,
} from "../../lib/format";

const AUTO_REFRESH_MS = 15_000;

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("浏览器拒绝了复制操作");
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function isLoopbackClient(): boolean {
  if (typeof window === "undefined") return true;
  const host = window.location.hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return host === "localhost" || host === "127.0.0.1" || host === "::1";
}

function currentOrigin(): string {
  return typeof window === "undefined" ? "" : window.location.origin;
}

function workerLabel(worker: string): string {
  if (worker === "managed") return "托管 worker";
  if (worker === "external") return "外部 worker";
  if (worker === "read-only") return "只读预览";
  return worker || "未知";
}

function accessLabel(access: SystemAccess): string {
  if (!access.lan_capable) return "仅本机";
  return access.lan_enabled ? "局域网开放" : "局域网关闭";
}

function accessTone(access: SystemAccess): Tone {
  if (!access.lan_capable) return "neutral";
  return access.lan_enabled ? "success" : "warning";
}

function CopyButton({
  value,
  label,
  className,
}: {
  value: string;
  label: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 2000);
    return () => window.clearTimeout(timer);
  }, [copied]);

  async function copy() {
    try {
      await copyText(value);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <Button
      type="button"
      variant="ghost"
      size="sm"
      className={cn("shrink-0", className)}
      aria-label={`复制${label}`}
      title={copied ? "已复制" : `复制${label}`}
      onClick={() => void copy()}
    >
      {copied ? (
        <Check size={14} aria-hidden="true" />
      ) : (
        <Copy size={14} aria-hidden="true" />
      )}
      <span className="sr-only sm:not-sr-only">{copied ? "已复制" : "复制"}</span>
    </Button>
  );
}

function Switch({
  checked,
  disabled,
  label,
  describedBy,
  onChange,
}: {
  checked: boolean;
  disabled?: boolean;
  label: string;
  describedBy?: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-describedby={describedBy}
      disabled={disabled}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors focus-visible:ring-2 focus-visible:ring-accent/40 focus-visible:outline-none",
        checked ? "border-accent bg-accent" : "border-line-strong bg-surface-muted",
        disabled && "cursor-not-allowed opacity-50",
      )}
      onClick={() => onChange(!checked)}
    >
      <span
        aria-hidden="true"
        className={cn(
          "h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
          checked ? "translate-x-6" : "translate-x-1",
        )}
      />
    </button>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="bg-surface px-4 py-4">
      <p className="text-xs font-medium text-ink-3">{label}</p>
      <p className="mt-1 text-lg leading-7 font-semibold tracking-[-0.01em] text-ink tabular">
        {value}
      </p>
      {hint ? <p className="mt-0.5 text-xs leading-5 text-ink-3">{hint}</p> : null}
    </div>
  );
}

function PathRow({
  label,
  value,
  copyLabel,
}: {
  label: string;
  value: string | null;
  copyLabel: string;
}) {
  return (
    <div className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start sm:justify-between sm:px-6">
      <dt className="shrink-0 text-sm text-ink-3">{label}</dt>
      <dd className="flex min-w-0 items-start gap-2 sm:max-w-[75%] sm:justify-end">
        <code className="break-all rounded-control bg-surface-muted px-2 py-1 font-mono text-xs text-ink-2">
          {value || "未配置"}
        </code>
        {value ? <CopyButton value={value} label={copyLabel} /> : null}
      </dd>
    </div>
  );
}

function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  busy,
  destructive = false,
  onOpenChange,
  onConfirm,
}: {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  busy: boolean;
  destructive?: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 w-[min(480px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("system-confirm-cancel")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div>
              <Dialog.Title className="text-lg leading-7 font-semibold text-ink">
                {title}
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                {description}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭确认对话框"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          <div className="flex justify-end gap-2 px-4 py-4 sm:px-6">
            <Button
              id="system-confirm-cancel"
              disabled={busy}
              onClick={() => onOpenChange(false)}
            >
              取消
            </Button>
            <Button
              variant={destructive ? "danger" : "primary"}
              disabled={busy}
              onClick={onConfirm}
            >
              {busy ? "处理中…" : confirmLabel}
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function TokenDialog({
  open,
  token,
  onOpenChange,
  onReload,
}: {
  open: boolean;
  token: string | null;
  onOpenChange: (open: boolean) => void;
  onReload: () => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content className="animate-dialog-in fixed left-1/2 top-1/2 z-50 w-[min(560px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 rounded-overlay border border-line bg-surface shadow-overlay">
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div>
              <Dialog.Title className="text-lg leading-7 font-semibold text-ink">
                新的访问令牌
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                只显示这一次。关闭或刷新后无法再次查看；请先复制保存。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭令牌对话框"
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          <div className="space-y-3 px-4 py-5 sm:px-6">
            <code className="block break-all rounded-control border border-line bg-surface-muted px-3 py-3 font-mono text-sm text-ink">
              {token || "正在生成…"}
            </code>
            <InlineNotice tone="warning" title="接下来会发生什么">
              所有设备都需要重新输入新令牌。你正在使用的浏览器会在重新加载后弹出认证框。
            </InlineNotice>
          </div>
          <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-4 sm:px-6">
            {token ? <CopyButton value={token} label="新访问令牌" /> : null}
            <Button onClick={() => onOpenChange(false)}>稍后重新加载</Button>
            <Button variant="primary" onClick={onReload} disabled={!token}>
              我已保存，重新加载
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function SystemSettingsPage() {
  const queryClient = useQueryClient();
  const [savingAccess, setSavingAccess] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmDisable, setConfirmDisable] = useState(false);
  const [confirmRotate, setConfirmRotate] = useState(false);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [tokenDialogOpen, setTokenDialogOpen] = useState(false);
  const [autoRefreshPaused, setAutoRefreshPaused] = useState(false);
  const [disabledFromLan, setDisabledFromLan] = useState(false);

  const query = useQuery({
    queryKey: ["system"],
    queryFn: ({ signal }) => getSystemInfo(signal),
    refetchInterval: autoRefreshPaused ? false : AUTO_REFRESH_MS,
    refetchOnWindowFocus: false,
  });

  if (query.isPending) {
    return (
      <p className="py-6 text-sm text-ink-2" role="status">
        正在读取系统状态…
      </p>
    );
  }

  if (query.isError || !query.data) {
    return (
      <ErrorNotice
        title="读取系统设置失败"
        message={
          query.error instanceof Error ? query.error.message : "服务没有返回系统状态。"
        }
        onRetry={() => void query.refetch()}
      />
    );
  }

  const data = query.data;
  const access = data.server;
  const readOnly = data.runtime.read_only;
  const lanClient = !isLoopbackClient();
  const restartFlags = `--host 0.0.0.0 --port ${access.port}`;
  const usedPercent =
    data.storage.disk_total_bytes > 0
      ? Math.min(
          100,
          Math.round(
            (data.storage.disk_used_bytes / data.storage.disk_total_bytes) * 100,
          ),
        )
      : 0;
  const diskWarning =
    data.storage.disk_total_bytes > 0 &&
    data.storage.disk_free_bytes / data.storage.disk_total_bytes < 0.1;

  let switchDisabledReason = "";
  if (readOnly) switchDisabledReason = "只读预览不能修改访问设置。";
  else if (disabledFromLan)
    switchDisabledReason = "局域网访问已关闭；请回到本机继续操作。";
  else if (autoRefreshPaused) switchDisabledReason = "请先重新加载页面。";
  else if (!access.lan_capable) switchDisabledReason = "当前仅监听回环地址，需重启。";
  else if (!access.token_configured) switchDisabledReason = "需要先生成访问令牌。";
  else if (savingAccess) switchDisabledReason = "正在保存访问设置。";

  function applyAccess(next: boolean) {
    if (savingAccess) return;
    setSavingAccess(true);
    setError("");
    setNotice("");
    void setSystemAccess(next)
      .then((response) => {
        queryClient.setQueryData<SystemInfo>(["system"], (current) =>
          current ? { ...current, server: response.access } : current,
        );
        if (!next && lanClient) {
          setAutoRefreshPaused(true);
          setDisabledFromLan(true);
          setNotice(
            "局域网访问已关闭。当前页面来自局域网，刷新后将无法继续访问；请回到本机继续操作。",
          );
        } else if (next) {
          setNotice("局域网访问已开启；同一局域网设备可使用访问令牌连接。");
        } else {
          setNotice("局域网访问已关闭。");
        }
      })
      .catch((exc) => setError(errorText(exc)))
      .finally(() => setSavingAccess(false));
  }

  function rotateToken() {
    if (rotating) return;
    setRotating(true);
    setAutoRefreshPaused(true);
    setError("");
    setNotice("");
    void rotateSystemToken()
      .then((response) => {
        queryClient.setQueryData<SystemInfo>(["system"], (current) =>
          current ? { ...current, server: response.access } : current,
        );
        setNewToken(response.token);
        setTokenDialogOpen(true);
        setAutoRefreshPaused(true);
        setConfirmRotate(false);
      })
      .catch((exc) => {
        setError(errorText(exc));
        setAutoRefreshPaused(false);
      })
      .finally(() => setRotating(false));
  }

  function reloadPage() {
    window.location.reload();
  }

  const modeBadge = (
    <Badge tone={accessTone(access)} dot>
      {accessLabel(access)}
    </Badge>
  );

  return (
    <div className="mx-auto w-full max-w-5xl space-y-6">
      <PageHeader
        eyebrow="系统"
        title="系统设置"
        description="查看访问、认证、资源和运行状态；局域网开关与令牌修改会立即生效并写入本地账本，绑定地址和端口由启动参数决定。"
        actions={
          <div className="flex flex-col items-stretch gap-1 sm:items-end">
            <Button
              onClick={() => {
                setError("");
                void query.refetch();
              }}
              disabled={
                query.isFetching || savingAccess || rotating || autoRefreshPaused
              }
              title={autoRefreshPaused ? "请先重新加载页面" : undefined}
            >
              <RefreshCw
                size={14}
                aria-hidden="true"
                className={query.isFetching ? "animate-spin" : undefined}
              />
              刷新
            </Button>
            <p className="text-xs text-ink-3">
              {autoRefreshPaused
                ? "自动刷新已暂停"
                : `更新于 ${formatTime(new Date(query.dataUpdatedAt).toISOString())}`}
            </p>
          </div>
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
      {newToken && !tokenDialogOpen ? (
        <InlineNotice tone="warning" title="访问令牌已更换">
          <p>新令牌只在刚才的对话框中显示；重新加载后需要输入新令牌。</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setTokenDialogOpen(true)}>
              查看新令牌
            </Button>
            <Button size="sm" variant="primary" onClick={reloadPage}>
              重新加载
            </Button>
          </div>
        </InlineNotice>
      ) : null}

      <MetricStrip
        label="系统概览"
        items={[
          {
            label: "服务状态",
            value: readOnly ? "只读预览" : "正常",
            hint: `版本 ${data.version}`,
          },
          {
            label: "访问范围",
            value: accessLabel(access),
            hint: `${access.host}:${access.port}`,
          },
          {
            label: "认证",
            value: access.auth_required ? "Basic 已启用" : "未启用",
            hint: access.token_configured
              ? `上次轮换 ${formatTime(access.token_updated_at)}`
              : "局域网需要令牌",
          },
          {
            label: "活跃负载",
            value: `${formatNumber(data.work.tasks_active)} 任务`,
            hint: `${formatNumber(data.work.builds_active)} 构建 · ${formatNumber(
              data.work.tasks_queued,
            )} 任务排队`,
          },
        ]}
      />

      <section className="rounded-panel border border-line bg-surface">
        <header className="border-b border-line px-4 py-4 sm:px-6">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-[17px] leading-6 font-semibold text-ink">访问与认证</h2>
            {modeBadge}
            {access.auth_required ? (
              <Badge tone="info" dot={false}>
                HTTP Basic
              </Badge>
            ) : (
              <Badge tone="warning" dot={false}>
                无认证
              </Badge>
            )}
          </div>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">
            局域网开关立即生效；令牌只保存哈希，页面不会再次显示旧令牌。
          </p>
        </header>

        <div className="grid divide-y divide-line lg:grid-cols-2 lg:divide-x lg:divide-y-0">
          <div className="space-y-4 px-4 py-5 sm:px-6">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">允许局域网访问</p>
                <p className="mt-1 text-sm leading-6 text-ink-2">
                  同一可信局域网内的设备可使用访问令牌连接。
                </p>
              </div>
              <Switch
                checked={access.lan_enabled}
                disabled={Boolean(switchDisabledReason)}
                label="允许局域网访问"
                describedBy="lan-access-reason"
                onChange={(next) => {
                  if (!next) {
                    setConfirmDisable(true);
                    return;
                  }
                  applyAccess(true);
                }}
              />
            </div>
            {switchDisabledReason ? (
              <p id="lan-access-reason" className="text-xs leading-5 text-ink-3">
                {switchDisabledReason}
              </p>
            ) : null}

            {!access.lan_capable ? (
              <InlineNotice tone="warning" title="当前仅监听回环地址">
                <p>页面无法把监听地址改成局域网。重启时在原启动命令上追加以下参数：</p>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <code className="break-all rounded-control bg-surface/70 px-2 py-1 font-mono text-xs">
                    {restartFlags}
                  </code>
                  <CopyButton value={restartFlags} label="重启参数" />
                </div>
                <p className="mt-2 text-xs">
                  令牌保存在本地账本；若尚未配置，请先在右侧生成。重启后页面即可开关局域网。
                </p>
              </InlineNotice>
            ) : null}

            {!access.token_configured ? (
              <InlineNotice tone="warning" title="尚未配置访问令牌">
                开启局域网前需要先生成访问令牌；生成后请立即保存。
              </InlineNotice>
            ) : null}

            {savingAccess ? (
              <p className="text-xs text-ink-3" role="status">
                正在保存访问设置…
              </p>
            ) : null}
          </div>

          <div className="space-y-4 px-4 py-5 sm:px-6">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">访问令牌</p>
                <p className="mt-1 text-sm leading-6 text-ink-2">
                  {access.token_configured
                    ? `Basic 认证已启用；上次轮换 ${formatTime(
                        access.token_updated_at,
                      )}。`
                    : "未配置令牌时仅回环地址可访问；局域网访问需要令牌。"}
                </p>
              </div>
              <Button
                size="sm"
                disabled={readOnly || rotating || savingAccess || autoRefreshPaused}
                title={
                  readOnly
                    ? "只读预览不能修改访问令牌"
                    : autoRefreshPaused
                      ? "请先重新加载页面"
                      : undefined
                }
                onClick={() => setConfirmRotate(true)}
              >
                <KeyRound size={14} aria-hidden="true" />
                {access.token_configured ? "轮换令牌" : "生成令牌"}
              </Button>
            </div>
            <p className="text-xs leading-5 text-ink-3">
              轮换后所有设备都需要重新输入新令牌。令牌只保存哈希；如果丢失，可用启动参数覆盖，或在本机重新生成。
            </p>
            <div className="flex items-start gap-2 rounded-control border border-line bg-surface-muted px-3 py-2">
              <ShieldCheck
                size={15}
                className="mt-0.5 shrink-0 text-ink-3"
                aria-hidden="true"
              />
              <p className="text-xs leading-5 text-ink-3">
                局域网访问使用 HTTP
                明文，仅适合可信网络；不要做公网端口映射或反向代理暴露。
              </p>
            </div>
          </div>
        </div>

        <div className="border-t border-line px-4 py-4 sm:px-6">
          <h3 className="text-sm font-semibold text-ink">访问地址</h3>
          <ul className="mt-2 space-y-2">
            {access.urls.map((url) => (
              <li key={url} className="flex flex-wrap items-center gap-2">
                <code className="break-all rounded-control bg-surface-muted px-2 py-1 font-mono text-xs text-ink-2">
                  {url}
                </code>
                {url.startsWith(currentOrigin()) ? (
                  <Badge tone="info" dot={false}>
                    当前
                  </Badge>
                ) : null}
                <CopyButton value={url} label="访问地址" />
              </li>
            ))}
          </ul>
          <details className="mt-3 rounded-control border border-line px-3 py-2">
            <summary className="cursor-pointer text-xs font-medium text-ink-2">
              允许的 Host（{formatNumber(access.allowed_hosts.length)}）
            </summary>
            {access.allowed_hosts.length ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {access.allowed_hosts.map((host) => (
                  <code
                    key={host}
                    className="rounded-control bg-surface-muted px-2 py-1 font-mono text-[11px] text-ink-3"
                  >
                    {host}
                  </code>
                ))}
              </div>
            ) : (
              <p className="mt-2 text-xs text-ink-3">
                没有额外的 Host；局域网能力需以非回环地址重启后建立。
              </p>
            )}
          </details>
        </div>
      </section>

      <section className="rounded-panel border border-line bg-surface">
        <header className="border-b border-line px-4 py-4 sm:px-6">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">资源与运行</h2>
          <p className="mt-1 text-sm leading-6 text-ink-2">
            应用级资源与队列状态；系统 CPU 和内存暂不采集。
          </p>
        </header>
        <div className="grid grid-cols-2 gap-px bg-line sm:grid-cols-3 lg:grid-cols-4">
          <Stat
            label="Worker"
            value={workerLabel(data.runtime.worker)}
            hint={`任务槽位 ${data.runtime.max_tasks ?? "—"} · 浏览器 ${
              data.runtime.max_browser_tasks ?? "—"
            }`}
          />
          <Stat
            label="活动任务"
            value={formatNumber(data.work.tasks_active)}
            hint={`排队 ${formatNumber(data.work.tasks_queued)} · 暂停 ${formatNumber(
              data.work.tasks_paused,
            )}`}
          />
          <Stat
            label="活动构建"
            value={formatNumber(data.work.builds_active)}
            hint={`排队 ${formatNumber(data.work.builds_queued)}`}
          />
          <Stat
            label="任务总数"
            value={formatNumber(data.work.tasks_total)}
            hint={`${Object.keys(data.work.tasks_by_state).length} 种状态`}
          />
          <Stat
            label="数据库"
            value={formatBytes(data.storage.db_bytes)}
            hint="含 WAL / SHM"
          />
          <Stat
            label="磁盘剩余"
            value={formatBytes(data.storage.disk_free_bytes)}
            hint={`共 ${formatBytes(data.storage.disk_total_bytes)}`}
          />
          <Stat
            label="磁盘使用"
            value={`${usedPercent}%`}
            hint={data.storage.disk_path || "当前输出盘"}
          />
          <Stat
            label="运行时长"
            value={formatDuration(data.uptime_seconds)}
            hint={`${formatNumber(data.runtime.threads)} 个进程线程`}
          />
        </div>
        <div className="border-t border-line px-4 py-4 sm:px-6">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-medium text-ink-3">磁盘占用</p>
            <p className={cn("text-xs", diskWarning ? "text-warning" : "text-ink-3")}>
              {diskWarning ? "剩余空间低于 10%" : `剩余 ${100 - usedPercent}%`}
            </p>
          </div>
          <div
            className="mt-2 h-2 overflow-hidden rounded-full bg-surface-muted"
            role="progressbar"
            aria-label="磁盘使用率"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={usedPercent}
          >
            <div
              className={cn(
                "h-full rounded-full transition-[width]",
                diskWarning ? "bg-warning" : "bg-accent",
              )}
              style={{ width: `${usedPercent}%` }}
            />
          </div>
        </div>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-panel border border-line bg-surface">
          <header className="border-b border-line px-4 py-4 sm:px-6">
            <h2 className="text-[17px] leading-6 font-semibold text-ink">数据与路径</h2>
            <p className="mt-1 text-sm leading-6 text-ink-2">
              用户主目录折叠为 ~；修改路径需要重启或迁移数据。
            </p>
          </header>
          <dl className="divide-y divide-line">
            <PathRow label="数据库" value={data.paths.db} copyLabel="数据库路径" />
            <PathRow
              label="输出目录"
              value={data.paths.out_root}
              copyLabel="输出目录路径"
            />
            <PathRow
              label="规则目录"
              value={data.paths.rules_dir}
              copyLabel="规则目录路径"
            />
          </dl>
        </section>

        <section className="rounded-panel border border-line bg-surface">
          <header className="border-b border-line px-4 py-4 sm:px-6">
            <h2 className="text-[17px] leading-6 font-semibold text-ink">环境与版本</h2>
            <p className="mt-1 text-sm leading-6 text-ink-2">
              应用、Python 和运行开关的当前状态。
            </p>
          </header>
          <dl className="divide-y divide-line">
            <div className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
              <dt className="text-sm text-ink-3">应用版本</dt>
              <dd className="font-mono text-xs text-ink-2">{data.version}</dd>
            </div>
            <div className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
              <dt className="text-sm text-ink-3">Python</dt>
              <dd className="font-mono text-xs text-ink-2">{data.runtime.python}</dd>
            </div>
            <div className="flex items-start justify-between gap-4 px-4 py-3 sm:px-6">
              <dt className="shrink-0 text-sm text-ink-3">操作系统</dt>
              <dd className="break-words text-right font-mono text-xs text-ink-2">
                {data.runtime.platform}
              </dd>
            </div>
            <div className="flex items-center justify-between gap-4 px-4 py-3 sm:px-6">
              <dt className="text-sm text-ink-3">启动时间</dt>
              <dd className="text-xs text-ink-2">{formatTime(data.started_at)}</dd>
            </div>
            <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 sm:px-6">
              <dt className="text-sm text-ink-3">运行开关</dt>
              <dd className="flex flex-wrap justify-end gap-1.5">
                <Badge tone={readOnly ? "warning" : "success"} dot={false}>
                  {readOnly ? "只读预览" : "可写"}
                </Badge>
                <Badge
                  tone={data.runtime.builds_available ? "success" : "neutral"}
                  dot={false}
                >
                  {data.runtime.builds_available ? "构建可用" : "构建停用"}
                </Badge>
                <Badge
                  tone={data.runtime.rules_configured ? "success" : "warning"}
                  dot={false}
                >
                  {data.runtime.rules_configured ? "规则已配置" : "无规则目录"}
                </Badge>
                <Badge
                  tone={data.runtime.legacy_ui === "enabled" ? "warning" : "neutral"}
                  dot={false}
                >
                  {data.runtime.legacy_ui === "enabled" ? "旧界面启用" : "旧界面下线"}
                </Badge>
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <section className="space-y-2 text-xs leading-5 text-ink-3">
        <p>
          访问开关和令牌写入本地 SQLite 账本；绑定地址、端口和允许的 Host
          由启动参数或启动时检测决定，修改后需要重启。
        </p>
        <p>
          令牌只保存哈希，不保存明文，也不会在日志或页面中回显。局域网访问是 HTTP
          明文；需要公网、HTTPS 或多用户权限时另做安全设计。
        </p>
      </section>

      <ConfirmDialog
        open={confirmDisable}
        title="关闭局域网访问？"
        description={
          lanClient
            ? "你正在通过局域网访问；关闭后本页会在下次请求时失去连接。其他设备也将无法访问。本机回环仍可使用，但需要令牌。"
            : "关闭后，同一局域网的其他设备将无法访问。本机回环仍可使用，但需要令牌。"
        }
        confirmLabel="关闭局域网"
        busy={savingAccess}
        destructive
        onOpenChange={setConfirmDisable}
        onConfirm={() => {
          setConfirmDisable(false);
          applyAccess(false);
        }}
      />

      <ConfirmDialog
        open={confirmRotate}
        title={access.token_configured ? "轮换访问令牌？" : "生成访问令牌？"}
        description="所有设备都需要重新输入新令牌；新令牌只显示一次。生成后请立即复制保存。"
        confirmLabel={access.token_configured ? "生成新令牌" : "生成令牌"}
        busy={rotating}
        onOpenChange={setConfirmRotate}
        onConfirm={rotateToken}
      />

      <TokenDialog
        open={tokenDialogOpen}
        token={newToken}
        onOpenChange={setTokenDialogOpen}
        onReload={reloadPage}
      />
    </div>
  );
}
