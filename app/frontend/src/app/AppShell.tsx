import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  Cpu,
  Layers,
  ListTodo,
  ListTree,
  MemoryStick,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Settings2,
  Wrench,
  X,
} from "lucide-react";
import { getHealth, getSystemInfo } from "../lib/api";
import { cn } from "../lib/cn";

const SIDEBAR_KEY = "ecom.sidebar.pinned";
const SIDEBAR_EXPANDED = 248;
const SIDEBAR_RAIL = 64;
// 容器展开用强 S 曲线（CF 实况 250ms）；内层元素用柔和曲线，避免文字先于空间到位。
const SIDEBAR_DURATION = "duration-[var(--sidebar-duration)]";
const SIDEBAR_EASE = "ease-[var(--sidebar-ease)]";
const SIDEBAR_EASE_SOFT = "ease-[var(--sidebar-ease-soft)]";

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
          "overflow-hidden whitespace-nowrap transition-transform",
          SIDEBAR_DURATION,
          SIDEBAR_EASE_SOFT,
          expanded ? "translate-x-0" : "-translate-x-1",
        )}
        aria-hidden={!expanded || undefined}
      >
        {label}
      </span>
    </NavLink>
  );
}

function SidebarGroup({
  label,
  expanded,
  showLabel = true,
  children,
}: {
  label: string;
  expanded: boolean;
  showLabel?: boolean;
  children: ReactNode;
}) {
  return (
    <div className="relative grid gap-0.5" role="group" aria-label={label}>
      {showLabel ? (
        <div className="relative h-7" aria-hidden={!expanded || undefined}>
          <span
            aria-hidden="true"
            className={cn(
              "pointer-events-none absolute left-2 right-2 top-1/2 h-px bg-line transition-opacity",
              SIDEBAR_DURATION,
              SIDEBAR_EASE_SOFT,
              expanded ? "opacity-0" : "opacity-100",
            )}
          />
          <p
            className={cn(
              "pointer-events-none absolute inset-x-0 top-0 px-2.5 pb-1 pt-2 text-[10px] font-semibold tracking-[0.08em] text-ink-3 uppercase transition-opacity",
              SIDEBAR_DURATION,
              SIDEBAR_EASE_SOFT,
              expanded ? "opacity-100" : "opacity-0",
            )}
          >
            {label}
          </p>
        </div>
      ) : null}
      {children}
    </div>
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
  const shortText = health.isError ? "异常" : health.data ? "正常" : "读取中";
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
        "inline-flex min-w-0 items-center justify-center gap-1.5 rounded-full border px-2.5 py-1 text-xs whitespace-nowrap lg:min-w-[176px] lg:gap-2 lg:px-3",
        tone === "success" && "border-success/20 bg-success-soft text-success",
        tone === "danger" && "border-danger/20 bg-danger-soft text-danger",
        tone === "neutral" && "border-line bg-surface-muted text-ink-3",
      )}
      title={title}
      aria-label={text}
      role="status"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" aria-hidden="true" />
      <span className="hidden lg:inline">{text}</span>
      <span className="lg:hidden">{shortText}</span>
    </span>
  );
}

function ResourcePill() {
  const system = useQuery({
    queryKey: ["system"],
    queryFn: ({ signal }) => getSystemInfo(signal),
    refetchInterval: 15_000,
    staleTime: 5_000,
  });
  const resources = system.data?.resources;
  if (
    !resources?.available ||
    resources.cpu_percent == null ||
    resources.memory_percent == null
  ) {
    return null;
  }
  const cpu = Math.round(resources.cpu_percent);
  const memory = Math.round(resources.memory_percent);
  const storage = system.data?.storage;
  const disk =
    storage && storage.disk_total_bytes > 0
      ? Math.round((storage.disk_used_bytes / storage.disk_total_bytes) * 100)
      : null;
  const tone =
    cpu >= 90 || memory >= 90
      ? "danger"
      : cpu >= 70 || memory >= 70
        ? "warning"
        : "neutral";
  const detail = `CPU ${cpu}% · 内存 ${memory}%${
    disk == null ? "" : ` · 磁盘 ${disk}%`
  }`;

  return (
    <Link
      to="/settings?focus=resources"
      className={cn(
        "hidden items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] whitespace-nowrap transition-colors md:inline-flex",
        tone === "warning" &&
          "border-warning/20 bg-warning-soft text-warning hover:bg-warning-soft/80",
        tone === "danger" &&
          "border-danger/20 bg-danger-soft text-danger hover:bg-danger-soft/80",
        tone === "neutral" && "border-line bg-surface-muted text-ink-2 hover:text-ink",
      )}
      title={detail}
      aria-label={`系统资源：${detail}；打开系统设置`}
    >
      <Cpu size={12} aria-hidden="true" />
      <span className="text-[10px] font-medium">CPU</span>
      <span className="tabular">{cpu}%</span>
      <span className="text-ink-3" aria-hidden="true">
        ·
      </span>
      <MemoryStick size={12} aria-hidden="true" />
      <span className="text-[10px] font-medium">内存</span>
      <span className="tabular">{memory}%</span>
    </Link>
  );
}

export function AppShell() {
  const location = useLocation();
  const mainRef = useRef<HTMLElement | null>(null);
  const panelRef = useRef<HTMLElement | null>(null);
  const toggleRef = useRef<HTMLButtonElement | null>(null);
  const mobilePanelRef = useRef<HTMLElement | null>(null);
  const mobileTriggerRef = useRef<HTMLButtonElement | null>(null);
  const mobileCloseRef = useRef<HTMLButtonElement | null>(null);
  const mobileReturnFocusRef = useRef<HTMLElement | null>(null);
  const keyboardFocusRef = useRef(false);
  const [pinned, setPinned] = useState(readPinned);
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [suppressed, setSuppressed] = useState(false);
  const [mobileOpenPath, setMobileOpenPath] = useState<string | null>(null);
  const isTaskDetail = /^\/tasks\/[^/]+/.test(location.pathname);
  const isBuildDetail = /^\/builds\/[^/]+/.test(location.pathname);
  const isModelSettings = location.pathname.startsWith("/models");
  const isSystemSettings = location.pathname.startsWith("/settings");
  const isWorkbench = location.pathname.startsWith("/workbench");
  const showBreadcrumb = isTaskDetail || isBuildDetail;

  const visualOpen = pinned || (!suppressed && (hovered || focused));
  const peeking = !pinned && visualOpen;
  const mobileOpen = mobileOpenPath === location.pathname;
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
    document.documentElement.classList.toggle("workbench-fullbleed", isWorkbench);
    return () => document.documentElement.classList.remove("workbench-fullbleed");
  }, [isWorkbench]);

  useEffect(() => {
    const title = isTaskDetail
      ? "任务详情"
      : isBuildDetail
        ? "构建详情"
        : isModelSettings
          ? "模型配置"
          : isSystemSettings
            ? "系统设置"
            : location.pathname.startsWith("/workbench")
              ? "任务工作台"
              : location.pathname.startsWith("/tasks")
                ? "全部任务"
                : location.pathname.startsWith("/builds")
                  ? "构建记录"
                  : "任务工作台";
    document.title = `${title} · 电商采集`;
  }, [
    isBuildDetail,
    isModelSettings,
    isSystemSettings,
    isTaskDetail,
    location.pathname,
  ]);

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

  useEffect(() => {
    const media = window.matchMedia("(min-width: 1024px)");
    function onChange() {
      if (media.matches) setMobileOpenPath(null);
    }
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (!mobileOpen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const timer = window.setTimeout(() => mobileCloseRef.current?.focus(), 0);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.clearTimeout(timer);
      mobileReturnFocusRef.current?.focus?.({ preventScroll: true });
    };
  }, [mobileOpen]);

  function openMobile() {
    mobileReturnFocusRef.current = document.activeElement as HTMLElement | null;
    setMobileOpenPath(location.pathname);
  }

  function closeMobile() {
    setMobileOpenPath(null);
  }

  function handleMobileKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeMobile();
      mobileTriggerRef.current?.focus();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = mobilePanelRef.current?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
    );
    if (!focusable?.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

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
    <div
      className="bg-canvas text-ink"
      style={{ "--sidebar-slot": `${slotWidth}px` } as CSSProperties}
    >
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-control focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:text-white"
        href="#main"
      >
        跳到主要内容
      </a>

      <header
        className={cn(
          "fixed inset-x-0 top-0 z-50 flex h-14 items-center border-b border-line bg-surface",
          isWorkbench ? "pr-2.5" : "pr-3 sm:pr-6 lg:pr-8",
        )}
      >
        <div
          className={cn(
            "hidden h-full shrink-0 items-center overflow-hidden border-r border-line transition-[width] lg:flex",
            SIDEBAR_DURATION,
            SIDEBAR_EASE,
          )}
          style={{ width: slotWidth }}
        >
          <a
            className={cn(
              "flex h-9 w-full items-center overflow-hidden rounded-control text-ink transition-colors hover:bg-surface-muted",
              pinned ? "px-[18px]" : "justify-center",
            )}
            href="#/workbench"
            aria-label="电商采集首页"
          >
            <span
              className={cn(
                "flex h-7 w-7 shrink-0 origin-left items-center justify-center rounded-[7px] bg-accent text-white transition-transform",
                SIDEBAR_DURATION,
                SIDEBAR_EASE_SOFT,
                pinned ? "scale-100" : "scale-[0.84]",
              )}
            >
              <Layers size={16} strokeWidth={1.75} aria-hidden="true" />
            </span>
            <span
              className={cn(
                "overflow-hidden whitespace-nowrap text-[15px] font-semibold tracking-[0.01em] transition-[max-width,padding]",
                SIDEBAR_DURATION,
                SIDEBAR_EASE_SOFT,
                pinned ? "max-w-[160px] pl-2.5" : "max-w-0 pl-0",
              )}
              aria-hidden={!pinned || undefined}
            >
              电商采集
            </span>
          </a>
        </div>

        <div className="flex min-w-0 items-center gap-1 lg:hidden">
          <button
            ref={mobileTriggerRef}
            type="button"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control text-ink-2 transition-colors hover:bg-surface-muted hover:text-ink"
            aria-label="打开导航菜单"
            aria-expanded={mobileOpen}
            aria-controls="mobile-sidebar"
            onClick={openMobile}
          >
            <Menu size={20} aria-hidden="true" />
          </button>
          <a
            className="flex min-w-0 items-center gap-2 rounded-control text-ink"
            href="#/workbench"
            aria-label="电商采集首页"
          >
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] bg-accent text-white">
              <Layers size={16} strokeWidth={1.75} aria-hidden="true" />
            </span>
            <span className="hidden truncate text-[15px] font-semibold tracking-[0.01em] sm:inline">
              电商采集
            </span>
          </a>
        </div>

        {showBreadcrumb ? (
          <nav
            className="hidden min-w-0 items-center gap-2 px-4 text-xs text-ink-3 md:flex lg:px-8"
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
            ) : null}
          </nav>
        ) : null}

        <div className="ml-auto flex shrink-0 items-center gap-2 pl-2">
          <ResourcePill />
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
          "fixed bottom-0 left-0 top-14 z-40 hidden overflow-hidden border-r border-line bg-surface transition-[width] lg:block",
          SIDEBAR_DURATION,
          SIDEBAR_EASE,
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
            <div className="space-y-1">
              <SidebarGroup label="采集工作台" expanded={visualOpen} showLabel={false}>
                <SidebarLink
                  to="/workbench"
                  icon={<ListTree size={17} />}
                  label="任务工作台"
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
              </SidebarGroup>
              <SidebarGroup label="规则与设置" expanded={visualOpen}>
                <SidebarLink
                  to="/builds"
                  icon={<Wrench size={17} />}
                  label="构建记录"
                  expanded={visualOpen}
                  onPointerNavigate={() => {
                    if (!pinned) setFocused(false);
                  }}
                />
                <SidebarLink
                  to="/models"
                  icon={<Cpu size={17} />}
                  label="模型配置"
                  expanded={visualOpen}
                  onPointerNavigate={() => {
                    if (!pinned) setFocused(false);
                  }}
                />
                <SidebarLink
                  to="/settings"
                  icon={<Settings2 size={17} />}
                  label="系统设置"
                  expanded={visualOpen}
                  onPointerNavigate={() => {
                    if (!pinned) setFocused(false);
                  }}
                />
              </SidebarGroup>
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
                  "overflow-hidden whitespace-nowrap transition-transform",
                  SIDEBAR_DURATION,
                  SIDEBAR_EASE_SOFT,
                  visualOpen ? "translate-x-0" : "-translate-x-1",
                )}
                aria-hidden={!visualOpen || undefined}
              >
                {toggleLabel}
              </span>
            </button>
          </div>
        </div>
      </aside>

      {mobileOpen ? (
        <div className="fixed inset-0 z-[60] lg:hidden">
          <button
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            className="animate-overlay-in absolute inset-0 bg-ink/35"
            onClick={closeMobile}
          />
          {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions */}
          <aside
            id="mobile-sidebar"
            ref={mobilePanelRef}
            role="dialog"
            aria-modal="true"
            aria-label="导航菜单"
            className="animate-menu-in absolute inset-y-0 left-0 flex w-[min(320px,calc(100vw-48px))] flex-col border-r border-line bg-surface shadow-overlay"
            onKeyDown={handleMobileKeyDown}
          >
            <div className="flex h-14 items-center justify-between gap-3 border-b border-line px-4">
              <a
                className="flex min-w-0 items-center gap-2.5 rounded-control text-ink"
                href="#/workbench"
                aria-label="电商采集首页"
                onClick={closeMobile}
              >
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-[7px] bg-accent text-white">
                  <Layers size={16} strokeWidth={1.75} aria-hidden="true" />
                </span>
                <span className="truncate text-[15px] font-semibold tracking-[0.01em]">
                  电商采集
                </span>
              </a>
              <button
                ref={mobileCloseRef}
                type="button"
                className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭导航菜单"
                onClick={closeMobile}
              >
                <X size={18} aria-hidden="true" />
              </button>
            </div>
            <nav className="flex-1 overflow-y-auto px-3 py-4" aria-label="主导航">
              <div className="space-y-1">
                <SidebarGroup label="采集工作台" expanded showLabel={false}>
                  <SidebarLink
                    to="/workbench"
                    icon={<ListTree size={17} />}
                    label="任务工作台"
                    expanded
                    onPointerNavigate={closeMobile}
                  />
                  <SidebarLink
                    to="/tasks"
                    icon={<ListTodo size={17} />}
                    label="全部任务"
                    expanded
                    onPointerNavigate={closeMobile}
                  />
                </SidebarGroup>
                <SidebarGroup label="规则与设置" expanded>
                  <SidebarLink
                    to="/builds"
                    icon={<Wrench size={17} />}
                    label="构建记录"
                    expanded
                    onPointerNavigate={closeMobile}
                  />
                  <SidebarLink
                    to="/models"
                    icon={<Cpu size={17} />}
                    label="模型配置"
                    expanded
                    onPointerNavigate={closeMobile}
                  />
                  <SidebarLink
                    to="/settings"
                    icon={<Settings2 size={17} />}
                    label="系统设置"
                    expanded
                    onPointerNavigate={closeMobile}
                  />
                </SidebarGroup>
              </div>
            </nav>
            <div className="border-t border-line px-4 py-3">
              <p className="text-xs leading-5 text-ink-3">
                本地单用户工作台；服务地址由当前浏览器决定。
              </p>
            </div>
          </aside>
        </div>
      ) : null}

      <main
        id="main"
        ref={mainRef}
        className={cn(
          "min-h-screen pt-14 transition-none lg:ml-[var(--sidebar-slot)] lg:transition-[margin-left]",
          SIDEBAR_DURATION,
          SIDEBAR_EASE,
        )}
        tabIndex={-1}
      >
        <div
          className={cn(
            "w-full",
            !isWorkbench && "mx-auto max-w-[1560px] px-4 py-6 sm:px-6 lg:px-8 lg:py-8",
          )}
        >
          <Outlet />
        </div>
      </main>
    </div>
  );
}
