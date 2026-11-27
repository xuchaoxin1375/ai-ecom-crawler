import { useMemo, useRef, useState, type MouseEvent } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";
import { getBuilds, type BuildStatus } from "../../lib/api";
import {
  buildOutcomeLabel,
  buildStateLabel,
  buildTone,
  formatTime,
} from "../../lib/format";
import { buildIsActive } from "../sites/site";
import { buildModeLabel } from "../sites/build";
import { useDelayedFlag, useManualRefresh } from "../../lib/liveRefresh";
import { rememberListReturn, useListReturnRestore } from "../../lib/listReturn";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { TableDisplayOptions } from "../../components/ui/TableDisplayOptions";
import {
  densityViewOptions,
  TableViewToggle,
} from "../../components/ui/TableViewToggle";
import { useTablePreferences } from "../../components/ui/tablePreferences";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input, Select } from "../../components/ui/Input";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { PageHeader } from "../../components/ui/PageHeader";

const LIMIT = 100;

function matchesQuery(build: BuildStatus, query: string): boolean {
  const text = query.trim().toLowerCase();
  if (!text) return true;
  return [
    build.build_id,
    build.site_key,
    build.rule?.rule_id,
    build.rule?.rule_version,
    build.error,
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(text));
}

export function BuildsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);
  const state = searchParams.get("state") ?? "";
  const mode = searchParams.get("mode") ?? "";
  const queryParam = searchParams.get("q") ?? "";
  const [queryDraft, setQueryDraft] = useState(queryParam);
  const resetWidthsRef = useRef<(() => void) | null>(null);
  const [widthsCustomized, setWidthsCustomized] = useState(false);

  const query = useQuery({
    queryKey: ["builds", LIMIT],
    queryFn: ({ signal }) => getBuilds({ limit: LIMIT }, signal),
    refetchInterval: (current) =>
      (current.state.data?.builds ?? []).some(buildIsActive) ? 5000 : false,
  });

  const builds = useMemo(() => query.data?.builds ?? [], [query.data?.builds]);
  const { refreshing, runRefresh } = useManualRefresh();
  const showUpdating = useDelayedFlag(query.isFetching);
  const visible = useMemo(
    () =>
      builds.filter((build) => {
        if (state === "active" && !buildIsActive(build)) return false;
        if (state && state !== "active" && build.state !== state) return false;
        if (mode && build.mode !== mode) return false;
        return matchesQuery(build, queryParam);
      }),
    [builds, mode, queryParam, state],
  );
  useListReturnRestore({
    ready: Boolean(query.data),
    locationKey: location.key,
    navigationState: location.state,
    containerRef: listRef,
  });

  const activeCount = builds.filter(buildIsActive).length;
  const queuedCount = builds.filter((build) => build.state === "QUEUED").length;
  const succeeded = builds.filter((build) => build.outcome === "succeeded").length;
  const failed = builds.filter((build) => build.outcome === "failed").length;
  const cancelled = builds.filter(
    (build) => build.outcome === "cancelled" || build.state === "CANCELLED",
  ).length;
  const hasFilters = Boolean(state || mode || queryParam);

  function updateParams(updates: Record<string, string>) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setSearchParams(next, { replace: true });
  }

  function submitSearch() {
    updateParams({ q: queryDraft.trim() });
  }

  function resetFilters() {
    setQueryDraft("");
    setSearchParams(new URLSearchParams(), { replace: true });
  }

  function openBuild(build: BuildStatus, event?: MouseEvent<HTMLAnchorElement>) {
    if (event) {
      if (
        event.defaultPrevented ||
        event.button !== 0 ||
        event.metaKey ||
        event.ctrlKey ||
        event.shiftKey ||
        event.altKey
      )
        return;
      event.preventDefault();
    }
    navigate(`/builds/${encodeURIComponent(build.build_id)}`, {
      state: rememberListReturn(location.key, {
        href: `${location.pathname}${location.search}`,
        label: "构建记录",
        scrollTop: window.scrollY,
        focusKey: build.build_id,
      }),
    });
  }

  const columns: DataTableColumn<BuildStatus>[] = [
    {
      key: "build",
      header: "构建",
      label: "构建",
      sortable: true,
      sortValue: (build) => build.site_key || build.build_id,
      width: 270,
      minWidth: 190,
      maxWidth: 720,
      cell: (build, { compact }) => (
        <div className="min-w-0">
          <Link
            className="block truncate font-semibold text-ink hover:text-accent hover:underline"
            to={`/builds/${encodeURIComponent(build.build_id)}`}
            onClick={(event) => openBuild(build, event)}
            data-return-focus={build.build_id}
            title={
              compact
                ? `${build.site_key || "未关联站点"} · ${build.build_id}`
                : undefined
            }
          >
            {build.site_key || "未关联站点"}
          </Link>
          {compact ? null : (
            <>
              <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-3">
                {build.build_id}
              </span>
              <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-ink-3">
                <Badge
                  tone={build.mode === "repair" ? "warning" : "neutral"}
                  dot={false}
                >
                  {buildModeLabel(build.mode)}
                </Badge>
              </div>
            </>
          )}
        </div>
      ),
    },
    {
      key: "site",
      header: "站点／规则",
      compactHeader: "规则",
      label: "站点／规则",
      hideable: true,
      sortable: true,
      sortValue: (build) => build.site_key || "",
      width: 230,
      minWidth: 160,
      maxWidth: 400,
      cell: (build, { compact }) => {
        const ruleText = build.rule
          ? `${build.rule.rule_id}@${build.rule.rule_version}`
          : build.mode === "repair" && build.source_rule?.rule_version
            ? `源规则 @${build.source_rule.rule_version}`
            : "尚未安装规则";
        if (compact) {
          return (
            <span
              className="block truncate font-mono text-xs text-ink-2"
              title={`${build.site_key || "未关联站点"}：${ruleText}`}
            >
              {ruleText}
            </span>
          );
        }
        return (
          <div className="min-w-0">
            <span className="block truncate text-sm text-ink">
              {build.site_key || "—"}
            </span>
            <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-3">
              {ruleText}
            </span>
          </div>
        );
      },
    },
    {
      key: "state",
      header: "状态／结果",
      label: "状态／结果",
      hideable: true,
      sortable: true,
      sortValue: (build) => build.state,
      width: 170,
      minWidth: 130,
      maxWidth: 300,
      cell: (build, { compact }) => (
        <div className={compact ? "flex flex-wrap items-center gap-1" : "space-y-1"}>
          <div className="flex flex-wrap items-center gap-1">
            <Badge tone={buildTone(build.state, build.outcome)} dot={false}>
              {buildStateLabel(build.state)}
            </Badge>
            {build.outcome ? (
              <Badge tone={buildTone(null, build.outcome)} dot={false}>
                {buildOutcomeLabel(build.outcome)}
              </Badge>
            ) : null}
          </div>
          {compact ? null : (
            <p className="text-xs text-ink-3">
              {build.state === "QUEUED" && build.queue_position
                ? `队列第 ${build.queue_position} 位`
                : build.repair_round
                  ? `自动修复 ${build.repair_round}/${build.repair_limit}`
                  : "未触发自动修复"}
              {build.state === "QUEUED"
                ? ""
                : build.validation?.status === "PASSED"
                  ? " · 验证通过"
                  : build.validation?.status === "FAILED"
                    ? " · 验证未通过"
                    : ""}
              {build.outcome === "interrupted" ? " · 可在详情继续" : ""}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "time",
      header: "时间",
      label: "时间",
      hideable: true,
      sortable: true,
      sortValue: (build) => build.updated_at,
      width: 145,
      minWidth: 110,
      maxWidth: 260,
      cell: (build, { compact }) => {
        const updated = formatTime(build.updated_at);
        const duration =
          build.elapsed_seconds !== null
            ? `${Math.round(build.elapsed_seconds)} 秒`
            : build.finished_at
              ? "未启动"
              : build.state === "QUEUED"
                ? "等待开始"
                : "尚未结束";
        if (compact) {
          const short = updated === "-" ? "-" : updated.slice(5);
          return (
            <span
              className="text-xs whitespace-nowrap text-ink-3"
              title={`更新 ${updated} · 耗时 ${duration}`}
            >
              {short} · {duration}
            </span>
          );
        }
        return (
          <div className="text-xs text-ink-3">
            <p>更新 {updated}</p>
            <p className="mt-0.5">耗时 {duration}</p>
          </div>
        );
      },
    },
    {
      key: "actions",
      header: "操作",
      label: "操作",
      width: 116,
      minWidth: 100,
      maxWidth: 180,
      resizable: false,
      sticky: "right",
      hideable: false,
      align: "right",
      skeleton: false,
      cell: (build) => (
        <div className="flex justify-end">
          <Button asChild size="sm">
            <Link
              to={`/builds/${encodeURIComponent(build.build_id)}`}
              onClick={(event) => openBuild(build, event)}
            >
              查看详情
            </Link>
          </Button>
        </div>
      ),
    },
  ];

  const table = useTablePreferences({
    tableKey: "builds",
    columns,
    defaultDensity: "default",
  });

  return (
    <div ref={listRef} tabIndex={-1} className="space-y-6">
      <PageHeader
        eyebrow="规则生产"
        title="构建记录"
        description="查看站点方案构建和规则修复的会话、自动修复轮次、主机验证与审批请求。构建与采集任务分开记录。"
        actions={
          <Button
            onClick={() => void runRefresh(() => query.refetch())}
            disabled={refreshing}
          >
            <RefreshCw
              className={refreshing ? "animate-spin" : undefined}
              size={14}
              aria-hidden="true"
            />
            刷新
          </Button>
        }
      />

      <MetricStrip
        label="构建概览"
        items={[
          {
            label: "构建总数",
            value: builds.length,
            hint: builds.length >= LIMIT ? `仅显示最近 ${LIMIT} 条` : "全部记录",
          },
          {
            label: "进行中",
            value: activeCount,
            hint: `排队 ${queuedCount} · 含暂停与审批`,
          },
          { label: "成功", value: succeeded, hint: "主机验证通过" },
          {
            label: "未成功",
            value: failed + cancelled,
            hint: "失败或主动取消",
          },
        ]}
      />

      {query.error ? (
        <ErrorNotice
          title="读取构建记录失败"
          message={
            query.error instanceof Error ? query.error.message : String(query.error)
          }
        />
      ) : null}

      <section className="rounded-panel border border-line bg-surface">
        <div className="flex flex-wrap items-end gap-3 border-b border-line px-5 py-3">
          <label
            className="flex min-w-[220px] flex-1 flex-col gap-1"
            htmlFor="build-search"
          >
            <span className="text-xs font-medium text-ink-3">搜索</span>
            <Input
              id="build-search"
              value={queryDraft}
              placeholder="构建 ID、站点或规则版本"
              onChange={(event) => setQueryDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") submitSearch();
              }}
            />
          </label>
          <label className="flex w-36 flex-col gap-1" htmlFor="build-state">
            <span className="text-xs font-medium text-ink-3">状态</span>
            <Select
              id="build-state"
              value={state}
              onChange={(event) => updateParams({ state: event.target.value })}
            >
              <option value="">全部状态</option>
              <option value="active">进行中</option>
              <option value="QUEUED">排队中</option>
              <option value="FINISHED">已结束</option>
              <option value="CANCELLED">已取消</option>
            </Select>
          </label>
          <label className="flex w-36 flex-col gap-1" htmlFor="build-mode">
            <span className="text-xs font-medium text-ink-3">模式</span>
            <Select
              id="build-mode"
              value={mode}
              onChange={(event) => updateParams({ mode: event.target.value })}
            >
              <option value="">全部模式</option>
              <option value="build">方案构建</option>
              <option value="repair">规则修复</option>
            </Select>
          </label>
          <Button onClick={submitSearch}>
            <Search size={13} aria-hidden="true" />
            搜索
          </Button>
          {hasFilters ? (
            <Button variant="ghost" onClick={resetFilters}>
              重置
            </Button>
          ) : null}
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-4 py-2.5 sm:px-5">
          <p className="text-xs text-ink-3" role="status">
            {query.isPending
              ? "正在读取构建记录…"
              : `显示 ${visible.length} / ${builds.length} 条${
                  showUpdating ? " · 更新中…" : ""
                }`}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <TableViewToggle
              value={table.density}
              options={densityViewOptions}
              onChange={table.setDensity}
            />
            <TableDisplayOptions
              columns={columns}
              visible={table.visible}
              onToggleColumn={table.toggleColumn}
              onResetWidths={() => resetWidthsRef.current?.()}
              widthsDefault={!widthsCustomized}
            />
          </div>
        </div>

        <DataTable
          caption="构建记录"
          columns={table.visibleColumns}
          rows={table.sortRows(visible)}
          rowKey={(build) => build.build_id}
          density={table.density}
          resizeKey="builds"
          sort={table.sort}
          onSort={table.toggleSort}
          onSortChange={table.setSort}
          mobileCards
          onResetWidthsReady={(reset) => {
            resetWidthsRef.current = reset;
          }}
          onWidthsCustomizedChange={setWidthsCustomized}
          loading={query.isPending}
          empty={
            <EmptyState
              title={hasFilters ? "没有符合条件的构建" : "还没有构建记录"}
              description={
                hasFilters
                  ? "换一个筛选条件，或重置后查看全部构建。"
                  : "站点构建入口暂未迁入任务工作台；已有构建记录仍可在这里查看。"
              }
              action={
                hasFilters ? (
                  <Button onClick={resetFilters}>重置筛选</Button>
                ) : (
                  <Button asChild>
                    <Link to="/workbench">去任务工作台</Link>
                  </Button>
                )
              }
            />
          }
        />
      </section>
    </div>
  );
}
