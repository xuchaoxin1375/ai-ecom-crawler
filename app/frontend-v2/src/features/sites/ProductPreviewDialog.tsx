import * as Dialog from "@radix-ui/react-dialog";
import { useState } from "react";
import { Check, Copy, Download, ExternalLink, X } from "lucide-react";
import type { TaskItem } from "../../lib/api";
import {
  descriptionStatusLabel,
  descriptionStatusTone,
  formatAmount,
} from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import {
  missingReasonsText,
  previewImage,
  previewMeta,
  previewName,
  productPreview,
} from "./site";

interface ProductPreviewDialogProps {
  open: boolean;
  item: TaskItem | null;
  initialTab?: "image" | "description";
  onOpenChange: (open: boolean) => void;
}

function stripHtml(value: string): string {
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|li|h[1-6])>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+/g, " ")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function ProductPreviewDialog({
  open,
  item,
  initialTab = "image",
  onOpenChange,
}: ProductPreviewDialogProps) {
  const image = item ? previewImage(item) : "";
  const [tab, setTab] = useState<"image" | "description">(
    initialTab === "image" && !image ? "description" : initialTab,
  );
  const [zoom, setZoom] = useState(1);
  const [message, setMessage] = useState("");

  const product = item ? productPreview(item) : {};
  const description = String(
    product.description_text || product.description_html || "",
  );
  const plainDescription = stripHtml(description);
  const hasImage = Boolean(image);
  const hasDescription = Boolean(plainDescription);
  const title = item ? previewName(item) : "商品预览";
  const meta = item
    ? [
        product.price_amount != null
          ? `${formatAmount(product.price_amount)} ${
              product.price_currency || ""
            }`.trim()
          : "",
        previewMeta(item),
      ]
        .filter(Boolean)
        .join(" · ")
    : "";

  async function copy(value: string, label: string) {
    if (!value) return;
    try {
      await navigator.clipboard.writeText(value);
      setMessage(`${label}已复制`);
    } catch {
      setMessage("复制失败，请手动选择文本");
    }
  }

  async function downloadImage() {
    if (!image) return;
    try {
      const response = await fetch(image);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `image-${Date.now()}.${
        blob.type.includes("png") ? "png" : "jpg"
      }`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
      setMessage("图片已开始下载");
    } catch {
      setMessage("浏览器阻止了跨域下载，请使用“打开原图”");
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/55" />
        <Dialog.Content className="animate-dialog-in fixed left-1/2 top-1/2 z-50 flex max-h-[92vh] w-[min(960px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-overlay border border-line bg-surface shadow-overlay">
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:gap-6 sm:px-6">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                {title}
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 truncate text-xs text-ink-3">
                {meta || "商品预览"}
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭商品预览"
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          {hasImage && hasDescription ? (
            <div
              className="flex items-center gap-1 overflow-x-auto border-b border-line px-4 py-2 sm:px-6"
              role="tablist"
              aria-label="预览内容"
            >
              {(
                [
                  ["image", "图片"],
                  ["description", "完整描述"],
                ] as const
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  role="tab"
                  aria-selected={tab === key}
                  className={cn(
                    "h-7 rounded-full border px-2.5 text-[11px] font-medium",
                    tab === key
                      ? "border-accent/30 bg-accent-soft text-accent"
                      : "border-line bg-surface text-ink-2 hover:bg-surface-muted",
                  )}
                  onClick={() => setTab(key)}
                >
                  {label}
                </button>
              ))}
            </div>
          ) : null}

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
            {tab === "image" && hasImage ? (
              <div className="space-y-3">
                <div className="flex min-h-[320px] items-center justify-center overflow-auto rounded-panel border border-line bg-surface-muted p-4">
                  <img
                    src={image}
                    alt={title}
                    className="max-h-[52vh] max-w-full origin-center object-contain transition-transform"
                    style={{ transform: `scale(${zoom})` }}
                    referrerPolicy="no-referrer"
                  />
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    disabled={zoom <= 1}
                    onClick={() => setZoom((value) => Math.max(1, value - 0.25))}
                  >
                    缩小
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => setZoom((value) => Math.min(4, value + 0.25))}
                  >
                    放大
                  </Button>
                  <Button size="sm" onClick={() => setZoom(1)}>
                    复位
                  </Button>
                  <Button size="sm" onClick={() => void copy(image, "图片 URL")}>
                    <Copy size={13} aria-hidden="true" />
                    复制图片 URL
                  </Button>
                  <Button size="sm" onClick={() => void downloadImage()}>
                    <Download size={13} aria-hidden="true" />
                    下载图片
                  </Button>
                  <Button asChild size="sm">
                    <a href={image} target="_blank" rel="noreferrer">
                      <ExternalLink size={13} aria-hidden="true" />
                      打开原图
                    </a>
                  </Button>
                </div>
              </div>
            ) : hasDescription ? (
              <div className="space-y-3">
                <pre className="max-h-[52vh] overflow-auto whitespace-pre-wrap rounded-panel border border-line bg-surface-muted p-4 font-sans text-sm leading-6 text-ink-2">
                  {plainDescription}
                </pre>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() => void copy(plainDescription, "描述文本")}
                  >
                    <Copy size={13} aria-hidden="true" />
                    复制文本
                  </Button>
                  {product.description_html ? (
                    <Button
                      size="sm"
                      onClick={() =>
                        void copy(String(product.description_html), "描述 HTML")
                      }
                    >
                      复制 HTML
                    </Button>
                  ) : null}
                  {item ? (
                    <Button asChild size="sm">
                      <a href={item.url} target="_blank" rel="noreferrer">
                        <ExternalLink size={13} aria-hidden="true" />
                        打开来源页
                      </a>
                    </Button>
                  ) : null}
                </div>
              </div>
            ) : (
              <div className="space-y-3 rounded-panel border border-line bg-surface-muted px-4 py-4">
                <p className="text-sm text-ink-2">
                  这个预览没有正文；完整描述请查看任务 CSV 或导出结果。
                </p>
                <div className="flex flex-wrap items-center gap-2">
                  {product.description_status ? (
                    <Badge
                      tone={descriptionStatusTone(String(product.description_status))}
                      dot={false}
                    >
                      描述
                      {descriptionStatusLabel(String(product.description_status))}
                    </Badge>
                  ) : null}
                  {product.partial_reason ? (
                    <span className="text-xs text-ink-3">
                      {String(product.partial_reason)}
                    </span>
                  ) : null}
                </div>
                {product.missing_reasons ? (
                  <p className="text-xs leading-5 text-ink-3">
                    缺失字段：{missingReasonsText(product.missing_reasons)}
                  </p>
                ) : null}
                {item ? (
                  <Button asChild size="sm">
                    <a href={item.url} target="_blank" rel="noreferrer">
                      <ExternalLink size={13} aria-hidden="true" />
                      打开来源页
                    </a>
                  </Button>
                ) : null}
              </div>
            )}
          </div>

          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-6">
            <p className="min-w-0 truncate text-xs text-ink-3" title={item?.url}>
              {item?.url || ""}
            </p>
            {message ? (
              <p
                className="flex shrink-0 items-center gap-1 text-xs text-success"
                role="status"
              >
                <Check size={13} aria-hidden="true" />
                {message}
              </p>
            ) : null}
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
