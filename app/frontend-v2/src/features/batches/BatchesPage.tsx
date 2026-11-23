import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Plus, RefreshCw, RotateCcw, Search, X } from "lucide-react";
import { getBatches, type BatchSummary } from "../../lib/api";
import { formatNumber, formatTime } from "../../lib/format";
import { summarizeBatches } from "./summary";
import { NewBatchDialog } from "./NewBatchDialog";
import { PageHeader } from "../../components/ui/PageHeader";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { BatchStatusBadge } from "../../components/ui/BatchStatusBadge";
import { Button } from "../../components/ui/Button";
import { Checkbox, Input, Select } from "../../components/ui/Input";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { ReadinessBar } from "../../components/ui/ReadinessBar";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

const STATUS_OPTIONS = [
  { value: "", label: "全部状态" },
  { value: "DRAFT", label: "草稿" },
  { value: "PARTIAL_READY", label: "部分就绪" },
  { value: "RUNNING", label: "运行中" },
  { value: "PARTIAL", label: "部分完成" },
  { value: "FINISHED", label: "已完成" },
  { value: "ARCHIVED", label: "已归档" },
];

function batchHref(batchId: string): string {
  return `/batch/#/batches/${encodeURIComponent(batchId)}`;
}

function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ink-3">{label}</span>
      {children}
    </label>
  );
}

export function BatchesPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const status = searchParams.get("status") ?? "";
  const country = searchParams.get("country") ?? "";
  const category = searchParams.get("category") ?? "";
  const queryParam = searchParams.get("q") ?? "";
  const includeArchived = searchParams.get("archived") === "1";
  const isNewOpen = searchParams.get("new") === "1";

  const [notice, setNotice] = useState<{
    tone: "success" | "warning";
    text: string;
  } | null>(null);
  const [countryDraft, setCountryDraft] = useState(country);
  const [categoryDraft, setCategoryDraft] = useState(category);
  const [queryDraft, setQueryDraft] = useState(queryParam);

  // URL is the source of truth; keep the editable drafts in sync when filters
  // change externally (back/forward or reset).
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setCountryDraft(country), [country]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setCategoryDraft(category), [category]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setQueryDraft(queryParam), [queryParam]);

  function updateParam(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  }

  function commitText(key: string, value: string) {
    if ((searchParams.get(key) ?? "") !== value) updateParam(key, value);
  }

  function resetFilters() {
    setSearchParams(new URLSearchParams(), { replace: true });
    setCountryDraft("");
    setCategoryDraft("");
    setQueryDraft("");
  }

  function openNewBatch() {
    const next = new URLSearchParams(searchParams);
    next.set("new", "1");
    setSearchParams(next, { replace: true });
  }

  function closeNewBatch() {
    const next = new URLSearchParams(searchParams);
    next.delete("new");
    setSearchParams(next, { replace: true });
  }

  const query = useQuery({
    queryKey: ["batches", status, country, category, includeArchived],
    queryFn: ({ signal }) =>
      getBatches(
        {
          status: status || undefined,
          country: country || undefined,
          category: category || undefined,
          includeArchived,
        },
        signal,
      ),
    placeholderData: keepPreviousData,
  });

  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const total = query.data?.total ?? 0;
  const summary = summarizeBatches(items, total);
  const loading = query.isPending;

  const visibleItems = useMemo(() => {
    const needle = queryDraft.trim().toLowerCase();
    if (!needle) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(needle) ||
        item.batch_id.toLowerCase().includes(needle),
    );
  }, [items, queryDraft]);

  const hasFilters = Boolean(status || country || category || queryParam);
  const errorText =
    query.error instanceof Error ? query.error.message : String(query.error);
  const unavailable = loading || (query.isError && !query.data);
  const showTable = !(query.isError && !query.data);
  const metricValue = (value: number | string) =>
    unavailable ? "—" : typeof value === "number" ? formatNumber(value) : value;

  const columns: DataTableColumn<BatchSummary>[] = [
    {
      key: "batch",
      header: "批次",
      width: "26%",
      cell: (row) => (
        <div className="min-w-0">
          <a
            className="block truncate font-semibold text-ink hover:text-accent hover:underline"
            href={batchHref(row.batch_id)}
            title={row.name}
          >
            {row.name}
          </a>
          <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-3">
            {row.batch_id}
          </span>
        </div>
      ),
    },
    {
      key: "market",
      header: "市场",
      width: "10%",
      cell: (row) => (
        <div>
          <p className="text-sm">{row.country || row.market || "-"}</p>
          <p className="mt-0.5 text-xs text-ink-3">{row.language || "未设置语言"}</p>
        </div>
      ),
    },
    {
      key: "sites",
      header: "站点",
      width: "16%",
      cell: (row) => {
        const { ready, needs_onboarding, building, invalid, duplicate, sites } =
          row.counts;
        return (
          <div>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-sm font-medium tabular">{sites}</span>
              <span className="text-xs text-ink-3">可采 {ready}</span>
            </div>
            <div className="mt-1.5">
              <ReadinessBar
                ready={ready}
                needs={needs_onboarding}
                building={building}
                invalid={invalid}
                duplicate={duplicate}
              />
            </div>
            <p className="mt-1 text-[11px] text-ink-3">
              待接入 {needs_onboarding + building} · 无效／重复 {invalid + duplicate}
            </p>
          </div>
        );
      },
    },
    {
      key: "tasks",
      header: "任务",
      width: "17%",
      cell: (row) => {
        const { tasks, running, finished, queued, failed, partial_tasks } = row.counts;
        if (!tasks) return <span className="text-xs text-ink-3">未开始</span>;
        return (
          <div>
            <p className="text-sm">
              运行 <span className="font-medium tabular">{running}</span> · 完成{" "}
              <span className="font-medium tabular">{finished}</span>
            </p>
            <p className="mt-0.5 text-xs text-ink-3">
              排队 {queued} · 失败／部分 {failed + partial_tasks}
            </p>
          </div>
        );
      },
    },
    {
      key: "status",
      header: "状态",
      width: "12%",
      cell: (row) => (
        <div>
          <BatchStatusBadge status={row.status} />
          {row.counts.startable > 0 ? (
            <p className="mt-1 text-xs text-ink-3">可启动 {row.counts.startable}</p>
          ) : null}
        </div>
      ),
    },
    {
      key: "updated",
      header: "更新",
      width: "11%",
      align: "right",
      cell: (row) => (
        <span className="text-xs whitespace-nowrap text-ink-3">
          {formatTime(row.updated_at)}
        </span>
      ),
    },
    {
      key: "action",
      header: "",
      width: "92px",
      align: "right",
      cell: (row) => (
        <a
          className="inline-flex h-8 items-center gap-1 whitespace-nowrap rounded-control border border-line-strong bg-surface px-2.5 text-xs font-medium text-ink hover:bg-surface-muted"
          href={batchHref(row.batch_id)}
        >
          查看
          <ArrowUpRight size={13} aria-hidden="true" />
        </a>
      ),
    },
  ];

  const emptyState = (
    <EmptyState
      title={hasFilters ? "没有符合条件的批次" : "还没有批次"}
      description={
        hasFilters
          ? "换一个筛选条件，或重置后查看全部批次。"
          : "从一批站点开始：导入站点、匹配规则包，再启动可采站点。"
      }
      action={
        hasFilters ? (
          <Button onClick={resetFilters}>重置筛选</Button>
        ) : (
          <button
            className="inline-flex items-center gap-1 text-sm font-medium text-accent hover:text-accent-hover hover:underline"
            type="button"
            onClick={openNewBatch}
          >
            新建批次
            <ArrowUpRight size={14} aria-hidden="true" />
          </button>
        )
      }
    />
  );

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="工作台 / 批次"
        title="采集批次"
        description="按项目组织站点：先导入并匹配规则包，再启动可采站点。未接入站点保留在批次中，不计为失败。"
        actions={
          <Button variant="primary" onClick={openNewBatch}>
            <Plus size={15} aria-hidden="true" />
            新建批次
          </Button>
        }
      />

      {notice ? (
        <div
          className={
            notice.tone === "success"
              ? "flex items-start justify-between gap-4 rounded-panel border border-success/25 bg-success-soft px-4 py-3"
              : "flex items-start justify-between gap-4 rounded-panel border border-warning/25 bg-warning-soft px-4 py-3"
          }
          role="status"
        >
          <p
            className={
              notice.tone === "success"
                ? "text-sm text-success"
                : "text-sm text-warning"
            }
          >
            {notice.text}
          </p>
          <button
            type="button"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface/60 hover:text-ink"
            aria-label="关闭提示"
            onClick={() => setNotice(null)}
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>
      ) : null}

      <MetricStrip
        items={[
          {
            label: "批次",
            value: metricValue(summary.total),
            hint: loading ? "正在读取" : "当前筛选",
          },
          {
            label: "运行中",
            value: metricValue(summary.running),
            hint: "至少一个任务在跑",
          },
          {
            label: "需关注",
            value: metricValue(summary.attention),
            hint: "部分就绪／部分完成",
          },
          {
            label: "可采 / 站点",
            value: unavailable
              ? "—"
              : `${formatNumber(summary.ready)} / ${formatNumber(summary.sites)}`,
            hint:
              summary.needs > 0
                ? `待接入 ${formatNumber(summary.needs)}`
                : "当前列表站点",
          },
        ]}
      />

      <section
        className="rounded-panel border border-line bg-surface p-4"
        aria-label="批次筛选"
      >
        <div className="flex flex-wrap items-end gap-3">
          <FilterField label="搜索">
            <div className="relative w-64">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3"
                size={15}
                aria-hidden="true"
              />
              <Input
                className="pl-8"
                value={queryDraft}
                placeholder="批次名或 ID"
                onChange={(event) => setQueryDraft(event.target.value)}
                onBlur={() => commitText("q", queryDraft.trim())}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    commitText("q", queryDraft.trim());
                  }
                }}
              />
            </div>
          </FilterField>

          <FilterField label="状态">
            <Select
              className="w-40"
              value={status}
              onChange={(event) => updateParam("status", event.target.value)}
            >
              {STATUS_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </FilterField>

          <FilterField label="国家／市场">
            <Input
              className="w-28"
              value={countryDraft}
              placeholder="如 FR"
              onChange={(event) => setCountryDraft(event.target.value)}
              onBlur={() => commitText("country", countryDraft.trim())}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  commitText("country", countryDraft.trim());
                }
              }}
            />
          </FilterField>

          <FilterField label="品类">
            <Input
              className="w-36"
              value={categoryDraft}
              placeholder="如 纺织"
              onChange={(event) => setCategoryDraft(event.target.value)}
              onBlur={() => commitText("category", categoryDraft.trim())}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  commitText("category", categoryDraft.trim());
                }
              }}
            />
          </FilterField>

          <div className="flex h-9 items-center gap-2">
            <Checkbox
              id="include-archived"
              checked={includeArchived}
              onChange={(event) =>
                updateParam("archived", event.target.checked ? "1" : "")
              }
            />
            <label className="text-sm text-ink-2" htmlFor="include-archived">
              包含归档
            </label>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <Button onClick={resetFilters} disabled={!hasFilters && !queryParam}>
              <RotateCcw size={14} aria-hidden="true" />
              重置
            </Button>
          </div>
        </div>
      </section>

      {query.isError ? (
        <ErrorNotice
          title="读取批次失败"
          message={errorText}
          onRetry={() => void query.refetch()}
          compact={Boolean(query.data)}
        />
      ) : null}

      {showTable ? (
        <section className="overflow-hidden rounded-panel border border-line bg-surface">
          <div className="flex items-center justify-between gap-4 border-b border-line px-6 py-4">
            <div>
              <h2 className="text-[17px] leading-6 font-semibold text-ink">批次列表</h2>
              <p className="mt-0.5 text-xs text-ink-3" role="status">
                {loading
                  ? "正在读取批次…"
                  : `共 ${formatNumber(total)} 个批次，显示 ${formatNumber(
                      visibleItems.length,
                    )} 个${query.isFetching ? " · 更新中…" : ""}`}
              </p>
            </div>
            <Button
              size="sm"
              onClick={() => void query.refetch()}
              disabled={query.isFetching}
            >
              <RefreshCw
                size={14}
                className={query.isFetching ? "animate-spin" : undefined}
                aria-hidden="true"
              />
              刷新
            </Button>
          </div>

          <DataTable
            caption="采集批次列表"
            columns={columns}
            rows={visibleItems}
            rowKey={(row) => row.batch_id}
            loading={loading}
            empty={emptyState}
          />
        </section>
      ) : null}

      {isNewOpen ? (
        <NewBatchDialog
          open
          onOpenChange={(next) => (next ? openNewBatch() : closeNewBatch())}
          onSaved={(value) => setNotice(value)}
        />
      ) : null}
    </div>
  );
}
