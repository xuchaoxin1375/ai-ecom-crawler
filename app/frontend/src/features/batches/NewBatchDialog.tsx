import * as Dialog from "@radix-ui/react-dialog";
import { useEffect, useState, type ChangeEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { FileUp, X } from "lucide-react";
import {
  createBatch,
  previewBatch,
  startBatch,
  type BatchDraftRequest,
  type BatchPreviewResponse,
  type ImportReport,
} from "../../lib/api";
import { formatNumber, READINESS_LABELS, readinessTone } from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { Input, Textarea } from "../../components/ui/Input";
import { ErrorNotice } from "../../components/ui/ErrorNotice";

interface NewBatchDialogProps {
  open: boolean;
  folderId?: string | null;
  folderName?: string | null;
  onOpenChange: (open: boolean) => void;
  onSaved: (
    batchId: string,
    notice: { tone: "success" | "warning"; text: string },
  ) => void;
}

const EMPTY_FORM = {
  name: "",
  country: "",
  market: "",
  language: "",
  category: "",
  note: "",
  sitesText: "",
};

function optional(value: string): string | null {
  return value.trim() || null;
}

function previewItems(report: ImportReport | null) {
  if (!report) return [];
  return report.items.filter(
    (item) => item.readiness === "invalid" || item.readiness === "duplicate",
  );
}

export function NewBatchDialog({
  open,
  folderId = null,
  folderName = null,
  onOpenChange,
  onSaved,
}: NewBatchDialogProps) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState(EMPTY_FORM);
  const [preview, setPreview] = useState<BatchPreviewResponse["preview"] | null>(null);
  const [previewKey, setPreviewKey] = useState("");
  const [previewError, setPreviewError] = useState("");
  const [retryPreview, setRetryPreview] = useState(0);
  const [collectionMode, setCollectionMode] = useState<"sample" | "formal">("formal");
  const [nameError, setNameError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "start">("");
  const [fileName, setFileName] = useState("");
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const dirty = Boolean(
    form.name.trim() ||
    form.sitesText.trim() ||
    form.category.trim() ||
    form.note.trim() ||
    form.country !== EMPTY_FORM.country ||
    form.market !== EMPTY_FORM.market ||
    form.language !== EMPTY_FORM.language ||
    preview,
  );

  function requestOpenChange(next: boolean) {
    if (next) {
      onOpenChange(true);
      return;
    }
    if (busy) return;
    if (dirty) {
      setConfirmDiscard(true);
      return;
    }
    onOpenChange(false);
  }

  function update<K extends keyof typeof form>(key: K, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
    if (key === "name") setNameError("");
  }

  function body(): BatchDraftRequest {
    return {
      name: form.name.trim(),
      collection_mode: collectionMode,
      country: optional(form.country),
      market: optional(form.market),
      language: optional(form.language),
      category: optional(form.category),
      note: optional(form.note),
      folder_id: folderId,
      sites_text: form.sitesText,
    };
  }

  const sitesText = form.sitesText.trim();
  const market = form.market.trim();
  const currentPreviewKey = JSON.stringify([sitesText, market, retryPreview]);
  const previewDirty = previewKey !== currentPreviewKey;

  useEffect(() => {
    if (!open || !sitesText) return;
    let ignore = false;
    const timer = window.setTimeout(() => {
      void previewBatch({
        name: "匹配预览",
        sites_text: sitesText,
        market: market || null,
        collection_mode: "formal",
      })
        .then((payload) => {
          if (ignore) return;
          setPreview(payload.preview);
          setPreviewError("");
          setPreviewKey(currentPreviewKey);
        })
        .catch((exc: unknown) => {
          if (ignore) return;
          setPreviewError(exc instanceof Error ? exc.message : String(exc));
          setPreview(null);
          setPreviewKey(currentPreviewKey);
        });
    }, 350);
    return () => {
      ignore = true;
      window.clearTimeout(timer);
    };
  }, [currentPreviewKey, market, open, sitesText]);

  async function save(start: boolean) {
    if (!form.name.trim()) {
      setNameError("请输入批次名称。");
      document.getElementById("new-batch-name")?.focus();
      return;
    }
    setBusy(start ? "start" : "save");
    setError("");
    try {
      const created = await createBatch(body());
      const batchId = created.batch.batch_id;
      await queryClient.invalidateQueries({ queryKey: ["batches"] });
      if (start) {
        try {
          const result = await startBatch(batchId);
          await queryClient.invalidateQueries({ queryKey: ["batches"] });
          onSaved(batchId, {
            tone: result.accepted.length > 0 ? "success" : "warning",
            text: `批次已保存：受理 ${formatNumber(
              result.accepted.length,
            )} 个站点，跳过 ${formatNumber(result.skipped.length)} 个。`,
          });
          onOpenChange(false);
          return;
        } catch (exc) {
          await queryClient.invalidateQueries({ queryKey: ["batches"] });
          onSaved(batchId, {
            tone: "warning",
            text: `批次已保存，但启动失败：${
              exc instanceof Error ? exc.message : String(exc)
            }。可在批次中重试启动。`,
          });
          onOpenChange(false);
          return;
        }
      }
      onSaved(batchId, { tone: "success", text: "批次草稿已保存。" });
      onOpenChange(false);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy("");
    }
  }

  async function readCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const text = await file.text();
    const lines = text.split(/\r?\n/);
    if (
      lines.length &&
      /^\s*(url|site|domain|website|网址|站点|域名)\s*(,|$)/i.test(lines[0])
    ) {
      lines.shift();
    }
    const cleaned = lines.join("\n").trim();
    setForm((current) => ({
      ...current,
      sitesText: current.sitesText.trim()
        ? `${current.sitesText.trim()}\n${cleaned}`
        : cleaned,
    }));
    setFileName(file.name);
    event.target.value = "";
  }

  const invalidItems = previewItems(preview?.import ?? null);
  const summary = preview?.import.summary;
  const canSave =
    !busy && (!sitesText || (!previewDirty && Boolean(summary?.accepted)));
  const canStart = canSave && Boolean(summary?.ready);

  return (
    <Dialog.Root open={open} onOpenChange={requestOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 flex max-h-[92vh] w-[min(1040px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("new-batch-name")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:gap-6 sm:px-6">
            <div>
              <Dialog.Title className="text-[22px] leading-8 font-semibold tracking-[-0.01em] text-ink">
                新建采集批次
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-ink-2">
                提交采集入口和计划，查看哪些目标可以开始。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭新建批次"
                disabled={Boolean(busy)}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="grid min-h-0 flex-1 grid-cols-1 overflow-y-auto lg:grid-cols-[7fr_5fr] lg:overflow-hidden">
            <div className="space-y-5 p-4 sm:p-6 lg:overflow-y-auto">
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="new-batch-name"
                >
                  批次名称 <span className="text-danger">*</span>
                </label>
                <Input
                  id="new-batch-name"
                  value={form.name}
                  maxLength={200}
                  placeholder="如 法国手工纺织 2026-11"
                  aria-invalid={Boolean(nameError)}
                  aria-describedby={nameError ? "new-batch-name-error" : undefined}
                  onChange={(event) => update("name", event.target.value)}
                />
                {nameError ? (
                  <p id="new-batch-name-error" className="mt-1 text-xs text-danger">
                    {nameError}
                  </p>
                ) : null}
                {folderName ? (
                  <p className="mt-2 text-xs text-ink-3">
                    将保存到分组：
                    <span className="font-medium text-ink-2">{folderName}</span>
                  </p>
                ) : null}
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label
                    className="mb-1 block text-xs font-medium text-ink-3"
                    htmlFor="new-batch-plan"
                  >
                    采集计划
                  </label>
                  <select
                    id="new-batch-plan"
                    className="h-9 w-full rounded-control border border-line px-2 text-sm"
                    value={collectionMode}
                    onChange={(event) =>
                      setCollectionMode(
                        event.target.value === "sample" ? "sample" : "formal",
                      )
                    }
                  >
                    <option value="formal">正式采集</option>
                    <option value="sample">试采</option>
                  </select>
                  <p className="mt-1 text-xs text-ink-3">
                    {collectionMode === "formal"
                      ? "按约定范围，每目标最多 1 万件或 1 小时。"
                      : "每目标最多 20 件商品或 180 秒。"}
                  </p>
                </div>
                <div>
                  <label
                    className="mb-1 block text-xs font-medium text-ink-3"
                    htmlFor="new-batch-market"
                  >
                    市场
                  </label>
                  <Input
                    id="new-batch-market"
                    value={form.market}
                    placeholder="如 FR"
                    onChange={(event) => update("market", event.target.value)}
                  />
                </div>
              </div>
              <details className="rounded-control border border-line px-3 py-2">
                <summary className="cursor-pointer text-sm text-ink-2">
                  批次资料
                </summary>
                <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label
                      className="mb-1 block text-xs text-ink-3"
                      htmlFor="new-batch-country"
                    >
                      国家
                    </label>
                    <Input
                      id="new-batch-country"
                      value={form.country}
                      onChange={(event) => update("country", event.target.value)}
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-ink-3"
                      htmlFor="new-batch-language"
                    >
                      语言
                    </label>
                    <Input
                      id="new-batch-language"
                      value={form.language}
                      placeholder="如 fr-FR"
                      onChange={(event) => update("language", event.target.value)}
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-ink-3"
                      htmlFor="new-batch-category"
                    >
                      品类
                    </label>
                    <Input
                      id="new-batch-category"
                      value={form.category}
                      placeholder="如 手工／纺织"
                      onChange={(event) => update("category", event.target.value)}
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-ink-3"
                      htmlFor="new-batch-note"
                    >
                      备注
                    </label>
                    <Input
                      id="new-batch-note"
                      value={form.note}
                      maxLength={2000}
                      placeholder="可选，用于交接说明"
                      onChange={(event) => update("note", event.target.value)}
                    />
                  </div>
                </div>
              </details>

              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="new-batch-sites"
                >
                  站点列表
                </label>
                <Textarea
                  id="new-batch-sites"
                  rows={8}
                  spellCheck={false}
                  value={form.sitesText}
                  placeholder={
                    "https://exemple-boutique.fr/\nhttps://autre-atelier.fr/"
                  }
                  onChange={(event) => update("sitesText", event.target.value)}
                />
                <div className="mt-2 flex items-center justify-between gap-3">
                  <p className="text-xs text-ink-3">
                    每行一个网址或域名；CSV 取第一列，表头自动跳过。
                  </p>
                  <input
                    id="new-batch-csv"
                    type="file"
                    accept=".csv,.txt,text/csv,text/plain"
                    className="sr-only"
                    onChange={readCsv}
                  />
                  <label
                    className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-control border border-line-strong bg-surface px-3 text-xs font-medium text-ink hover:bg-surface-muted"
                    htmlFor="new-batch-csv"
                  >
                    <FileUp size={14} aria-hidden="true" />
                    上传 CSV
                  </label>
                </div>
                {fileName ? (
                  <p className="mt-1 text-xs text-ink-3">已追加 {fileName}</p>
                ) : null}
              </div>

              {error ? (
                <ErrorNotice
                  title="操作失败"
                  message={error}
                  compact
                  onRetry={undefined}
                />
              ) : null}
            </div>

            <aside className="border-t border-line bg-surface-muted p-4 sm:p-6 lg:overflow-y-auto lg:border-l lg:border-t-0">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h2 className="text-[17px] leading-6 font-semibold text-ink">
                    匹配预览
                  </h2>
                  <p className="mt-0.5 text-xs text-ink-3">只读预览，不会创建批次。</p>
                </div>
              </div>

              {!sitesText || previewDirty || !preview ? (
                <div className="mt-8 rounded-panel border border-dashed border-line-strong px-4 py-8">
                  {sitesText && !previewDirty && previewError ? (
                    <ErrorNotice
                      title="匹配失败"
                      message={previewError}
                      compact
                      onRetry={() => setRetryPreview((value) => value + 1)}
                    />
                  ) : (
                    <p className="text-sm text-ink-3" role="status">
                      {sitesText ? "正在匹配采集范围…" : "输入站点后会自动匹配。"}
                    </p>
                  )}
                </div>
              ) : (
                <div className="mt-4 space-y-4">
                  <div className="grid grid-cols-2 gap-2">
                    {[
                      { label: "可采", value: summary?.ready ?? 0 },
                      { label: "待接入", value: summary?.needs_onboarding ?? 0 },
                      { label: "重复", value: summary?.duplicate ?? 0 },
                      { label: "无效", value: summary?.invalid ?? 0 },
                    ].map((item) => (
                      <div
                        key={item.label}
                        className="rounded-panel border border-line bg-surface px-3 py-2"
                      >
                        <p className="text-xs text-ink-3">{item.label}</p>
                        <p className="mt-0.5 text-lg font-semibold text-ink tabular">
                          {formatNumber(item.value)}
                        </p>
                      </div>
                    ))}
                  </div>

                  {summary && summary.needs_onboarding > 0 ? (
                    <p className="rounded-control border border-warning/25 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning">
                      {summary.needs_onboarding}{" "}
                      个站点没有匹配到受管规则包，会保留为“待接入”，不阻塞其他站点。
                    </p>
                  ) : null}

                  {invalidItems.length > 0 ? (
                    <div className="rounded-control border border-danger/25 bg-danger-soft px-3 py-2">
                      <p className="text-xs font-semibold text-danger">
                        {invalidItems.length} 条无效／重复
                      </p>
                      <ul className="mt-1 space-y-1">
                        {invalidItems.map((item, index) => (
                          <li
                            key={`${item.input_value}-${index}`}
                            className="text-xs leading-5 text-ink-2"
                          >
                            <code className="font-mono text-[11px]">
                              {item.input_value}
                            </code>
                            ：{item.reason}
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  <div className="overflow-hidden rounded-panel border border-line bg-surface">
                    <table className="w-full table-fixed border-collapse text-xs">
                      <caption className="sr-only">站点匹配结果</caption>
                      <thead>
                        <tr>
                          <th
                            scope="col"
                            className="border-b border-line bg-surface-muted px-3 py-2 text-left font-medium text-ink-3"
                          >
                            站点
                          </th>
                          <th
                            scope="col"
                            className="w-20 border-b border-line bg-surface-muted px-3 py-2 text-left font-medium text-ink-3"
                          >
                            匹配
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {preview.import.items
                          .filter((item) => item.stored)
                          .map((item, index) => (
                            <tr
                              key={`${item.input_value}-${index}`}
                              className="border-b border-line last:border-0"
                            >
                              <td className="px-3 py-2 align-top">
                                <p
                                  className="truncate font-medium text-ink"
                                  title={item.input_value}
                                >
                                  {item.input_value}
                                </p>
                                <p
                                  className="mt-0.5 truncate text-[11px] text-ink-3"
                                  title={item.reason}
                                >
                                  {item.reason}
                                </p>
                              </td>
                              <td className="px-3 py-2 align-top">
                                <Badge tone={readinessTone(item.readiness)}>
                                  {READINESS_LABELS[item.readiness]}
                                </Badge>
                              </td>
                            </tr>
                          ))}
                        {preview.import.items.length === 0 ? (
                          <tr>
                            <td
                              colSpan={2}
                              className="px-3 py-6 text-center text-ink-3"
                            >
                              没有站点；可以保存一个空草稿，稍后再导入。
                            </td>
                          </tr>
                        ) : null}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </aside>
          </div>

          {confirmDiscard ? (
            <div className="flex flex-col items-start gap-3 border-t border-warning/25 bg-warning-soft px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-6">
              <p className="text-sm text-warning">
                表单里还有未提交内容，确定关闭弹窗？
              </p>
              <div className="flex items-center gap-2">
                <Button size="sm" onClick={() => setConfirmDiscard(false)}>
                  继续编辑
                </Button>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => {
                    setConfirmDiscard(false);
                    onOpenChange(false);
                  }}
                >
                  放弃并关闭
                </Button>
              </div>
            </div>
          ) : null}

          <footer className="flex flex-col items-start gap-3 border-t border-line px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
            <p className="text-xs text-ink-3">
              保存草稿和启动分离；启动只受理可采且未开始的站点。
            </p>
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto sm:justify-end">
              <Dialog.Close asChild>
                <Button variant="ghost" disabled={Boolean(busy)}>
                  取消
                </Button>
              </Dialog.Close>
              <Button
                variant={canStart ? "secondary" : "primary"}
                onClick={() => void save(false)}
                disabled={!canSave}
              >
                {busy === "save" ? "保存中…" : "保存草稿"}
              </Button>
              {canStart || busy === "start" ? (
                <Button
                  variant="primary"
                  onClick={() => void save(true)}
                  disabled={!canStart}
                >
                  {busy === "start"
                    ? "启动中…"
                    : `保存并启动 ${summary?.ready ?? 0} 个`}
                </Button>
              ) : null}
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
