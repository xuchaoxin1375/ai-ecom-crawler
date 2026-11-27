import * as Dialog from "@radix-ui/react-dialog";
import { useQuery } from "@tanstack/react-query";
import { Layers, ListPlus, X } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  getBatch,
  getBatches,
  type BatchDraftRequest,
  type WorkbenchNode,
} from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input, Select, Textarea } from "../../components/ui/Input";

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
  icon: "import" | "new";
  onOpenChange: (open: boolean) => void;
  children: ReactNode;
}

function DialogShell({
  open,
  busy,
  title,
  description,
  icon,
  onOpenChange,
  children,
}: DialogShellProps) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(620px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            const target = (
              event.currentTarget as HTMLElement
            ).querySelector<HTMLElement>(
              "input:not([type='hidden']), select, textarea",
            );
            target?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                {icon === "import" ? <ListPlus size={17} /> : <Layers size={17} />}
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
            还没有批次可添加。先到
            <Link className="mx-1 text-accent hover:underline" to="/batches">
              采集批次
            </Link>
            创建并导入站点，再回到这里批量添加。
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

interface NewBatchDialogProps {
  open: boolean;
  nodes: WorkbenchNode[];
  initialParentId?: string | null;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (
    values: BatchDraftRequest & { workbench_parent_id: string | null },
  ) => void;
}

export function WorkbenchNewBatchDialog({
  open,
  nodes,
  initialParentId = null,
  busy = false,
  error = "",
  onOpenChange,
  onSubmit,
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
              每行一个站点；未匹配规则的站点会留在批次中等待接入，不会创建任务定义。
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
