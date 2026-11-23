import { useEffect, useRef, type ReactNode } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Layers, LayoutList, ListChecks, Plus } from "lucide-react";
import { getHealth } from "../lib/api";
import { cn } from "../lib/cn";
import { Badge } from "../components/ui/Badge";

function SidebarLink({
  to,
  icon,
  children,
  external = false,
}: {
  to: string;
  icon: ReactNode;
  children: ReactNode;
  external?: boolean;
}) {
  const className =
    "flex h-9 items-center gap-2.5 rounded-control px-2.5 text-sm text-ink-2 transition-colors hover:bg-surface-muted hover:text-ink";

  if (external) {
    return (
      <a className={className} href={to}>
        <span
          className="flex h-5 w-5 items-center justify-center text-ink-3"
          aria-hidden="true"
        >
          {icon}
        </span>
        <span className="flex-1">{children}</span>
        <ExternalLink size={13} className="text-ink-3" aria-hidden="true" />
      </a>
    );
  }

  return (
    <NavLink
      className={({ isActive }) =>
        cn(className, isActive && "bg-accent-soft font-semibold text-ink")
      }
      to={to}
    >
      <span
        className="flex h-5 w-5 items-center justify-center text-ink-3"
        aria-hidden="true"
      >
        {icon}
      </span>
      <span>{children}</span>
    </NavLink>
  );
}

function SidebarAction({
  href,
  icon,
  children,
}: {
  href: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <a
      className="flex h-9 items-center gap-2.5 rounded-control px-2.5 text-sm text-ink-2 transition-colors hover:bg-surface-muted hover:text-ink"
      href={href}
    >
      <span
        className="flex h-5 w-5 items-center justify-center text-ink-3"
        aria-hidden="true"
      >
        {icon}
      </span>
      <span>{children}</span>
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
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs whitespace-nowrap",
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

  useEffect(() => {
    mainRef.current?.focus({ preventScroll: true });
    window.scrollTo({ top: 0, behavior: "auto" });
  }, [location.pathname]);

  return (
    <div className="min-w-[1180px] bg-canvas text-ink">
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-control focus:bg-accent focus:px-4 focus:py-2 focus:text-sm focus:text-white"
        href="#main"
      >
        跳到主要内容
      </a>

      <header className="fixed inset-x-0 top-0 z-50 flex h-14 items-center gap-3 border-b border-line bg-surface px-4">
        <a
          className="flex items-center gap-2.5 rounded-control px-1.5 py-1 text-ink hover:bg-surface-muted"
          href="#/batches"
          aria-label="电商采集首页"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-[7px] bg-accent text-white">
            <Layers size={16} strokeWidth={1.75} aria-hidden="true" />
          </span>
          <span className="text-[15px] font-semibold tracking-[0.01em]">电商采集</span>
        </a>

        <span className="h-5 w-px bg-line" aria-hidden="true" />

        <nav
          className="flex min-w-0 items-center gap-2 text-xs text-ink-3"
          aria-label="面包屑"
        >
          <a className="hover:text-ink" href="#/batches">
            采集批次
          </a>
          <span className="text-line-strong" aria-hidden="true">
            /
          </span>
          <span className="font-medium text-ink">批次列表</span>
        </nav>

        <div className="ml-auto flex items-center gap-3">
          <Badge tone="info" dot={false}>
            桌面端试点
          </Badge>
          <ServicePill />
        </div>
      </header>

      <aside className="fixed bottom-0 left-0 top-14 z-40 w-[248px] border-r border-line bg-surface">
        <div className="flex h-full flex-col">
          <nav className="flex-1 space-y-6 px-3 py-4" aria-label="主导航">
            <div>
              <p className="px-2.5 pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-ink-3">
                工作台
              </p>
              <div className="space-y-0.5">
                <SidebarLink to="/batches" icon={<LayoutList size={17} />}>
                  采集批次
                </SidebarLink>
                <SidebarLink
                  to="/batch/#/tasks"
                  icon={<ListChecks size={17} />}
                  external
                >
                  全部任务
                </SidebarLink>
                <SidebarAction href="#/batches?new=1" icon={<Plus size={17} />}>
                  新建批次
                </SidebarAction>
              </div>
            </div>

            <div>
              <p className="px-2.5 pb-1.5 text-[11px] font-semibold tracking-[0.08em] text-ink-3">
                系统
              </p>
              <div className="space-y-0.5">
                <SidebarLink to="/batch/" icon={<ExternalLink size={17} />} external>
                  旧版工作台
                </SidebarLink>
                <SidebarLink to="/legacy" icon={<ExternalLink size={17} />} external>
                  技术兜底入口
                </SidebarLink>
              </div>
            </div>
          </nav>

          <div className="border-t border-line px-4 py-4">
            <p className="text-xs font-medium text-ink-2">v2 前端试点</p>
            <p className="mt-1 text-xs leading-5 text-ink-3">
              当前覆盖桌面端批次列表和新建批次弹窗；详情、任务仍由旧版处理。
            </p>
            <a
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:text-accent-hover hover:underline"
              href="/batch/"
            >
              返回旧版
              <ExternalLink size={12} aria-hidden="true" />
            </a>
          </div>
        </div>
      </aside>

      <main
        id="main"
        ref={mainRef}
        className="ml-[248px] min-h-screen pt-14"
        tabIndex={-1}
      >
        <div className="mx-auto w-full max-w-[1560px] px-8 py-8">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
