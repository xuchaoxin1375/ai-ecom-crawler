import {
  useEffect,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Layers,
  LayoutList,
  ListTodo,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Wrench,
} from "lucide-react";
import { getHealth } from "../lib/api";
import { cn } from "../lib/cn";

const SIDEBAR_KEY = "ecom.sidebar.pinned";
const SIDEBAR_EXPANDED = 248;
const SIDEBAR_RAIL = 64;

function readPinned(): boolean {
  try {
    const stored = localStorage.getItem(SIDEBAR_KEY);
    if (stored !== null) return stored === "true";
  } catch {
    // Storage can be unavailable in private mode; keep the default.
  }
  return true;
}

function persistPinned(pinned: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_KEY, String(pinned));
  } catch {
    // Persistence is a preference, not a functional requirement.
  }
}

function SidebarLink({
  to,
  icon,
  label,
  expanded,
  onPointerNavigate,
}: {
  to: string;
  icon: ReactNode;
  label: string;
  expanded: boolean;
  onPointerNavigate?: () => void;
}) {
  return (
    <NavLink
      className={({ isActive }) =>
        cn(
          "flex h-9 items-center gap-2.5 overflow-hidden rounded-control px-2.5 text-sm text-ink-2 transition-colors hover:bg-surface-muted hover:text-ink",
          isActive && "bg-accent-soft font-semibold text-ink",
        )
      }
      to={to}
      aria-label={expanded ? undefined : label}
      title={expanded ? undefined : label}
      onClick={(event) => {
        if (event.detail > 0) onPointerNavigate?.();
      }}
    >
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center text-ink-3"
        aria-hidden="true"
      >
        {icon}
      </span>
      <span
        className={cn(
          "truncate whitespace-nowrap transition-opacity duration-150",
          expanded ? "opacity-100" : "opacity-0",
        )}
        aria-hidden={!expanded || undefined}
      >
        {label}
      </span>
    </NavLink>
  );
}

function SidebarAction({
  href,
  icon,
  label,
  expanded,
  onPointerNavigate,
}: {
  href: string;
  icon: ReactNode;
  label: string;
  expanded: boolean;
  onPointerNavigate?: () => void;
}) {
  return (
    <a
      className="flex h-9 items-center gap-2.5 overflow-hidden rounded-control px-2.5 text-sm text-ink-2 transition-colors hover:bg-surface-muted hover:text-ink"
      href={href}
      aria-label={expanded ? undefined : label}
      title={expanded ? undefined : label}
      onClick={(event) => {
        if (event.detail > 0) onPointerNavigate?.();
      }}
    >
      <span
        className="flex h-5 w-5 shrink-0 items-center justify-center text-ink-3"
        aria-hidden="true"
      >
        {icon}
      </span>
      <span
        className={cn(
          "truncate whitespace-nowrap transition-opacity duration-150",
          expanded ? "opacity-100" : "opacity-0",
        )}
        aria-hidden={!expanded || undefined}
      >
        {label}
      </span>
    </a>
  );
}

function ServicePill() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 30_000,
  });

  const tone = health.isError ? "danger" : health.data ? "success" : "neutral";
  const text = health.isError
    ? "服务异常"
    : health.data
      ? health.data.worker === "managed"
        ? "服务正常 · 托管 worker"
        : "服务正常 · 外部 worker"
      : "读取中";
  const title = health.isError
    ? health.error instanceof Error
      ? health.error.message
      : String(health.error)
    : health.data
      ? `版本 ${health.data.version} · worker ${health.data.worker ?? "未知"}`
      : "正在读取 /api/health";

  return (
    <span
      className={cn(
        "inline-flex min-w-[176px] items-center justify-center gap-2 rounded-full border px-3 py-1 text-xs whitespace-nowrap",
        tone === "success" && "border-success/20 bg-success-soft text-success",
        tone === "danger" && "border-danger/20 bg-danger-soft text-danger",
        tone === "neutral" && "border-line bg-surface-muted text-ink-3",
      )}
      title={title}
      role="status"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      {text}
    </span>
  );
}

export function AppShell() {
  const location = useLocation();
  const mainRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const keyboardFocusRef = useRef(false);
  const [pinned, setPinned] = useState(readPinned);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [suppressed, setSuppressed] = useState(false);
  const siteMatch = location.pathname.match(/^\/batches\/([^/]+)\/sites\/[^/]+/);
  const batchMatch = location.pathname.match(/^\/batches\/([^/]+)/);
  const isTaskDetail = /^\/tasks\/[^/]+/.test(location.pathname);
  const isBuildDetail = /^\/builds\/[^/]+/.test(location.pathname);
  const isSiteDetail = Boolean(siteMatch);
  const isBatchDetail = Boolean(batchMatch) && !isSiteDetail;
  const showBreadcrumb = isBatchDetail || isSiteDetail || isTaskDetail || isBuildDetail;

  const visualOpen = pinned || (!suppressed && (hovered || focused));
  const peeking = !pinned && visualOpen;
  const slotWidth = pinned ? SIDEBAR_EXPANDED : SIDEBAR_RAIL;
  const visualWidth = visualOpen ? SIDEBAR_EXPANDED : SIDEBAR_RAIL;
  const toggleLabel = pinned
    ? "收起侧边栏"
    : visualOpen
      ? "展开并固定侧边栏"
      : "展开侧边栏";

  useEffect(() => {
    persistPinned(pinned);
  }, [pinned]);

  useEffect(() => {
    const title = isTaskDetail
      ? "任务详情"
      : isBuildDetail
        ? "构建详情"
        : isSiteDetail
          ? "站点详情"
          : isBatchDetail
            ? "批次详情"
            : location.pathname.startsWith("/tasks")
              ? "全部任务"
              : location.pathname.startsWith("/builds")
                ? "构建记录"
                : "采集批次";
    document.title = `${title} · 电商采集`;
  }, [isBatchDetail, isBuildDetail, isSiteDetail, isTaskDetail, location.pathname]);

  useEffect(() => {
    function onPointerDown() {
      keyboardFocusRef.current = false;
    }
    function onKeyDown() {
      keyboardFocusRef.current = true;
    }
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("keydown", onKeyDown, true);
    };
  }, []);

  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [location.pathname]);

  function togglePinned() {
    const next = !pinned;
    setPinned(next);
    setSuppressed(!next);
  }

  function handleMouseEnter() {
    if (pinned) return;
    setHovered(true);
    setSuppressed(false);
  }

  function handleMouseLeave() {
    setHovered(false);
    if (document.activeElement !== toggleRef.current) setSuppressed(false);
  }

  function handleFocus(event: FocusEvent<HTMLElement>) {
    const focusVisible = keyboardFocusRef.current;
    setFocused(focusVisible);
    if (focusVisible && event.target !== toggleRef.current) setSuppressed(false);
  }

  function handleBlur(event: FocusEvent<HTMLElement>) {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
      setFocused(false);
    }
  }

  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key !== "Escape" || pinned || !visualOpen) return;
    event.preventDefault();
    setHovered(false);
    setFocused(false);
    setSuppressed(true);
    toggleRef.current?.focus();
  }

  return (
    <div className="min-w-[1180px] bg-canvas text-ink">
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-control focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:text-white"
        href="#main"
      >
        跳到主要内容
      </a>

      <header className="fixed inset-x-0 top-0 z-50 flex h-14 items-center border-b border-line bg-surface pr-8">
        <div
          className="flex h-full shrink-0 items-center border-r border-line transition-[width] duration-300 ease-out"
          style={{ width: slotWidth }}
        >
          <a
            className={cn(
              "flex h-9 w-full items-center gap-2.5 rounded-control text-ink transition-colors hover:bg-surface-muted",
              pinned ? "px-[18px]" : "justify-center",
            )}
            href="#/batches"
            aria-label="电商采集首页"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] bg-accent text-white">
              <Layers size={16} strokeWidth={1.75} aria-hidden="true" />
            </span>
            {pinned ? (
              <span className="truncate text-[15px] font-semibold tracking-[0.01em]">
                电商采集
              </span>
            ) : null}
          </a>
        </div>

        {showBreadcrumb ? (
          <nav
            className="flex min-w-0 items-center gap-2 px-8 text-xs text-ink-3"
            aria-label="面包屑"
          >
            {isTaskDetail ? (
              <>
                <a className="hover:text-ink" href="#/tasks">
                  全部任务
                </a>
                <span className="text-line-strong" aria-hidden="true">
                  /
                </span>
                <span className="font-medium text-ink">任务详情</span>
              </>
            ) : isBuildDetail ? (
              <>
                <a className="hover:text-ink" href="#/builds">
                  构建记录
                </a>
                <span className="text-line-strong" aria-hidden="true">
                  /
                </span>
                <span className="font-medium text-ink">构建详情</span>
              </>
            ) : (
              <>
                <a className="hover:text-ink" href="#/batches">
                  采集批次
                </a>
                <span className="text-line-strong" aria-hidden="true">
                  /
                </span>
                {isSiteDetail ? (
                  <>
                    <a
                      className="hover:text-ink"
                      href={`#/batches/${encodeURIComponent(siteMatch?.[1] ?? "")}`}
                    >
                      批次详情
                    </a>
                    <span className="text-line-strong" aria-hidden="true">
                      /
                    </span>
                    <span className="font-medium text-ink">站点详情</span>
                  </>
                ) : (
                  <span className="font-medium text-ink">批次详情</span>
                )}
              </>
            )}
          </nav>
        ) : null}

        <div className="ml-auto flex shrink-0 items-center gap-3">
          <ServicePill />
        </div>
      </header>

      {/* The shell owns hover/focus peek; controls inside stay native links/buttons. */}
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
      <aside
        id="app-sidebar"
        ref={panelRef}
        aria-label="侧边栏"
        className={cn(
          "fixed bottom-0 left-0 top-14 z-40 overflow-hidden border-r border-line bg-surface transition-[width] duration-300 ease-out",
          peeking && "shadow-overlay",
        )}
        style={{ width: visualWidth }}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onFocusCapture={handleFocus}
        onBlurCapture={handleBlur}
        onKeyDown={handleKeyDown}
      >
        <div className="flex h-full flex-col">
          <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="主导航">
            <div className="space-y-0.5">
              <SidebarLink
                to="/batches"
                icon={<LayoutList size={17} />}
                label="采集批次"
                expanded={visualOpen}
                onPointerNavigate={() => {
                  if (!pinned) setFocused(false);
                }}
              />
              <SidebarLink
                to="/tasks"
                icon={<ListTodo size={17} />}
                label="全部任务"
                expanded={visualOpen}
                onPointerNavigate={() => {
                  if (!pinned) setFocused(false);
                }}
              />
              <SidebarLink
                to="/builds"
                icon={<Wrench size={17} />}
                label="构建记录"
                expanded={visualOpen}
                onPointerNavigate={() => {
                  if (!pinned) setFocused(false);
                }}
              />
              <SidebarAction
                href="#/batches?new=1"
                icon={<Plus size={17} />}
                label="新建批次"
                expanded={visualOpen}
                onPointerNavigate={() => {
                  if (!pinned) setFocused(false);
                }}
              />
            </div>
          </nav>

          <div className="border-t border-line px-3 py-3">
            <button
              ref={toggleRef}
              type="button"
              className="flex h-9 w-full items-center gap-2.5 overflow-hidden rounded-control px-2.5 text-sm text-ink-2 transition-colors hover:bg-surface-muted hover:text-ink"
              aria-expanded={visualOpen}
              aria-controls="app-sidebar"
              aria-label={toggleLabel}
              title={toggleLabel}
              onClick={togglePinned}
            >
              <span
                className="flex h-5 w-5 shrink-0 items-center justify-center text-ink-3"
                aria-hidden="true"
              >
                {pinned ? <PanelLeftClose size={17} /> : <PanelLeftOpen size={17} />}
              </span>
              <span
                className={cn(
                  "truncate whitespace-nowrap transition-opacity duration-150",
                  visualOpen ? "opacity-100" : "opacity-0",
                )}
                aria-hidden={!visualOpen || undefined}
              >
                {toggleLabel}
              </span>
            </button>
          </div>
        </div>
      </aside>

      <main
        id="main"
        ref={mainRef}
        className="min-h-screen pt-14 transition-[margin-left] duration-300 ease-out"
        style={{ marginLeft: slotWidth }}
        tabIndex={-1}
      >
        <div className="mx-auto w-full max-w-[1560px] px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
