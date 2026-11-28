import * as Dialog from "@radix-ui/react-dialog";
import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Download,
  ExternalLink,
  ImageOff,
  Loader2,
  X,
} from "lucide-react";
import type { TaskItem } from "../../lib/api";
import {
  descriptionStatusLabel,
  descriptionStatusTone,
  formatAmount,
} from "../../lib/format";
import { Badge } from "../../components/ui/Badge";
import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import { imageProxyUrl } from "../../lib/media";
import {
  htmlToText,
  missingReasonsText,
  previewAttributes,
  previewImage,
  previewMeta,
  previewName,
  productPreview,
} from "./site";
import { ProductThumb } from "./ProductThumb";

interface ProductPreviewDialogProps {
  open: boolean;
  item: TaskItem | null;
  items?: TaskItem[];
  taskId?: string | null;
  initialTab?: "image" | "description";
  onOpenChange: (open: boolean) => void;
}

function PreviewImage({
  src,
  alt,
  taskId,
  zoom,
  onToggleZoom,
}: {
  src: string;
  alt: string;
  taskId?: string | null;
  zoom: number;
  onToggleZoom: () => void;
}) {
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [attempt, setAttempt] = useState(0);
  const imageRef = useRef<HTMLImageElement>(null);
  const displaySrc = imageProxyUrl(src, taskId);

  // A cached image can finish before React attaches onLoad. Check the DOM
  // node after mount so the dialog does not stay in its transparent loading
  // state forever.
  useEffect(() => {
    const node = imageRef.current;
    if (!node || !node.complete) return;
    setStatus(node.naturalWidth > 0 ? "ready" : "error");
  }, [displaySrc, attempt]);

  return (
    <div className="relative flex min-h-[320px] items-center justify-center overflow-auto rounded-panel border border-line bg-surface-muted p-3">
      {status === "loading" ? (
        <span className="pointer-events-none absolute inset-0 flex items-center justify-center bg-surface-muted/60">
          <Loader2 className="animate-spin text-ink-3" size={20} aria-hidden="true" />
          <span className="sr-only">正在加载图片</span>
        </span>
      ) : null}
      {status === "error" ? (
        <div className="flex flex-col items-center gap-2 px-4 py-8 text-center">
          <ImageOff size={28} className="text-ink-3" aria-hidden="true" />
          <p className="text-sm text-ink-2">图片加载失败</p>
          <p className="max-w-md text-xs leading-5 text-ink-3">
            可以重试、打开原图，或直接打开商品来源页。
          </p>
          <div className="flex flex-wrap items-center justify-center gap-2">
            <Button
              size="sm"
              onClick={() => {
                setStatus("loading");
                setAttempt((value) => value + 1);
              }}
            >
              重试
            </Button>
            <Button asChild size="sm" variant="ghost">
              <a href={src} target="_blank" rel="noreferrer">
                打开原图
              </a>
            </Button>
          </div>
        </div>
      ) : (
        <img
          key={`${displaySrc}-${attempt}`}
          ref={imageRef}
          src={displaySrc}
          alt={alt}
          className={cn(
            "origin-center object-contain transition-opacity duration-150",
            zoom > 1 ? "cursor-zoom-out" : "cursor-zoom-in",
            status === "loading" && "opacity-0",
          )}
          style={
            zoom > 1
              ? {
                  width: `${zoom * 100}%`,
                  maxWidth: "none",
                  maxHeight: "none",
                }
              : { maxWidth: "100%", maxHeight: "56vh" }
          }
          onLoad={() => setStatus("ready")}
          onError={() => setStatus("error")}
          onDoubleClick={onToggleZoom}
          draggable={false}
          decoding="async"
          referrerPolicy="no-referrer"
          title="双击切换适应窗口／放大"
        />
      )}
    </div>
  );
}

export function ProductPreviewDialog({
  open,
  item,
  items,
  taskId,
  initialTab = "image",
  onOpenChange,
}: ProductPreviewDialogProps) {
  const gallery = items?.length ? items : item ? [item] : [];
  const [selectedId, setSelectedId] = useState(
    item?.item_id ?? gallery[0]?.item_id ?? "",
  );
  const [pinnedItem, setPinnedItem] = useState<TaskItem | null>(item);
  const foundIndex = gallery.findIndex((entry) => entry.item_id === selectedId);
  const activeIndex = foundIndex >= 0 ? foundIndex : 0;
  const activeItem =
    foundIndex >= 0 ? gallery[foundIndex] : (pinnedItem ?? gallery[0] ?? item);
  const [tab, setTab] = useState<"image" | "description">(initialTab);
  const [zoom, setZoom] = useState(1);
  const [message, setMessage] = useState("");

  const product = activeItem ? productPreview(activeItem) : {};
  const image = activeItem ? previewImage(activeItem) : "";
  const attributes = activeItem ? previewAttributes(activeItem) : "";
  const description = String(
    product.description_text || product.description_html || "",
  );
  const plainDescription = htmlToText(description);
  const hasImage = Boolean(image);
  const hasDescription = Boolean(plainDescription);
  const activeTab =
    tab === "image" && hasImage
      ? "image"
      : hasDescription
        ? "description"
        : hasImage
          ? "image"
          : "empty";
  const title = activeItem ? previewName(activeItem) : "商品预览";
  const meta = activeItem
    ? [
        product.price_amount != null
          ? `${formatAmount(product.price_amount)} ${
              product.price_currency || ""
            }`.trim()
          : "",
        previewMeta(activeItem),
      ]
        .filter(Boolean)
        .join(" · ")
    : "";
  const canPrev = foundIndex > 0;
  const canNext = foundIndex >= 0 && foundIndex < gallery.length - 1;

  async function copy(value: string, label: string) {
    if (!value) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) throw new Error("浏览器拒绝复制");
      }
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

  function selectIndex(next: number) {
    const nextItem = gallery[next];
    if (!nextItem) return;
    setSelectedId(nextItem.item_id);
    setPinnedItem(nextItem);
    setZoom(1);
    setMessage("");
    if (tab === "image" && !previewImage(nextItem)) {
      const nextDescription = htmlToText(
        productPreview(nextItem).description_text ||
          productPreview(nextItem).description_html ||
          "",
      );
      if (nextDescription) setTab("description");
    }
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === "ArrowLeft" && canPrev) {
      event.preventDefault();
      selectIndex(activeIndex - 1);
    } else if (event.key === "ArrowRight" && canNext) {
      event.preventDefault();
      selectIndex(activeIndex + 1);
    } else if (activeTab === "image" && (event.key === "+" || event.key === "=")) {
      event.preventDefault();
      setZoom((value) => Math.min(4, value + 0.25));
    } else if (activeTab === "image" && event.key === "-") {
      event.preventDefault();
      setZoom((value) => Math.max(1, value - 0.25));
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/55" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 flex max-h-[92vh] w-[min(1040px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-overlay border border-line bg-surface shadow-overlay"
          onKeyDown={handleKeyDown}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-3.5 sm:gap-6 sm:px-6">
            <div className="min-w-0">
              <Dialog.Title className="truncate text-[19px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                {title}
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 truncate text-xs text-ink-3">
                {meta || "商品预览"}
              </Dialog.Description>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {gallery.length > 1 ? (
                <span className="rounded-full border border-line bg-surface-muted px-2 py-0.5 text-[10.5px] tabular text-ink-3">
                  {activeIndex + 1} / {gallery.length}
                </span>
              ) : null}
              <Dialog.Close asChild>
                <button
                  type="button"
                  className="flex h-8 w-8 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                  aria-label="关闭商品预览"
                >
                  <X size={17} aria-hidden="true" />
                </button>
              </Dialog.Close>
            </div>
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
                  aria-selected={activeTab === key}
                  className={cn(
                    "h-7 rounded-full border px-2.5 text-[11px] font-medium",
                    activeTab === key
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

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
            {activeTab === "image" && hasImage ? (
              <div className="space-y-3">
                <div className="relative">
                  <PreviewImage
                    key={image}
                    src={image}
                    alt={title}
                    taskId={taskId}
                    zoom={zoom}
                    onToggleZoom={() => setZoom((value) => (value > 1 ? 1 : 2))}
                  />
                  {gallery.length > 1 ? (
                    <>
                      <button
                        type="button"
                        className="absolute left-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-line bg-surface/95 text-ink-2 shadow-raised hover:bg-surface disabled:pointer-events-none disabled:opacity-30"
                        aria-label="上一张商品"
                        disabled={!canPrev}
                        onClick={() => selectIndex(activeIndex - 1)}
                      >
                        <ChevronLeft size={16} aria-hidden="true" />
                      </button>
                      <button
                        type="button"
                        className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full border border-line bg-surface/95 text-ink-2 shadow-raised hover:bg-surface disabled:pointer-events-none disabled:opacity-30"
                        aria-label="下一张商品"
                        disabled={!canNext}
                        onClick={() => selectIndex(activeIndex + 1)}
                      >
                        <ChevronRight size={16} aria-hidden="true" />
                      </button>
                    </>
                  ) : null}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    disabled={zoom <= 1}
                    onClick={() => setZoom((value) => Math.max(1, value - 0.25))}
                  >
                    缩小
                  </Button>
                  <span className="min-w-12 text-center text-xs text-ink-3 tabular">
                    {Math.round(zoom * 100)}%
                  </span>
                  <Button
                    size="sm"
                    onClick={() => setZoom((value) => Math.min(4, value + 0.25))}
                  >
                    放大
                  </Button>
                  <Button size="sm" onClick={() => setZoom(1)}>
                    适应窗口
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
            ) : activeTab === "description" && hasDescription ? (
              <div className="space-y-3">
                {attributes || product.description_status ? (
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-3">
                    {attributes ? (
                      <span className="break-words">属性：{attributes}</span>
                    ) : null}
                    {product.description_status ? (
                      <Badge
                        tone={descriptionStatusTone(String(product.description_status))}
                        dot={false}
                      >
                        描述
                        {descriptionStatusLabel(String(product.description_status))}
                      </Badge>
                    ) : null}
                  </div>
                ) : null}
                <pre className="max-h-[56vh] overflow-auto whitespace-pre-wrap rounded-panel border border-line bg-surface-muted p-4 font-sans text-sm leading-6 text-ink-2">
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
                  {activeItem ? (
                    <Button asChild size="sm">
                      <a href={activeItem.url} target="_blank" rel="noreferrer">
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
                {activeItem ? (
                  <Button asChild size="sm">
                    <a href={activeItem.url} target="_blank" rel="noreferrer">
                      <ExternalLink size={13} aria-hidden="true" />
                      打开来源页
                    </a>
                  </Button>
                ) : null}
              </div>
            )}
          </div>

          {gallery.length > 1 ? (
            <div className="shrink-0 border-t border-line bg-surface-muted/60 px-3 py-2">
              <div
                className="flex items-center gap-2 overflow-x-auto pb-1"
                role="group"
                aria-label="商品缩略图"
              >
                {gallery.map((entry, entryIndex) => {
                  const entryImage = previewImage(entry);
                  return (
                    <button
                      key={entry.item_id}
                      type="button"
                      className={cn(
                        "relative flex h-14 w-14 shrink-0 items-center justify-center overflow-hidden rounded-control border bg-surface transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/50",
                        entryIndex === activeIndex
                          ? "border-accent ring-2 ring-accent/25"
                          : "border-line hover:border-line-strong",
                      )}
                      aria-label={`查看第 ${entryIndex + 1} 个商品：${previewName(entry)}`}
                      aria-current={entryIndex === activeIndex ? "true" : undefined}
                      title={`${entryIndex + 1}. ${previewName(entry)}`}
                      onClick={() => selectIndex(entryIndex)}
                    >
                      <ProductThumb
                        src={entryImage}
                        alt={previewName(entry)}
                        taskId={taskId}
                        className="h-full w-full"
                      />
                      <span className="absolute bottom-0.5 right-0.5 rounded bg-ink/70 px-1 text-[9px] leading-4 text-white tabular">
                        {entryIndex + 1}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          ) : null}

          <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-2.5 sm:px-6">
            <p className="min-w-0 truncate text-xs text-ink-3" title={activeItem?.url}>
              {activeItem?.url || ""}
            </p>
            {message ? (
              <p
                className="flex shrink-0 items-center gap-1 text-xs text-success"
                role="status"
              >
                <Check size={13} aria-hidden="true" />
                {message}
              </p>
            ) : (
              <p className="hidden text-[10.5px] text-ink-3 sm:block">
                点击缩略图切换商品；←／→ 切换，双击图片缩放
              </p>
            )}
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
