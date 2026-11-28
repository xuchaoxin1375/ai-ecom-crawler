import { Eye, ImageOff } from "lucide-react";
import { useState } from "react";
import { cn } from "../../lib/cn";
import { imageProxyUrl } from "../../lib/media";
import { usePreviewDisplaySettings } from "../../lib/previewSettings";

interface ProductThumbProps {
  src: string;
  alt: string;
  taskId?: string | null;
  className?: string;
  loading?: "lazy" | "eager";
}

export function ProductThumb({
  src,
  alt,
  taskId,
  className,
  loading = "lazy",
}: ProductThumbProps) {
  const [failedSrc, setFailedSrc] = useState("");
  const { thumbnailsEnabled, ready } = usePreviewDisplaySettings();
  const failed = Boolean(src) && failedSrc === src;
  const disabled = ready && !thumbnailsEnabled;
  const loadingPreference = !ready;

  if (!src || failed || disabled || loadingPreference) {
    const label = !src
      ? "没有主图"
      : failed
        ? "图片加载失败"
        : loadingPreference
          ? "正在读取图片预览设置"
          : "缩略图已关闭，点击查看大图";
    return (
      <span
        className={cn(
          "flex shrink-0 items-center justify-center overflow-hidden bg-surface-muted text-ink-3",
          className,
        )}
        title={label}
        aria-label={label}
        role="img"
      >
        {!src || failed ? (
          <ImageOff size={16} aria-hidden="true" />
        ) : (
          <Eye size={16} aria-hidden="true" />
        )}
      </span>
    );
  }

  return (
    <img
      src={imageProxyUrl(src, taskId)}
      alt={alt}
      className={cn("shrink-0 object-cover", className)}
      loading={loading}
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailedSrc(src)}
    />
  );
}
