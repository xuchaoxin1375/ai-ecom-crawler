import * as Dialog from "@radix-ui/react-dialog";
import { useState, type ChangeEvent } from "react";
import { FileUp, X } from "lucide-react";
import {
  importBatch,
  type BatchDetail,
  type BatchImportResponse,
  type ImportReport,
} from "../../lib/api";
import { formatNumber } from "../../lib/format";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Textarea } from "../../components/ui/Input";

interface ImportSitesDialogProps {
  open: boolean;
  batch: BatchDetail;
  onOpenChange: (open: boolean) => void;
  onImported: (response: BatchImportResponse) => void;
}

function issueItems(report: ImportReport | null) {
  if (!report) return [];
  return report.items.filter(
    (item) => item.readiness === "invalid" || item.readiness === "duplicate",
  );
}

export function ImportSitesDialog({
  open,
  batch,
  onOpenChange,
  onImported,
}: ImportSitesDialogProps) {
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<ImportReport | null>(null);
  const [confirmDiscard, setConfirmDiscard] = useState(false);

  const dirty = Boolean(text.trim());
  const canImport = Boolean(text.trim()) && !busy;
  const issues = issueItems(report);

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

  async function runImport() {
    if (!canImport) return;
    setBusy(true);
    setError("");
    setConfirmDiscard(false);
    try {
      const response = await importBatch(batch.batch_id, {
        name: batch.name,
        sites_text: text,
      });
      setReport(response.import);
      setText("");
      setFileName("");
      onImported(response);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(false);
    }
  }

  async function readCsv(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    const content = await file.text();
    const lines = content.split(/\r?\n/);
    if (
      lines.length &&
      /^\s*(url|site|domain|website|网址|站点|域名)\s*(,|$)/i.test(lines[0])
    ) {
      lines.shift();
    }
    const cleaned = lines.join("\n").trim();
    setText((current) => (current.trim() ? `${current.trim()}\n${cleaned}` : cleaned));
    setFileName(file.name);
    event.target.value = "";
  }

  return (
    <Dialog.Root open={open} onOpenChange={requestOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="fixed left-1/2 top-1/2 z-50 flex max-h-[86vh] w-[min(720px,calc(100vw-64px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document.getElementById("import-sites-text")?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-6 border-b border-line px-6 py-4">
            <div>
              <Dialog.Title className="text-[22px] leading-8 font-semibold tracking-[-0.01em] text-ink">
                继续导入站点
              </Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-ink-2">
                把站点追加到“{batch.name}”；导入会立即匹配规则包并写入批次。
              </Dialog.Description>
            </div>
            <button
              type="button"
              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
              aria-label="关闭继续导入"
              disabled={busy}
              onClick={() => requestOpenChange(false)}
            >
              <X size={17} aria-hidden="true" />
            </button>
          </header>

          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-6 py-5">
            <div>
              <label
                className="mb-1 block text-xs font-medium text-ink-3"
                htmlFor="import-sites-text"
              >
                追加站点
              </label>
              <Textarea
                id="import-sites-text"
                rows={7}
                spellCheck={false}
                value={text}
                placeholder={"https://exemple-boutique.fr/\nhttps://autre-atelier.fr/"}
                onChange={(event) => setText(event.target.value)}
              />
              <div className="mt-2 flex items-center justify-between gap-3">
                <p className="text-xs text-ink-3">
                  每行一个网址或域名；CSV 取第一列，表头自动跳过。
                </p>
                <input
                  id="import-sites-csv"
                  type="file"
                  accept=".csv,.txt,text/csv,text/plain"
                  className="sr-only"
                  onChange={readCsv}
                />
                <label
                  className="inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-control border border-line-strong bg-surface px-3 text-xs font-medium text-ink hover:bg-surface-muted"
                  htmlFor="import-sites-csv"
                >
                  <FileUp size={14} aria-hidden="true" />
                  上传 CSV
                </label>
              </div>
              {fileName ? (
                <p className="mt-1 text-xs text-ink-3">已追加 {fileName}</p>
              ) : null}
            </div>

            {error ? <ErrorNotice title="导入失败" message={error} compact /> : null}

            {report ? (
              <div className="space-y-3 border-t border-line pt-4">
                <div className="flex items-baseline justify-between gap-3">
                  <h2 className="text-[15px] leading-6 font-semibold text-ink">
                    本次导入结果
                  </h2>
                  <span className="text-xs text-ink-3">
                    共 {formatNumber(report.summary.total)} 条
                  </span>
                </div>

                <div className="grid grid-cols-4 gap-2">
                  {[
                    { label: "可采", value: report.summary.ready },
                    { label: "待接入", value: report.summary.needs_onboarding },
                    { label: "重复", value: report.summary.duplicate },
                    { label: "无效", value: report.summary.invalid },
                  ].map((item) => (
                    <div
                      key={item.label}
                      className="rounded-panel border border-line bg-surface-muted px-3 py-2"
                    >
                      <p className="text-xs text-ink-3">{item.label}</p>
                      <p className="mt-0.5 text-lg font-semibold text-ink tabular">
                        {formatNumber(item.value)}
                      </p>
                    </div>
                  ))}
                </div>

                {report.summary.needs_onboarding > 0 ? (
                  <p className="rounded-control border border-warning/25 bg-warning-soft px-3 py-2 text-xs leading-5 text-warning">
                    {formatNumber(report.summary.needs_onboarding)}{" "}
                    个站点没有匹配到受管规则包，会保留为“待接入”，不阻塞其他站点。
                  </p>
                ) : null}

                {issues.length > 0 ? (
                  <div className="rounded-control border border-danger/25 bg-danger-soft px-3 py-2">
                    <p className="text-xs font-semibold text-danger">
                      {formatNumber(issues.length)} 条无效／重复
                    </p>
                    <ul className="mt-1 space-y-1">
                      {issues.map((item, index) => (
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
              </div>
            ) : null}
          </div>

          {confirmDiscard ? (
            <div className="flex items-center justify-between gap-4 border-t border-warning/25 bg-warning-soft px-6 py-3">
              <p className="text-sm text-warning">
                输入框里还有未导入的站点，确定关闭弹窗？
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

          <footer className="flex items-center justify-between gap-4 border-t border-line px-6 py-4">
            <p className="text-xs text-ink-3">
              导入会立即写入批次；重复和无效条目会保留并标出原因。
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                onClick={() => requestOpenChange(false)}
                disabled={busy}
              >
                完成
              </Button>
              <Button
                variant="primary"
                onClick={() => void runImport()}
                disabled={!canImport}
              >
                {busy ? "导入中…" : "导入并匹配"}
              </Button>
            </div>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
