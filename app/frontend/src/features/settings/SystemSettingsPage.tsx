import * as Dialog from "@radix-ui/react-dialog";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { Check, Copy, KeyRound, LogOut, RefreshCw, ShieldCheck, X } from "lucide-react";
import {
  getSystemInfo,
  logout as logoutSession,
  rotateSystemToken,
  setSystemAccess,
  setSystemBuildSlots,
  setSystemCollectionSlots,
  setSystemToken,
  type SystemAccess,
  type SystemInfo,
  type SystemRuntime,
} from "../../lib/api";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { InlineNotice } from "../../components/ui/InlineNotice";
import { Input } from "../../components/ui/Input";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { PageHeader } from "../../components/ui/PageHeader";
import { cn } from "../../lib/cn";
import { useManualRefresh } from "../../lib/liveRefresh";
import { CollectionPolicySettings } from "./CollectionPolicySettings";
import { ResourceGauges } from "./ResourceGauges";
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
                新的访问密钥
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                只显示这一次。关闭或刷新后无法再次查看；请先复制保存。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭密钥对话框"
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
              所有设备都需要用新密钥重新登录。你正在使用的浏览器会在重新加载后进入登录页。
            </InlineNotice>
          </div>
          <div className="flex flex-wrap justify-end gap-2 border-t border-line px-4 py-4 sm:px-6">
            {token ? <CopyButton value={token} label="新访问密钥" /> : null}
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

type SlotKind = "collection" | "build";

interface RestartNotice {
  kind: SlotKind;
  current: number;
  next: number;
}

function RestartNoticeDialog({
  notice,
  onClose,
}: {
  notice: RestartNotice | null;
  onClose: () => void;
}) {
  return (
    <Dialog.Root
      open={notice !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content className="animate-dialog-in fixed left-1/2 top-1/2 z-50 w-[min(520px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 rounded-overlay border border-line bg-surface shadow-overlay">
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div>
              <Dialog.Title className="text-lg leading-7 font-semibold text-ink">
                并发设置已保存，需要重启服务
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                {notice
                  ? `${notice.kind === "build" ? "规则分析" : "采集"}并发已保存为下次启动值 ${notice.next} 个；当前进程仍为 ${notice.current} 个。`
                  : ""}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭重启提醒"
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          <div className="space-y-2 px-4 py-4 sm:px-6">
            <p className="text-sm leading-6 text-ink-2">
              保存不会中断当前任务；新并发值不会热更新。请沿用当前启动参数重启服务后生效。
            </p>
            <p className="text-xs leading-5 text-ink-3">
              重启前先让在途任务结清，不要用强制结束代替正常关闭。
            </p>
          </div>
          <div className="flex justify-end border-t border-line px-4 py-4 sm:px-6">
            <Button variant="primary" onClick={onClose}>
              知道了
            </Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function RuntimeSlots({
  runtime,
  kind,
  onRestartRequired,
}: {
  runtime: SystemRuntime;
  kind: SlotKind;
  onRestartRequired: (notice: RestartNotice) => void;
}) {
  const building = kind === "build";
  const field = building ? "build_slots" : "collection_slots";
  const inputId = `${kind}-slots`;
  const launchOption = building ? "--max-builds" : "--max-tasks";
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState<string | null>(null);
  const slots = runtime[field];
  const currentValue = building ? runtime.max_builds : runtime.max_tasks;
  const current = currentValue ?? slots?.next_start ?? 1;
  const nextStart = slots?.next_start ?? 1;
  const input = slots ? (draft ?? String(slots.next_start)) : "";
  const value = Number(input);
  const valid = /^\d+$/.test(input) && Number.isSafeInteger(value) && value >= 1;
  const pendingRestart = slots ? current !== slots.next_start : false;
  const changed = valid && value !== nextStart;
  const save = useMutation({
    mutationFn: building ? setSystemBuildSlots : setSystemCollectionSlots,
    onSuccess: async (saved) => {
      await queryClient.cancelQueries({ queryKey: ["system"] });
      queryClient.setQueryData<SystemInfo>(["system"], (previous) =>
        previous
          ? { ...previous, runtime: { ...previous.runtime, [field]: saved } }
          : previous,
      );
      setDraft(null);
      if (saved.next_start !== current) {
        onRestartRequired({ kind, current, next: saved.next_start });
      }
    },
  });
  const {
    mutate: saveSlots,
    isPending,
    isError,
    error: saveError,
    reset: resetSave,
  } = save;

  useEffect(() => {
    if (
      draft === null ||
      !slots ||
      !valid ||
      value === nextStart ||
      isPending ||
      isError
    ) {
      return;
    }
    const timer = window.setTimeout(() => saveSlots(value), 700);
    return () => window.clearTimeout(timer);
  }, [draft, slots, valid, value, nextStart, isPending, isError, saveSlots]);

  if (!slots) return null;

  function saveNow() {
    if (!changed || isPending) return;
    saveSlots(value);
  }

  return (
    <div className="space-y-2 border-t border-line px-4 py-4 sm:px-6">
      <div className="flex flex-wrap items-center gap-2">
        <label
          htmlFor={slots.source === "cli" ? undefined : inputId}
          className="text-sm font-medium text-ink"
        >
          {building ? "同时分析规则的任务数" : "同时采集任务数"}
        </label>
        {pendingRestart ? <Badge tone="warning">待重启</Badge> : null}
      </div>
      {slots.source === "cli" ? (
        <p className="text-sm text-ink-2">
          当前由启动参数{" "}
          <code>
            {launchOption} {current}
          </code>{" "}
          指定。
        </p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              id={inputId}
              className="w-24"
              inputMode="numeric"
              aria-invalid={!valid}
              aria-describedby={
                valid ? `${inputId}-hint` : `${inputId}-error ${inputId}-hint`
              }
              disabled={isPending}
              value={input}
              onChange={(event) => {
                resetSave();
                setDraft(event.target.value);
              }}
              onBlur={saveNow}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  saveNow();
                }
              }}
            />
            {slots.source === "settings" ? (
              <Button size="sm" disabled={isPending} onClick={() => saveSlots(null)}>
                恢复默认
              </Button>
            ) : null}
          </div>
          {!valid ? (
            <p id={`${inputId}-error`} className="text-sm text-danger">
              请输入大于 0 且可精确表示的整数。
            </p>
          ) : null}
          <p id={`${inputId}-hint`} className="text-xs leading-5 text-ink-3">
            修改后自动保存；保存的是下次启动值，不会热更新当前进程。
          </p>
          <p className="text-sm text-ink-2" role="status">
            {isPending
              ? "正在自动保存…"
              : pendingRestart
                ? `已自动保存下次启动值 ${slots.next_start} 个；重启服务后生效。`
                : `当前运行 ${current} 个；修改后自动保存。`}
          </p>
          {isError ? (
            <p className="text-sm text-danger" role="alert">
              {errorText(saveError)}
            </p>
          ) : null}
        </>
      )}
    </div>
  );
}

export function SystemSettingsPage() {
  const location = useLocation();
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
  const [restartNotice, setRestartNotice] = useState<RestartNotice | null>(null);
  const [disabledFromLan, setDisabledFromLan] = useState(false);
  const [customKey, setCustomKey] = useState("");
  const [savingKey, setSavingKey] = useState(false);
  const [confirmCustomKey, setConfirmCustomKey] = useState(false);
  const [customKeyChanged, setCustomKeyChanged] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const focusedResources = useRef(false);
  const { refreshing, runRefresh } = useManualRefresh();

  const query = useQuery({
    queryKey: ["system"],
    queryFn: ({ signal }) => getSystemInfo(signal),
    refetchInterval: autoRefreshPaused ? false : AUTO_REFRESH_MS,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (focusedResources.current) return;
    if (
      !location.search.includes("focus=resources") &&
      !window.location.hash.includes("focus=resources")
    ) {
      return;
    }
    const target = document.getElementById("resources");
    if (!target) return;
    const frame = window.requestAnimationFrame(() => {
      target.scrollIntoView({ block: "start" });
      focusedResources.current = true;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [location.search, query.data]);

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
  else if (!access.token_configured) switchDisabledReason = "需要先设置访问密钥。";
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
          setNotice("局域网访问已开启；同一局域网设备可使用访问密钥连接。");
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
        setCustomKeyChanged(false);
        setConfirmRotate(false);
      })
      .catch((exc) => {
        setError(errorText(exc));
        setAutoRefreshPaused(false);
      })
      .finally(() => setRotating(false));
  }

  function saveCustomKey() {
    if (savingKey) return;
    if (!customKey.trim()) {
      setError("请输入访问密钥。");
      setConfirmCustomKey(false);
      return;
    }
    setSavingKey(true);
    setError("");
    setNotice("");
    void setSystemToken(customKey)
      .then((response) => {
        queryClient.setQueryData<SystemInfo>(["system"], (current) =>
          current ? { ...current, server: response.access } : current,
        );
        setCustomKey("");
        setNewToken(null);
        setTokenDialogOpen(false);
        setConfirmCustomKey(false);
        setCustomKeyChanged(true);
        setAutoRefreshPaused(true);
      })
      .catch((exc) => setError(errorText(exc)))
      .finally(() => setSavingKey(false));
  }

  function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setError("");
    void logoutSession()
      .then(() => {
        window.location.hash = "#/login";
      })
      .catch((exc) => setError(errorText(exc)))
      .finally(() => setLoggingOut(false));
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
        description="查看访问、认证、资源和运行状态；局域网开关与访问密钥修改会立即生效并写入本地账本，绑定地址和端口由启动参数决定。"
        actions={
          <div className="flex flex-col items-stretch gap-1 sm:items-end">
            <Button
              onClick={() => {
                setError("");
                void runRefresh(() => query.refetch());
              }}
              disabled={refreshing || savingAccess || rotating || autoRefreshPaused}
              title={autoRefreshPaused ? "请先重新加载页面" : undefined}
            >
              <RefreshCw
                size={14}
                aria-hidden="true"
                className={refreshing ? "animate-spin" : undefined}
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
        <InlineNotice tone="warning" title="访问密钥已更换">
          <p>新密钥只在刚才的对话框中显示；重新加载后需要在登录页输入新密钥。</p>
          <div className="mt-2 flex flex-wrap gap-2">
            <Button size="sm" onClick={() => setTokenDialogOpen(true)}>
              查看新密钥
            </Button>
            <Button size="sm" variant="primary" onClick={reloadPage}>
              重新加载
            </Button>
          </div>
        </InlineNotice>
      ) : null}
      {customKeyChanged && !newToken ? (
        <InlineNotice tone="warning" title="访问密钥已更新">
          <p>请重新加载页面，并在登录页输入新密钥。</p>
          <div className="mt-2">
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
            value: access.auth_required ? "登录页已启用" : "未启用",
            hint: access.token_configured
              ? `上次轮换 ${formatTime(access.token_updated_at)}`
              : "局域网需要访问密钥",
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
                登录页认证
              </Badge>
            ) : (
              <Badge tone="warning" dot={false}>
                无认证
              </Badge>
            )}
          </div>
          <p className="mt-1 max-w-3xl text-sm leading-6 text-ink-2">
            局域网开关立即生效；访问密钥只保存哈希，页面不会再次显示旧密钥。
          </p>
        </header>

        <div className="grid divide-y divide-line lg:grid-cols-2 lg:divide-x lg:divide-y-0">
          <div
            role="group"
            aria-label="局域网访问"
            className="min-w-0 space-y-4 px-4 py-5 sm:px-6"
          >
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">允许局域网访问</p>
                <p className="mt-1 text-sm leading-6 text-ink-2">
                  同一可信局域网内的设备可使用访问密钥连接。
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
                  访问密钥保存在本地账本；若尚未配置，请先在访问密钥区域设置。重启后页面即可开关局域网。
                </p>
              </InlineNotice>
            ) : null}

            {!access.token_configured ? (
              <InlineNotice tone="warning" title="尚未配置访问密钥">
                开启局域网前需要先设置访问密钥；设置后请保存。
              </InlineNotice>
            ) : null}

            {savingAccess ? (
              <p className="text-xs text-ink-3" role="status">
                正在保存访问设置…
              </p>
            ) : null}
            <div className="border-t border-line pt-4">
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
              <p className="mt-3 text-xs leading-5 text-ink-3">
                {!access.lan_capable
                  ? "当前仅监听回环地址；需重启后才能供其他设备访问。"
                  : access.lan_enabled
                    ? "在可信局域网内的其他设备上打开地址，再输入访问密钥。"
                    : "局域网访问已关闭，开启后其他设备才能使用地址访问。"}
              </p>
            </div>
          </div>

          <div className="min-w-0 space-y-4 px-4 py-5 sm:px-6">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <p className="text-sm font-semibold text-ink">访问密钥</p>
                <p className="mt-1 text-sm leading-6 text-ink-2">
                  {access.token_configured
                    ? `登录页认证已启用；上次轮换 ${formatTime(
                        access.token_updated_at,
                      )}。`
                    : "未配置密钥时仅回环地址可访问；局域网访问需要密钥。"}
                </p>
              </div>
              <Button
                size="sm"
                disabled={
                  readOnly || rotating || savingAccess || savingKey || autoRefreshPaused
                }
                title={
                  readOnly
                    ? "只读预览不能修改访问密钥"
                    : autoRefreshPaused
                      ? "请先重新加载页面"
                      : undefined
                }
                onClick={() => setConfirmRotate(true)}
              >
                <KeyRound size={14} aria-hidden="true" />
                {access.token_configured ? "生成随机密钥" : "生成密钥"}
              </Button>
            </div>
            <p className="text-xs leading-5 text-ink-3">
              随机密钥只显示一次；生成后所有设备都需要用新密钥重新登录。
            </p>
            <form
              className="space-y-2"
              onSubmit={(event) => {
                event.preventDefault();
                if (!customKey.trim()) {
                  setError("请输入访问密钥。");
                  return;
                }
                setConfirmCustomKey(true);
              }}
            >
              <label
                htmlFor="custom-access-key"
                className="block text-sm font-medium text-ink"
              >
                自定义访问密钥
              </label>
              <div className="flex flex-wrap gap-2">
                <Input
                  id="custom-access-key"
                  type="password"
                  autoComplete="new-password"
                  className="min-w-0 flex-1"
                  placeholder="1–256 个字符"
                  value={customKey}
                  disabled={readOnly || autoRefreshPaused || savingKey}
                  onChange={(event) => setCustomKey(event.target.value)}
                />
                <Button
                  type="submit"
                  size="sm"
                  disabled={readOnly || autoRefreshPaused || savingKey || savingAccess}
                >
                  保存密钥
                </Button>
              </div>
              <p className="text-xs leading-5 text-ink-3">
                1–256 个字符，首尾空白会去掉；不强制大小写、数字或符号。
              </p>
            </form>
            <p className="text-xs leading-5 text-ink-3">
              密钥只保存哈希；如果丢失，可用启动参数覆盖，或在本机重新设置。
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
            {access.token_configured ? (
              <div className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-3">
                <p className="text-xs leading-5 text-ink-3">
                  退出只清除当前浏览器；其他设备需要重新登录时轮换密钥。
                </p>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={loggingOut}
                  onClick={handleLogout}
                >
                  <LogOut size={14} aria-hidden="true" />
                  {loggingOut ? "正在退出…" : "退出登录"}
                </Button>
              </div>
            ) : null}
          </div>
        </div>
      </section>

      <section
        id="resources"
        className="scroll-mt-20 rounded-panel border border-line bg-surface"
      >
        <header className="border-b border-line px-4 py-4 sm:px-6">
          <h2 className="text-[17px] leading-6 font-semibold text-ink">资源与运行</h2>
          <p className="mt-1 text-sm leading-6 text-ink-2">
            CPU 与内存为服务所在主机的采样值；磁盘为输出盘，队列为当前任务与构建状态。
          </p>
        </header>
        <ResourceGauges
          data={data}
          isPending={query.isPending}
          isError={query.isError}
          onRetry={() => void query.refetch()}
        />
        <div className="grid grid-cols-2 gap-px bg-line sm:grid-cols-3 lg:grid-cols-4">
          <Stat
            label="Worker"
            value={workerLabel(data.runtime.worker)}
            hint={`任务槽位 ${data.runtime.max_tasks ?? "—"} · 浏览器 ${
              data.runtime.max_browser_tasks ?? "—"
            }${data.runtime.per_domain_rps == null ? "" : ` · 每域 ${data.runtime.per_domain_rps} 请求/秒`}`}
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
        <RuntimeSlots
          runtime={data.runtime}
          kind="collection"
          onRestartRequired={setRestartNotice}
        />
        <RuntimeSlots
          runtime={data.runtime}
          kind="build"
          onRestartRequired={setRestartNotice}
        />
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

      <CollectionPolicySettings />

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
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <section className="space-y-2 text-xs leading-5 text-ink-3">
        <p>
          访问开关和访问密钥写入本地 SQLite 账本；绑定地址、端口和允许的 Host
          由启动参数或启动时检测决定，修改后需要重启。
        </p>
        <p>
          访问密钥只保存哈希，不保存明文，也不会在日志或页面中回显。局域网访问是 HTTP
          明文；需要公网、HTTPS 或多用户权限时另做安全设计。
        </p>
      </section>

      <ConfirmDialog
        open={confirmDisable}
        title="关闭局域网访问？"
        description={
          lanClient
            ? "你正在通过局域网访问；关闭后本页会在下次请求时失去连接。其他设备也将无法访问。本机回环仍可使用，但需要访问密钥。"
            : "关闭后，同一局域网的其他设备将无法访问。本机回环仍可使用，但需要访问密钥。"
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
        title={access.token_configured ? "生成随机访问密钥？" : "生成访问密钥？"}
        description="所有设备都需要用新密钥重新登录；新密钥只显示一次。生成后请立即复制保存。"
        confirmLabel={access.token_configured ? "生成新密钥" : "生成密钥"}
        busy={rotating}
        onOpenChange={setConfirmRotate}
        onConfirm={rotateToken}
      />

      <ConfirmDialog
        open={confirmCustomKey}
        title="保存自定义访问密钥？"
        description="保存后旧密钥和所有设备会话立即失效；请用新密钥重新登录。"
        confirmLabel="保存新密钥"
        busy={savingKey}
        onOpenChange={setConfirmCustomKey}
        onConfirm={saveCustomKey}
      />

      <TokenDialog
        open={tokenDialogOpen}
        token={newToken}
        onOpenChange={setTokenDialogOpen}
        onReload={reloadPage}
      />

      <RestartNoticeDialog
        notice={restartNotice}
        onClose={() => setRestartNotice(null)}
      />
    </div>
  );
}
