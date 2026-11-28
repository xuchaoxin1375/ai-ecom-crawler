import * as Dialog from "@radix-ui/react-dialog";
import { SlidersHorizontal, X } from "lucide-react";
import { useState } from "react";
import { ImageProxyForm } from "../settings/ImageProxyForm";
import { PreviewDisplayForm } from "../settings/PreviewDisplaySettings";
import { cn } from "../../lib/cn";

/**
 * Open preview settings in place. The page-level settings area remains the
 * single source of truth for the form, but preview pages should not send the
 * user away from the data they are inspecting.
 */
export function PreviewSettingsButton({ className }: { className?: string }) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex h-7 items-center gap-1 rounded-full border border-line bg-surface px-2.5 text-[11px] font-medium text-ink-2 hover:bg-surface-muted hover:text-ink",
            className,
          )}
          title="调整图片代理、列表缩略图与实时数据加载"
          aria-label="预览设置：图片与列表"
        >
          <SlidersHorizontal size={13} aria-hidden="true" />
          预览设置
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/55" />
        <Dialog.Content className="animate-dialog-in fixed left-1/2 top-1/2 z-50 flex max-h-[92vh] w-[min(720px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-overlay border border-line bg-surface shadow-overlay">
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-3.5 sm:px-6">
            <div className="min-w-0">
              <Dialog.Title className="text-[19px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                预览设置
              </Dialog.Title>
              <Dialog.Description className="mt-0.5 text-xs leading-5 text-ink-3">
                调整商品图片的取图出口、列表缩略图，以及实时数据首批条数和滚动加载批量；保存后当前页立即生效。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label="关闭预览设置"
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
            <ImageProxyForm onSaved={() => setOpen(false)} />
            <div className="mt-5 border-t border-line pt-4">
              <p className="mb-3 text-xs leading-5 text-ink-3">
                列表缩略图、实时数据首批条数和滚动加载批量与系统设置「列表与预览」共用同一项服务端设置。
              </p>
              <PreviewDisplayForm />
            </div>
            <p className="mt-4 border-t border-line pt-3 text-xs leading-5 text-ink-3">
              描述显示方式（单行／换行）在 CSV
              表格表头直接切换；这里调整图片取图、列表缩略图、实时数据首批条数和滚动加载批量。
            </p>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
