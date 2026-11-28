import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Layers, ListPlus, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  getBatch,
  getBatches,
  type BatchDraftRequest,
  type WorkbenchBatchImportCounts,
  type WorkbenchBatchImportSkipped,
  type WorkbenchNode,
  type WorkbenchPendingBatch,
  type WorkbenchPendingSite,
  type WorkbenchPendingTargets,
} from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input, Select, Textarea } from "../../components/ui/Input";
import { cn } from "../../lib/cn";

function nodePaths(nodes: WorkbenchNode[]): Map<string, string> {
  const byId = new Map(nodes.map((node) => [node.node_id, node]));
  const paths = new Map<string, string>();
  function resolve(node: WorkbenchNode, seen: Set<string>): string {
    const cached = paths.get(node.node_id);
    if (cached) return cached;
    if (seen.has(node.node_id)) return node.name;
    seen.add(node.node_id);
    const parent = node.parent_id ? byId.get(node.parent_id) : null;
    const path = parent ? `${resolve(parent, seen)} / ${node.name}` : node.name;
    paths.set(node.node_id, path);
    return path;
  }
  for (const node of nodes) {
    if (node.node_type === "group") resolve(node, new Set());
  }
  return paths;
}

function groupOptions(nodes: WorkbenchNode[]) {
  const paths = nodePaths(nodes);
  return nodes
    .filter((node) => node.node_type === "group")
    .sort((left, right) =>
      (paths.get(left.node_id) ?? left.name).localeCompare(
        paths.get(right.node_id) ?? right.name,
        "zh-CN",
      ),
    )
    .map((group) => ({
      node_id: group.node_id,
      label: paths.get(group.node_id) ?? group.name,
    }));
}

interface DialogShellProps {
  open: boolean;
  busy: boolean;
  title: string;
  description: string;
  icon: "import" | "new" | "pending";
  wide?: boolean;
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}

function DialogShell({
  open,
  busy,
  title,
  description,
  icon,
  wide = false,
  onOpenChange,
  children,
}: DialogShellProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className={cn(
            "animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay",
            wide
              ? "w-[min(760px,calc(100vw-24px))]"
              : "w-[min(620px,calc(100vw-24px))]",
          )}
          tabIndex={-1}
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            const content = event.currentTarget as HTMLElement;
            const target = content.querySelector<HTMLElement>(
              "input:not([type='hidden']), select, textarea",
            );
            (target ?? content).focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                {icon === "new" ? <Layers size={17} /> : <ListPlus size={17} />}
              </span>
              <div>
                <Dialog.Title className="text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                  {title}
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  {description}
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭"
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

interface ImportBatchDialogProps {
  open: boolean;
  nodes: WorkbenchNode[];
  initialParentId?: string | null;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: { batch_id: string; parent_id: string | null }) => void;
}

export function WorkbenchImportBatchDialog({
  open,
  nodes,
  initialParentId = null,
  busy = false,
  error = "",
  onOpenChange,
  onSubmit,
}: ImportBatchDialogProps) {
  const [batchId, setBatchId] = useState("");
  const [parentId, setParentId] = useState(initialParentId ?? "");
  const groups = useMemo(() => groupOptions(nodes), [nodes]);
  const batchesQuery = useQuery({
    queryKey: ["workbench-batches"],
    queryFn: ({ signal }) => getBatches({ limit: 200 }, signal),
    enabled: open,
  });
  const batches = batchesQuery.data?.items ?? [];
  const activeBatchId =
    batchId || batches.find((batch) => batch.status !== "ARCHIVED")?.batch_id || "";
  const selectedBatch = batches.find((batch) => batch.batch_id === activeBatchId);
  const detailQuery = useQuery({
    queryKey: ["workbench-batch-detail", activeBatchId],
    queryFn: ({ signal }) => getBatch(activeBatchId, signal),
    enabled: open && Boolean(activeBatchId),
  });
  const siteKeys = new Set(
    (detailQuery.data?.sites ?? []).map((site) => site.site_key),
  );
  const inTree = nodes.filter(
    (node) =>
      node.node_type === "task" &&
      node.definition?.site_key &&
      siteKeys.has(node.definition.site_key),
  ).length;

  return (
    <DialogShell
      open={open}
      busy={busy}
      title="添加已有批次"
      description="批次只批量添加任务定义；已在树中的站点和未匹配规则的站点会跳过。"
      icon="import"
      onOpenChange={onOpenChange}
    >
      <div className="space-y-4 px-4 py-5 sm:px-6">
        {error ? <ErrorNotice title="未能添加批次" message={error} compact /> : null}
        {batchesQuery.isError ? (
          <ErrorNotice
            title="读取批次失败"
            message={
              batchesQuery.error instanceof Error
                ? batchesQuery.error.message
                : "暂时无法读取批次列表。"
            }
            onRetry={() => void batchesQuery.refetch()}
            compact
          />
        ) : null}
        {batchesQuery.isPending ? (
          <p className="text-xs text-ink-3" role="status">
            正在读取批次…
          </p>
        ) : batches.length === 0 ? (
          <div className="rounded-panel border border-dashed border-line-strong px-3 py-4 text-xs text-ink-3">
            还没有可添加的批次记录。先用任务工作台的“新建批次”创建并选择目标目录。
          </div>
        ) : (
          <>
            <div>
              <label
                className="mb-1 block text-xs font-medium text-ink-3"
                htmlFor="workbench-import-batch"
              >
                批次
              </label>
              <Select
                id="workbench-import-batch"
                value={activeBatchId}
                onChange={(event) => setBatchId(event.target.value)}
              >
                {batches.map((batch) => (
                  <option key={batch.batch_id} value={batch.batch_id}>
                    {batch.name} · {batch.counts.sites} 站
                    {batch.archived_at ? " · 已归档" : ""}
                  </option>
                ))}
              </Select>
              {selectedBatch ? (
                <p className="mt-1.5 text-[11px] leading-5 text-ink-3">
                  {selectedBatch.counts.sites} 个站点，已在任务树中 {inTree} 个；
                  {detailQuery.isPending
                    ? "正在核对站点规则…"
                    : "只添加有可用规则的其余站点。"}
                </p>
              ) : null}
            </div>
            <div>
              <label
                className="mb-1 block text-xs font-medium text-ink-3"
                htmlFor="workbench-import-parent"
              >
                目标目录
              </label>
              <Select
                id="workbench-import-parent"
                value={parentId}
                onChange={(event) => setParentId(event.target.value)}
              >
                <option value="">根目录</option>
                {groups.map((group) => (
                  <option key={group.node_id} value={group.node_id}>
                    {group.label}
                  </option>
                ))}
              </Select>
            </div>
          </>
        )}
      </div>
      <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-6">
        <Button type="button" onClick={() => onOpenChange(false)} disabled={busy}>
          取消
        </Button>
        <Button
          type="button"
          variant="primary"
          onClick={() =>
            onSubmit({ batch_id: activeBatchId, parent_id: parentId || null })
          }
          disabled={busy || !activeBatchId}
        >
          {busy ? "添加中…" : "添加任务"}
        </Button>
      </footer>
    </DialogShell>
  );
}

export interface WorkbenchBatchAddResult {
  batchId: string;
  batchName: string;
  parentId: string | null;
  added: number;
  counts: WorkbenchBatchImportCounts;
  skipped: WorkbenchBatchImportSkipped[];
  error?: string;
}

interface NewBatchDialogProps {
  open: boolean;
  nodes: WorkbenchNode[];
  initialParentId?: string | null;
  busy?: boolean;
  error?: string;
  result?: WorkbenchBatchAddResult | null;
  onOpenChange: (open: boolean) => void;
  onSubmit: (
    values: BatchDraftRequest & { workbench_parent_id: string | null },
  ) => void;
  onRetry?: () => void;
  onViewPending?: () => void;
  onDone?: () => void;
}

function BatchResultBody({
  result,
  busy,
  onRetry,
  onViewPending,
  onDone,
}: {
  result: WorkbenchBatchAddResult;
  busy: boolean;
  onRetry?: () => void;
  onViewPending?: () => void;
  onDone?: () => void;
}) {
  const pending = result.counts.pending + result.counts.failed;
  const reasons = result.skipped.filter((item) => item.category !== "added");
  return (
    <>
      <div className="space-y-4 px-4 py-5 sm:px-6">
        {result.error ? (
          <ErrorNotice title="批次已创建，但加入未完成" message={result.error} />
        ) : null}
        <p className="text-sm leading-6 text-ink-2">
          批次「{result.batchName}」已创建。已加入 {result.added} 个目标
          {pending ? `，${pending} 个目标待接入或加入失败` : ""}。
        </p>
        <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
          {[
            ["已加入", result.counts.added],
            ["待接入", result.counts.pending],
            ["已在树中", result.counts.existing],
            ["失败", result.counts.failed],
            ["重复", result.counts.duplicate],
            ["无效", result.counts.invalid],
          ].map(([label, value]) => (
            <div
              key={String(label)}
              className="rounded-control border border-line bg-surface-muted px-3 py-2"
            >
              <div className="text-xs text-ink-3">{label}</div>
              <div className="mt-0.5 text-base font-semibold text-ink">{value}</div>
            </div>
          ))}
        </div>
        {reasons.length ? (
          <div className="rounded-control border border-line">
            <div className="border-b border-line px-3 py-2 text-xs font-medium text-ink-3">
              未加入的目标
            </div>
            <ul className="max-h-56 divide-y divide-line overflow-y-auto">
              {reasons.slice(0, 12).map((item) => (
                <li
                  key={`${item.category}-${item.site_key}`}
                  className="flex items-start justify-between gap-3 px-3 py-2 text-sm"
                >
                  <span className="min-w-0 break-all text-ink">
                    {item.domain || item.site_key}
                  </span>
                  <span className="shrink-0 text-right text-xs text-ink-3">
                    {item.reason}
                  </span>
                </li>
              ))}
            </ul>
            {reasons.length > 12 ? (
              <div className="border-t border-line px-3 py-2 text-xs text-ink-3">
                另有 {reasons.length - 12} 个目标，查看待接入可继续处理。
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
      <footer className="flex flex-wrap justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-6">
        {result.error && onRetry ? (
          <Button type="button" onClick={onRetry} disabled={busy}>
            {busy ? "重试中…" : "重试加入"}
          </Button>
        ) : null}
        {pending && onViewPending ? (
          <Button type="button" onClick={onViewPending} disabled={busy}>
            查看待接入
          </Button>
        ) : null}
        <Button type="button" variant="primary" onClick={onDone} disabled={busy}>
          完成
        </Button>
      </footer>
    </>
  );
}

export function WorkbenchNewBatchDialog({
  open,
  nodes,
  initialParentId = null,
  busy = false,
  error = "",
  result = null,
  onOpenChange,
  onSubmit,
  onRetry,
  onViewPending,
  onDone,
}: NewBatchDialogProps) {
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState(initialParentId ?? "");
  const [country, setCountry] = useState("FR");
  const [language, setLanguage] = useState("fr");
  const [market, setMarket] = useState("FR");
  const [category, setCategory] = useState("纺织");
  const [sitesText, setSitesText] = useState("");
  const [localError, setLocalError] = useState("");
  const groups = useMemo(() => groupOptions(nodes), [nodes]);

  if (result) {
    return (
      <DialogShell
        open={open}
        busy={busy}
        title="批次加入结果"
        description="已创建批次并尝试加入任务树；待接入目标可继续构建或重试。"
        icon="pending"
        onOpenChange={onOpenChange}
      >
        <BatchResultBody
          result={result}
          busy={busy}
          onRetry={onRetry}
          onViewPending={onViewPending}
          onDone={onDone}
        />
      </DialogShell>
    );
  }

  function submit() {
    const batchName = name.trim();
    const sites = sitesText
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean);
    if (!batchName) {
      setLocalError("请填写批次名称。");
      return;
    }
    if (!sites.length) {
      setLocalError("请至少填写一个站点 URL。");
      return;
    }
    setLocalError("");
    onSubmit({
      name: batchName,
      collection_mode: "formal",
      country: country.trim() || null,
      language: language.trim() || null,
      market: market.trim() || null,
      category: category.trim() || null,
      sites,
      workbench_parent_id: parentId || null,
    });
  }

  return (
    <DialogShell
      open={open}
      busy={busy}
      title="新建批次"
      description="复用批次导入与规则匹配；创建后把匹配到规则的站点定义加入任务树。"
      icon="new"
      onOpenChange={onOpenChange}
    >
      <div className="space-y-4 px-4 py-5 sm:px-6">
        {error ? <ErrorNotice title="未能创建批次" message={error} compact /> : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label
              className="mb-1 block text-xs font-medium text-ink-3"
              htmlFor="workbench-new-batch-name"
            >
              批次名称 <span className="text-danger">*</span>
            </label>
            <Input
              id="workbench-new-batch-name"
              value={name}
              maxLength={80}
              placeholder="如 202612 法国纺织"
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div>
            <label
              className="mb-1 block text-xs font-medium text-ink-3"
              htmlFor="workbench-new-batch-parent"
            >
              目标目录
            </label>
            <Select
              id="workbench-new-batch-parent"
              value={parentId}
              onChange={(event) => setParentId(event.target.value)}
            >
              <option value="">根目录</option>
              {groups.map((group) => (
                <option key={group.node_id} value={group.node_id}>
                  {group.label}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label
              className="mb-1 block text-xs font-medium text-ink-3"
              htmlFor="workbench-new-batch-market"
            >
              市场
            </label>
            <Input
              id="workbench-new-batch-market"
              value={market}
              maxLength={20}
              onChange={(event) => setMarket(event.target.value)}
            />
          </div>
          <div>
            <label
              className="mb-1 block text-xs font-medium text-ink-3"
              htmlFor="workbench-new-batch-country"
            >
              国家
            </label>
            <Input
              id="workbench-new-batch-country"
              value={country}
              maxLength={20}
              onChange={(event) => setCountry(event.target.value)}
            />
          </div>
          <div>
            <label
              className="mb-1 block text-xs font-medium text-ink-3"
              htmlFor="workbench-new-batch-language"
            >
              语言
            </label>
            <Input
              id="workbench-new-batch-language"
              value={language}
              maxLength={20}
              onChange={(event) => setLanguage(event.target.value)}
            />
          </div>
          <div className="sm:col-span-2">
            <label
              className="mb-1 block text-xs font-medium text-ink-3"
              htmlFor="workbench-new-batch-category"
            >
              品类
            </label>
            <Input
              id="workbench-new-batch-category"
              value={category}
              maxLength={40}
              onChange={(event) => setCategory(event.target.value)}
            />
          </div>
          <div className="sm:col-span-2">
            <label
              className="mb-1 block text-xs font-medium text-ink-3"
              htmlFor="workbench-new-batch-sites"
            >
              站点 URL <span className="text-danger">*</span>
            </label>
            <Textarea
              id="workbench-new-batch-sites"
              value={sitesText}
              rows={6}
              placeholder={"https://www.example-one.fr/\nexample-two.fr"}
              onChange={(event) => setSitesText(event.target.value)}
            />
            <p className="mt-1.5 text-[11px] leading-5 text-ink-3">
              每行一个站点。未匹配规则的站点会在所选目录显示为「待接入」，可从节点启动接入构建。
            </p>
          </div>
        </div>
        {localError ? <p className="text-xs text-danger">{localError}</p> : null}
      </div>
      <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-6">
        <Button type="button" onClick={() => onOpenChange(false)} disabled={busy}>
          取消
        </Button>
        <Button type="button" variant="primary" onClick={submit} disabled={busy}>
          {busy ? "创建中…" : "创建批次并添加"}
        </Button>
      </footer>
    </DialogShell>
  );
}

interface PendingTargetsDialogProps {
  open: boolean;
  data: WorkbenchPendingTargets | null;
  nodes: WorkbenchNode[];
  busy?: string;
  error?: string;
  readOnly?: boolean;
  onOpenChange: (open: boolean) => void;
  onRetry: (batch: WorkbenchPendingBatch, targetId: string | null) => void;
  onBuild: (batch: WorkbenchPendingBatch, site: WorkbenchPendingSite) => void;
  onDismiss: (batch: WorkbenchPendingBatch) => void;
}

function PendingBatchSection({
  batch,
  nodes,
  busy,
  canBuild,
  readOnly,
  onRetry,
  onBuild,
  onDismiss,
}: {
  batch: WorkbenchPendingBatch;
  nodes: WorkbenchNode[];
  busy: string;
  canBuild: boolean;
  readOnly: boolean;
  onRetry: PendingTargetsDialogProps["onRetry"];
  onBuild: PendingTargetsDialogProps["onBuild"];
  onDismiss: PendingTargetsDialogProps["onDismiss"];
}) {
  const groups = useMemo(() => groupOptions(nodes), [nodes]);
  const paths = useMemo(() => nodePaths(nodes), [nodes]);
  const [targetId, setTargetId] = useState(
    batch.target.missing ? "" : (batch.target.node_id ?? ""),
  );
  const retrying = busy === `batch:${batch.batch_id}`;
  const pendingCount =
    batch.counts.needs_onboarding + batch.counts.building + batch.counts.ready;
  const targetLabel = batch.target.missing
    ? "原目录已删除"
    : batch.target.node_id
      ? (paths.get(batch.target.node_id) ?? batch.target.name ?? "目标目录")
      : "根目录";

  return (
    <section className="overflow-hidden rounded-control border border-line">
      <header className="border-b border-line bg-surface-muted px-3 py-3">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-ink">{batch.name}</div>
            <div className="mt-0.5 text-xs text-ink-3">
              {batch.market || "未设市场"} · {targetLabel} · 待处理 {pendingCount}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              onClick={() => onRetry(batch, targetId || null)}
              disabled={
                readOnly ||
                Boolean(busy) ||
                (batch.counts.ready === 0 && !batch.target.missing)
              }
            >
              {retrying ? "加入中…" : "重试加入"}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              onClick={() => onDismiss(batch)}
              disabled={readOnly || Boolean(busy)}
            >
              忽略此批次
            </Button>
          </div>
        </div>
        {batch.target.missing ? (
          <div className="mt-3 space-y-1.5">
            <label
              className="block text-xs text-ink-3"
              htmlFor={`pending-target-${batch.batch_id}`}
            >
              原目标目录已删除，请选择新的目标目录
            </label>
            <Select
              id={`pending-target-${batch.batch_id}`}
              value={targetId}
              onChange={(event) => setTargetId(event.target.value)}
              disabled={Boolean(busy)}
            >
              <option value="">根目录</option>
              {groups.map((group) => (
                <option key={group.node_id} value={group.node_id}>
                  {group.label}
                </option>
              ))}
            </Select>
          </div>
        ) : null}
        {batch.last_error ? (
          <p className="mt-2 text-xs leading-5 text-danger">
            上次加入失败：{batch.last_error}
          </p>
        ) : null}
      </header>
      {batch.sites.length ? (
        <ul className="divide-y divide-line">
          {batch.sites.map((site) => {
            const siteBusy = busy === `site:${batch.batch_id}:${site.site_key}`;
            return (
              <li key={site.site_key} className="px-3 py-3">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium text-ink">
                      {site.domain || site.site_key}
                    </div>
                    <div className="mt-0.5 break-all text-xs leading-5 text-ink-3">
                      {site.input_value}
                    </div>
                    <div className="mt-1 text-xs leading-5 text-ink-2">
                      {site.reason}
                    </div>
                    {site.active_rule ? (
                      <div className="mt-1 text-xs text-ink-3">
                        生效规则 {site.active_rule.rule_id}@
                        {site.active_rule.rule_version}
                      </div>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {site.action === "build" ? (
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => onBuild(batch, site)}
                        disabled={readOnly || Boolean(busy) || !canBuild}
                      >
                        {siteBusy ? "启动中…" : "接入"}
                      </Button>
                    ) : null}
                    {site.action === "open_build" && site.build_id ? (
                      <Link
                        className="inline-flex h-8 items-center rounded-control border border-line-strong bg-surface px-3 text-xs font-medium text-ink hover:bg-surface-muted"
                        to={`/builds/${encodeURIComponent(site.build_id)}`}
                      >
                        打开构建
                      </Link>
                    ) : null}
                    {site.action === "import" ? (
                      <span className="text-xs text-ink-3">可加入任务树</span>
                    ) : null}
                    {site.action === "none" ? (
                      <span className="text-xs text-ink-3">需先调整批次或规则</span>
                    ) : null}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <div className="px-3 py-4 text-sm text-ink-3">没有可显示的待接入站点。</div>
      )}
      {batch.truncated ? (
        <div className="border-t border-line px-3 py-2 text-xs text-ink-3">
          仅显示前 500 个站点，计数仍按完整批次统计。
        </div>
      ) : null}
    </section>
  );
}

export function WorkbenchPendingTargetsDialog({
  open,
  data,
  nodes,
  busy = "",
  error = "",
  readOnly = false,
  onOpenChange,
  onRetry,
  onBuild,
  onDismiss,
}: PendingTargetsDialogProps) {
  const canBuild = data?.onboarding_available ?? false;
  return (
    <DialogShell
      open={open}
      busy={false}
      title="待接入目标"
      description="查看未加入任务树的批次目标，重试加入或启动接入构建。"
      icon="pending"
      wide
      onOpenChange={onOpenChange}
    >
      <div className="space-y-4 px-4 py-5 sm:px-6">
        {error ? <ErrorNotice title="操作失败" message={error} compact /> : null}
        {readOnly ? (
          <p className="text-xs leading-5 text-ink-3">
            只读预览：可以查看待接入目标，不能接入、重试或忽略。
          </p>
        ) : null}
        {data && !data.onboarding_available && data.onboarding_unavailable_reason ? (
          <p className="text-xs leading-5 text-ink-3">
            接入构建不可用：{data.onboarding_unavailable_reason}
          </p>
        ) : null}
        {!data || data.batches.length === 0 ? (
          <div className="rounded-control border border-dashed border-line px-4 py-8 text-center text-sm text-ink-3">
            没有待接入或未完成加入的目标。
          </div>
        ) : (
          <div className="space-y-3">
            {data.batches.map((batch) => (
              <PendingBatchSection
                key={batch.batch_id}
                batch={batch}
                nodes={nodes}
                busy={busy}
                canBuild={canBuild}
                readOnly={readOnly}
                onRetry={onRetry}
                onBuild={onBuild}
                onDismiss={onDismiss}
              />
            ))}
          </div>
        )}
      </div>
      <footer className="flex justify-end gap-2 border-t border-line bg-surface-muted px-4 py-3 sm:px-6">
        <Button type="button" onClick={() => onOpenChange(false)}>
          关闭
        </Button>
      </footer>
    </DialogShell>
  );
}
