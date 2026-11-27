import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Ban,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  Eye,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
} from "lucide-react";
import {
  archiveTask,
  cancelTask,
  getTasks,
  pauseTask,
  restoreTask,
  resumeTask,
  startTask,
  taskExportUrl,
  type TaskSummary,
} from "../../lib/api";
import {
  coverageLabel,
  formatNumber,
  formatTime,
  outcomeLabel,
  taskStateLabel,
  taskStateTone,
} from "../../lib/format";
import { cn } from "../../lib/cn";
import { rememberListReturn, useListReturnRestore } from "../../lib/listReturn";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Checkbox, Input, Select } from "../../components/ui/Input";
import { DataTable, type DataTableColumn } from "../../components/ui/DataTable";
import { TableDisplayOptions } from "../../components/ui/TableDisplayOptions";
import {
  densityViewOptions,
  TableViewToggle,
} from "../../components/ui/TableViewToggle";
import {
  useTablePreferences,
  type TableSort,
} from "../../components/ui/tablePreferences";
import { EmptyState } from "../../components/ui/EmptyState";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { MetricStrip } from "../../components/ui/MetricStrip";
import { PageHeader } from "../../components/ui/PageHeader";
import { RowActionsMenu, type RowActionItem } from "../../components/ui/DropdownMenu";
import { RowControlButton } from "../../components/ui/RowControlButton";
import { ConfirmBatchActionDialog } from "../batches/ConfirmBatchActionDialog";
import { taskIsActive } from "../sites/site";
import { taskPrimaryControl } from "../../lib/taskControl";
import {
  TASK_STATE_OPTIONS,
  TASK_TYPE_OPTIONS,
  summarizeTasks,
  taskMatchesQuery,
  taskNeedsAttention,
  taskTypeLabel,
  tasksNeedLiveRefresh,
} from "./task";

const PAGE_SIZE = 30;

function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-xs font-medium text-ink-3">{label}</span>
      {children}
    </label>
  );
}

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const textarea = document.createElement("textarea");
  textarea.value = value;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) throw new Error("浏览器拒绝了复制操作");
}

export function TasksPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const listRef = useRef<HTMLDivElement>(null);

  const state = searchParams.get("state") ?? "";
  const taskType = searchParams.get("type") ?? "";
  const siteKey = searchParams.get("site") ?? "";
  const includeArchived = searchParams.get("archived") === "1";
  const queryParam = searchParams.get("q") ?? "";
  const offset = Math.max(0, Number(searchParams.get("offset") ?? 0) || 0);
  const sortKey = searchParams.get("sort") ?? "";
  const sortOrder: "asc" | "desc" =
    searchParams.get("order") === "asc" ? "asc" : "desc";
  const tableSort: TableSort = sortKey ? { key: sortKey, direction: sortOrder } : null;

  const [queryDraft, setQueryDraft] = useState(queryParam);
  const resetWidthsRef = useRef<(() => void) | null>(null);
  const [widthsCustomized, setWidthsCustomized] = useState(false);
  const [siteDraft, setSiteDraft] = useState(siteKey);
  const [busy, setBusy] = useState("");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [confirmCancel, setConfirmCancel] = useState<TaskSummary | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState("");

  // URL is the source of truth; keep the editable drafts in sync on back/forward
  // and reset.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setQueryDraft(queryParam), [queryParam]);
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setSiteDraft(siteKey), [siteKey]);

  function updateParams(updates: Record<string, string>, resetOffset = true) {
    const next = new URLSearchParams(searchParams);
    for (const [key, value] of Object.entries(updates)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    if (resetOffset) next.delete("offset");
    setSearchParams(next, { replace: true });
  }

  function commitText(key: string, value: string) {
    if ((searchParams.get(key) ?? "") !== value) updateParams({ [key]: value });
  }

  function resetFilters() {
    setSearchParams(new URLSearchParams(), { replace: true });
    setQueryDraft("");
    setSiteDraft("");
  }

  const query = useQuery({
    queryKey: [
      "tasks",
      state,
      taskType,
      siteKey,
      includeArchived,
      offset,
      sortKey,
      sortOrder,
    ],
    queryFn: ({ signal }) =>
      getTasks(
        {
          state: state || undefined,
          taskType: taskType || undefined,
          siteKey: siteKey || undefined,
          includeArchived,
          limit: PAGE_SIZE,
          offset,
          sort: sortKey || undefined,
          order: sortKey ? sortOrder : undefined,
        },
        signal,
      ),
    placeholderData: keepPreviousData,
    refetchInterval: (current) =>
      tasksNeedLiveRefresh(current.state.data?.items ?? []) ? 3000 : false,
  });

  const items = useMemo(() => query.data?.items ?? [], [query.data]);
  const liveRefresh = tasksNeedLiveRefresh(items);
  const total = query.data?.total ?? 0;
  const summary = summarizeTasks(items, total);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const page = Math.floor(offset / PAGE_SIZE) + 1;

  const visibleItems = useMemo(
    () => items.filter((task) => taskMatchesQuery(task, queryDraft)),
    [items, queryDraft],
  );

  useListReturnRestore({
    ready: Boolean(query.data),
    locationKey: location.key,
    navigationState: location.state,
    containerRef: listRef,
  });

  const hasFilters = Boolean(
    state || taskType || siteKey || queryParam || includeArchived,
  );

  async function refresh() {
    setRefreshing(true);
    try {
      await queryClient.invalidateQueries({ queryKey: ["tasks"] });
    } finally {
      setRefreshing(false);
    }
  }

  async function runAction(
    task: TaskSummary,
    kind: "start" | "pause" | "resume" | "archive" | "restore",
  ) {
    setBusy(`${kind}-${task.task_id}`);
    setError("");
    try {
      if (kind === "start") await startTask(task.task_id);
      else if (kind === "pause") await pauseTask(task.task_id);
      else if (kind === "resume") await resumeTask(task.task_id);
      else if (kind === "archive") await archiveTask(task.task_id);
      else await restoreTask(task.task_id);
      setNotice(
        kind === "start"
          ? `启动请求已受理：${task.task_id}`
          : kind === "pause"
            ? `暂停请求已受理：${task.task_id}`
            : kind === "resume"
              ? `继续请求已受理：${task.task_id}`
              : kind === "archive"
                ? `任务已归档：${task.task_id}`
                : `任务已恢复：${task.task_id}`,
      );
      refresh();
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  async function confirmCancelTask() {
    if (!confirmCancel) return;
    setConfirmBusy(true);
    setConfirmError("");
    try {
      await cancelTask(confirmCancel.task_id);
      setNotice(`取消请求已受理：${confirmCancel.task_id}`);
      setConfirmCancel(null);
      refresh();
    } catch (exc) {
      setConfirmError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setConfirmBusy(false);
    }
  }

  async function copyId(task: TaskSummary) {
    try {
      await copyText(task.task_id);
      setNotice(`任务 ID 已复制：${task.task_id}`);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    }
  }

  function download(task: TaskSummary) {
    const link = document.createElement("a");
    link.href = taskExportUrl(task.task_id, taskIsActive(task));
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  function openTask(task: TaskSummary, event?: MouseEvent<HTMLAnchorElement>) {
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
    navigate(`/tasks/${encodeURIComponent(task.task_id)}`, {
      state: rememberListReturn(location.key, {
        href: `${location.pathname}${location.search}`,
        label: "全部任务",
        scrollTop: window.scrollY,
        focusKey: task.task_id,
      }),
    });
  }

  function taskActions(task: TaskSummary): RowActionItem[][] {
    const active = taskIsActive(task);
    const groups: RowActionItem[][] = [
      [
        {
          key: "view",
          label: "查看任务详情",
          icon: <Eye size={14} />,
          onSelect: () => openTask(task),
        },
        {
          key: "copy",
          label: "复制任务 ID",
          icon: <Copy size={14} />,
          onSelect: () => void copyId(task),
        },
      ],
    ];

    const control: RowActionItem[] = [];
    if (task.state === "QUEUED" || task.state === "RUNNING") {
      control.push({
        key: "pause",
        label: "暂停任务",
        icon: <Pause size={14} />,
        onSelect: () => void runAction(task, "pause"),
      });
    }
    if (task.state === "PAUSED") {
      control.push({
        key: "resume",
        label: "继续任务",
        icon: <Play size={14} />,
        onSelect: () => void runAction(task, "resume"),
      });
    }
    if (["DRAFT", "QUEUED", "RUNNING", "PAUSING", "PAUSED"].includes(task.state)) {
      control.push({
        key: "cancel",
        label: "取消任务",
        icon: <Ban size={14} />,
        danger: true,
        onSelect: () => {
          setConfirmError("");
          setConfirmCancel(task);
        },
      });
    }
    if (control.length) groups.push(control);

    groups.push([
      {
        key: "export",
        label: active ? "导出部分结果" : "导出 ZIP",
        icon: <Download size={14} />,
        onSelect: () => download(task),
      },
      {
        key: "archive",
        label: task.archived_at ? "恢复任务" : "归档任务",
        icon: task.archived_at ? <RotateCcw size={14} /> : <Archive size={14} />,
        onSelect: () => void runAction(task, task.archived_at ? "restore" : "archive"),
        disabled: active,
        hint: active ? "运行中不能归档" : undefined,
      },
    ]);

    return groups;
  }

  const columns: DataTableColumn<TaskSummary>[] = [
    {
      key: "task",
      header: "任务",
      label: "任务",
      sortable: true,
      sortValue: (task) => task.site_key || task.plan_id,
      width: 260,
      minWidth: 180,
      maxWidth: 720,
      cell: (task, { compact }) => (
        <div className="min-w-0">
          <Link
            className="block truncate font-semibold text-ink hover:text-accent hover:underline"
            to={`/tasks/${encodeURIComponent(task.task_id)}`}
            onClick={(event) => openTask(task, event)}
            data-return-focus={task.task_id}
            title={
              compact ? `${task.site_key || task.plan_id} · ${task.task_id}` : undefined
            }
          >
            {task.site_key || task.plan_id}
          </Link>
          {compact ? null : (
            <>
              <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-3">
                {task.task_id}
              </span>
              <div className="mt-1 flex flex-wrap gap-x-2 gap-y-0.5 text-[11px] text-ink-3">
                <span>{taskTypeLabel(task.task_type)}</span>
              </div>
            </>
          )}
        </div>
      ),
    },
    {
      key: "state",
      header: "状态／结果",
      label: "状态／结果",
      hideable: true,
      sortable: true,
      sortValue: (task) => task.state,
      width: 140,
      minWidth: 100,
      maxWidth: 240,
      cell: (task, { compact }) => (
        <div className={compact ? "flex flex-wrap items-center gap-1" : "space-y-1"}>
          <div className="flex flex-wrap items-center gap-1">
            <Badge tone={taskStateTone(task.state)} dot={false}>
              {taskStateLabel(task.state)}
            </Badge>
            {task.archived_at ? (
              <Badge tone="neutral" dot={false}>
                已归档
              </Badge>
            ) : null}
          </div>
          {compact ? (
            <span className="text-xs text-ink-3">
              {task.outcome ? outcomeLabel(task.outcome) : "未结束"}
              {taskNeedsAttention(task) ? " · 需关注" : ""}
            </span>
          ) : (
            <p className="text-xs text-ink-3">
              {task.outcome ? outcomeLabel(task.outcome) : "未结束"}
              {taskNeedsAttention(task) ? " · 需关注" : ""}
            </p>
          )}
        </div>
      ),
    },
    {
      key: "results",
      header: "结果",
      label: "结果",
      hideable: true,
      sortable: true,
      sortValue: (task) =>
        task.task_type === "discovery"
          ? (task.counts.discovered_urls ?? 0)
          : (task.counts.valid_products ?? 0),
      width: 150,
      minWidth: 110,
      maxWidth: 260,
      cell: (task, { compact }) => {
        const discovery = task.task_type === "discovery";
        const label = discovery ? "发现 / 失败 / 排除" : "有效 / 失败 / 排除";
        const primary = discovery
          ? (task.counts.discovered_urls ?? 0)
          : (task.counts.valid_products ?? 0);
        if (compact) {
          return (
            <span
              className="text-sm tabular whitespace-nowrap"
              title={label}
              aria-label={`${label}：${formatNumber(primary)} / ${formatNumber(task.counts.failed_products ?? 0)} / ${formatNumber(task.counts.excluded_products ?? 0)}`}
            >
              <span className="font-medium text-ink">{formatNumber(primary)}</span>
              <span className="text-ink-3">
                {" "}
                / {formatNumber(task.counts.failed_products ?? 0)} /{" "}
                {formatNumber(task.counts.excluded_products ?? 0)}
              </span>
            </span>
          );
        }
        return (
          <div>
            <p className="text-[11px] text-ink-3">{label}</p>
            <p className="text-sm tabular">
              <span className="font-medium text-ink">{formatNumber(primary)}</span>
              <span className="text-ink-3">
                {" "}
                / {formatNumber(task.counts.failed_products ?? 0)} /{" "}
                {formatNumber(task.counts.excluded_products ?? 0)}
              </span>
            </p>
          </div>
        );
      },
    },
    {
      key: "coverage",
      header: "覆盖",
      label: "覆盖",
      hideable: true,
      sortable: true,
      sortValue: (task) => task.coverage?.status ?? "",
      width: 120,
      minWidth: 90,
      maxWidth: 220,
      cell: (task, { compact }) => {
        const coverage = coverageLabel(task.coverage?.status);
        const detail =
          task.coverage?.status !== "UNKNOWN" && task.coverage
            ? `${task.coverage.covered ?? "—"} / ${task.coverage.denominator ?? "—"}`
            : null;
        if (compact) {
          return (
            <span className="text-sm whitespace-nowrap">
              {coverage}
              {detail ? (
                <span className="text-xs text-ink-3 tabular"> {detail}</span>
              ) : null}
            </span>
          );
        }
        return (
          <div>
            <p className="text-sm">{coverage}</p>
            {detail ? (
              <p className="mt-0.5 text-xs text-ink-3 tabular">{detail}</p>
            ) : null}
          </div>
        );
      },
    },
    {
      key: "quality",
      header: "质量异常",
      label: "质量异常",
      hideable: true,
      sortable: true,
      sortValue: (task) => task.quality_exceptions?.length ?? 0,
      width: 100,
      minWidth: 70,
      maxWidth: 160,
      align: "right",
      cell: (task) => (
        <span
          className={cn(
            "text-sm tabular",
            (task.quality_exceptions?.length ?? 0) > 0 && "font-medium text-warning",
          )}
        >
          {formatNumber(task.quality_exceptions?.length ?? 0)}
        </span>
      ),
    },
    {
      key: "updated",
      header: "更新",
      label: "更新",
      hideable: true,
      sortable: true,
      sortValue: (task) => task.updated_at,
      width: 100,
      minWidth: 80,
      maxWidth: 150,
      align: "right",
      cell: (task) => {
        const stamp = formatTime(task.updated_at);
        return (
          <span className="text-xs whitespace-nowrap text-ink-3" title={stamp}>
            {stamp === "-" ? "-" : stamp.slice(5)}
          </span>
        );
      },
    },
    {
      key: "actions",
      label: "操作",
      header: <span className="sr-only">操作</span>,
      width: 76,
      resizable: false,
      sticky: "right",
      hideable: false,
      align: "right",
      headerClassName: "px-2",
      cellClassName: "px-2",
      skeleton: false,
      cell: (task) => {
        const control = taskPrimaryControl(task.state);
        const rowBusy = busy.includes(task.task_id);
        return (
          <div className="flex items-center justify-end gap-0.5">
            {control ? (
              <RowControlButton
                label={
                  control === "start"
                    ? `启动任务 ${task.task_id}`
                    : control === "pause"
                      ? `暂停任务 ${task.task_id}`
                      : `继续任务 ${task.task_id}`
                }
                icon={
                  control === "pause" ? (
                    <Pause size={15} aria-hidden="true" />
                  ) : (
                    <Play size={15} aria-hidden="true" />
                  )
                }
                accent={control === "start"}
                busy={rowBusy}
                onClick={() => void runAction(task, control)}
              />
            ) : null}
            <RowActionsMenu
              label={`打开任务「${task.task_id}」的操作菜单`}
              groups={taskActions(task)}
              busy={rowBusy}
            />
          </div>
        );
      },
    },
  ];

  const table = useTablePreferences({
    tableKey: "tasks",
    columns,
    defaultDensity: "default",
    sort: tableSort,
    onSortChange: (next) =>
      updateParams({ sort: next?.key ?? "", order: next?.direction ?? "" }),
  });

  return (
    <div ref={listRef} tabIndex={-1} className="space-y-6">
      <PageHeader
        eyebrow="任务控制台"
        title="全部任务"
        description="按站点查看每一次采集运行；任务结果、反馈和导出都属于单个任务。"
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {liveRefresh ? (
              <span className="text-xs text-ink-3" role="status">
                活动任务每 3 秒自动刷新
              </span>
            ) : null}
            <Button onClick={() => void refresh()} disabled={refreshing}>
              <RefreshCw
                className={refreshing ? "animate-spin" : undefined}
                size={14}
                aria-hidden="true"
              />
              刷新
            </Button>
          </div>
        }
      />

      {notice ? (
        <div
          className="flex items-start justify-between gap-4 rounded-panel border border-success/25 bg-success-soft px-4 py-3"
          role="status"
        >
          <p className="text-sm text-success">{notice}</p>
          <button
            type="button"
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface/60 hover:text-ink"
            aria-label="关闭提示"
            onClick={() => setNotice("")}
          >
            ×
          </button>
        </div>
      ) : null}

      {error ? <ErrorNotice title="操作失败" message={error} compact /> : null}

      <MetricStrip
        items={[
          {
            label: "任务",
            value: query.isPending ? "—" : formatNumber(summary.total),
            hint: "当前筛选",
          },
          {
            label: "运行中",
            value: query.isPending ? "—" : formatNumber(summary.running),
            hint: "当前页含排队",
          },
          {
            label: "需关注",
            value: query.isPending ? "—" : formatNumber(summary.attention),
            hint: "失败、部分或质量异常",
          },
          {
            label: "已归档",
            value: query.isPending ? "—" : formatNumber(summary.archived),
            hint: "当前页",
          },
        ]}
        label="任务概览"
      />

      <section
        className="rounded-panel border border-line bg-surface p-4"
        aria-label="任务筛选"
      >
        <div className="flex flex-wrap items-end gap-3">
          <FilterField label="状态">
            <Select
              className="w-32"
              value={state}
              onChange={(event) => updateParams({ state: event.target.value })}
            >
              {TASK_STATE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </FilterField>

          <FilterField label="类型">
            <Select
              className="w-32"
              value={taskType}
              onChange={(event) => updateParams({ type: event.target.value })}
            >
              {TASK_TYPE_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </FilterField>

          <FilterField label="站点 ID">
            <Input
              className="w-40"
              value={siteDraft}
              placeholder="example.fr"
              onChange={(event) => setSiteDraft(event.target.value)}
              onBlur={() => commitText("site", siteDraft.trim())}
              onKeyDown={(event) => {
                if (event.key === "Enter") commitText("site", siteDraft.trim());
              }}
            />
          </FilterField>

          <FilterField label="搜索当前页">
            <div className="relative w-48">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3"
                size={15}
                aria-hidden="true"
              />
              <Input
                className="pl-8"
                value={queryDraft}
                placeholder="任务或站点"
                onChange={(event) => setQueryDraft(event.target.value)}
                onBlur={() => commitText("q", queryDraft.trim())}
                onKeyDown={(event) => {
                  if (event.key === "Enter") commitText("q", queryDraft.trim());
                }}
              />
            </div>
          </FilterField>

          <div className="flex h-9 items-center gap-2">
            <Checkbox
              id="tasks-include-archived"
              checked={includeArchived}
              onChange={(event) =>
                updateParams({ archived: event.target.checked ? "1" : "" })
              }
            />
            <label className="text-sm text-ink-2" htmlFor="tasks-include-archived">
              包含归档
            </label>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <Button onClick={resetFilters} disabled={!hasFilters}>
              <RotateCcw size={14} aria-hidden="true" />
              重置
            </Button>
          </div>
        </div>
      </section>

      {query.isError ? (
        <ErrorNotice
          title="读取任务失败"
          message={
            query.error instanceof Error ? query.error.message : "无法读取任务列表。"
          }
          onRetry={refresh}
          compact={Boolean(query.data)}
        />
      ) : null}

      <section
        aria-label="任务列表"
        className="overflow-hidden rounded-panel border border-line bg-surface"
      >
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-6 py-4">
          <div>
            <h2 className="text-[17px] leading-6 font-semibold text-ink">任务列表</h2>
            <p className="mt-0.5 text-xs text-ink-3" role="status">
              {query.isPending
                ? "正在读取任务…"
                : `共 ${formatNumber(total)} 个任务，当前页显示 ${formatNumber(
                    visibleItems.length,
                  )} 个${query.isFetching ? " · 更新中…" : ""}`}
            </p>
          </div>
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
          caption="全部任务"
          columns={table.visibleColumns}
          rows={visibleItems}
          rowKey={(task) => task.task_id}
          density={table.density}
          resizeKey="tasks"
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
              title={hasFilters ? "没有符合条件的任务" : "还没有任务"}
              description={
                hasFilters
                  ? "换一个筛选条件，或重置后查看全部任务。"
                  : "从任务工作台启动采集后，任务会出现在这里。"
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

        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-6">
          <p className="text-xs text-ink-3">
            {total ? `第 ${page} / ${pageCount} 页` : "没有可翻页的数据"}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button
              size="sm"
              disabled={offset === 0 || query.isFetching}
              onClick={() =>
                updateParams({ offset: String(Math.max(0, offset - PAGE_SIZE)) }, false)
              }
            >
              <ChevronLeft size={13} aria-hidden="true" />
              上一页
            </Button>
            <Button
              size="sm"
              disabled={page >= pageCount || query.isFetching}
              onClick={() =>
                updateParams({ offset: String(offset + PAGE_SIZE) }, false)
              }
            >
              下一页
              <ChevronRight size={13} aria-hidden="true" />
            </Button>
          </div>
        </div>
      </section>

      <ConfirmBatchActionDialog
        open={Boolean(confirmCancel)}
        title="取消这个任务？"
        description={
          confirmCancel
            ? `任务 ${confirmCancel.task_id} 会停止；已经产生的部分结果保留。`
            : ""
        }
        consequence="取消是任务级操作，不会删除任务定义或已有结果；可在任务工作台重新启动。"
        confirmLabel="确认取消任务"
        tone="danger"
        busy={confirmBusy}
        error={confirmError}
        onOpenChange={(next) => {
          if (!next) setConfirmCancel(null);
        }}
        onConfirm={() => void confirmCancelTask()}
      />
    </div>
  );
}
