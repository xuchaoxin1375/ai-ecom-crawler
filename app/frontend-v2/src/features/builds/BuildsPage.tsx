import { useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input, Select } from "../../components/ui/Input";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { PageHeader } from "../../components/ui/PageHeader";

const LIMIT = 100;

function siteHref(build: BuildStatus): string | null {
  if (!build.batch_id || !build.site_key) return null;
  return `/batches/${encodeURIComponent(build.batch_id)}/sites/${encodeURIComponent(
    build.site_key,
  )}`;
}

function matchesQuery(build: BuildStatus, query: string): boolean {
  const text = query.trim().toLowerCase();
  if (!text) return true;
  return [
    build.build_id,
    build.site_key,
    build.batch_id,
    build.rule?.rule_id,
    build.rule?.rule_version,
    build.error,
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(text));
}

export function BuildsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const state = searchParams.get("state") ?? "";
  const mode = searchParams.get("mode") ?? "";
  const queryParam = searchParams.get("q") ?? "";
  const [queryDraft, setQueryDraft] = useState(queryParam);

  const query = useQuery({
    queryKey: ["builds", LIMIT],
    queryFn: ({ signal }) => getBuilds({ limit: LIMIT }, signal),
    refetchInterval: (current) =>
      (current.state.data?.builds ?? []).some(buildIsActive) ? 5000 : false,
  });

  const builds = useMemo(() => query.data?.builds ?? [], [query.data?.builds]);
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

  const columns: DataTableColumn<BuildStatus>[] = [
    {
      key: "build",
      header: "构建",
      width: "28%",
      cell: (build) => (
        <div className="min-w-0">
          <Link
            className="block truncate font-semibold text-ink hover:text-accent hover:underline"
            to={`/builds/${encodeURIComponent(build.build_id)}`}
          >
            {build.site_key || "未关联站点"}
          </Link>
          <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-3">
            {build.build_id}
          </span>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-ink-3">
            <Badge tone={build.mode === "repair" ? "warning" : "neutral"} dot={false}>
              {buildModeLabel(build.mode)}
            </Badge>
            {build.batch_id ? (
              <Link
                className="hover:text-accent hover:underline"
                to={`/batches/${encodeURIComponent(build.batch_id)}`}
              >
                {build.batch_id}
              </Link>
            ) : (
              <span>未关联批次</span>
            )}
          </div>
        </div>
      ),
    },
    {
      key: "site",
      header: "站点／规则",
      width: "22%",
      cell: (build) => {
        const href = siteHref(build);
        return (
          <div className="min-w-0">
            {href ? (
              <Link
                className="block truncate text-sm font-medium text-ink hover:text-accent hover:underline"
                to={href}
              >
                {build.site_key}
              </Link>
            ) : (
              <span className="block truncate text-sm text-ink">
                {build.site_key || "—"}
              </span>
            )}
            <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-3">
              {build.rule
                ? `${build.rule.rule_id}@${build.rule.rule_version}`
                : build.mode === "repair" && build.source_rule?.rule_version
                  ? `源规则 @${build.source_rule.rule_version}`
                  : "尚未安装规则"}
            </span>
          </div>
        );
      },
    },
    {
      key: "state",
      header: "状态／结果",
      width: "18%",
      cell: (build) => (
        <div className="space-y-1">
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
        </div>
      ),
    },
    {
      key: "time",
      header: "时间",
      width: "16%",
      cell: (build) => (
        <div className="text-xs text-ink-3">
          <p>更新 {formatTime(build.updated_at)}</p>
          <p className="mt-0.5">
            {build.elapsed_seconds !== null
              ? `耗时 ${Math.round(build.elapsed_seconds)} 秒`
              : build.finished_at
                ? "未启动"
                : build.state === "QUEUED"
                  ? "等待开始"
                  : "尚未结束"}
          </p>
        </div>
      ),
    },
    {
      key: "actions",
      header: "操作",
      width: "16%",
      align: "right",
      skeleton: false,
      cell: (build) => (
        <div className="flex justify-end">
          <Button asChild size="sm">
            <Link to={`/builds/${encodeURIComponent(build.build_id)}`}>查看详情</Link>
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="规则生产"
        title="构建记录"
        description="查看站点方案构建和规则修复的会话、自动修复轮次、主机验证与审批请求。构建与采集任务分开记录。"
        actions={
          <Button onClick={() => void query.refetch()} disabled={query.isFetching}>
            <RefreshCw
              className={query.isFetching ? "animate-spin" : undefined}
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
              placeholder="构建 ID、站点、批次或规则版本"
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

        <div className="flex items-center justify-between gap-4 border-b border-line px-5 py-2.5">
          <p className="text-xs text-ink-3" role="status">
            {query.isPending
              ? "正在读取构建记录…"
              : `显示 ${visible.length} / ${builds.length} 条${
                  query.isFetching ? " · 更新中…" : ""
                }`}
          </p>
        </div>

        <DataTable
          caption="构建记录"
          columns={columns}
          rows={visible}
          rowKey={(build) => build.build_id}
          density="compact"
          loading={query.isPending}
          empty={
            <EmptyState
              title={hasFilters ? "没有符合条件的构建" : "还没有构建记录"}
              description={
                hasFilters
                  ? "换一个筛选条件，或重置后查看全部构建。"
                  : "从站点详情启动方案构建或规则修复后，构建会出现在这里。"
              }
              action={
                hasFilters ? (
                  <Button onClick={resetFilters}>重置筛选</Button>
                ) : (
                  <Button asChild>
                    <Link to="/batches">去采集批次</Link>
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
