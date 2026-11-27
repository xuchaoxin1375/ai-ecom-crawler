import { ImageOff } from "lucide-react";
import { useState } from "react";
import { cn } from "../../lib/cn";
import { imageProxyUrl } from "../../lib/media";

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
  const failed = Boolean(src) && failedSrc === src;

  if (!src || failed) {
    return (
      <span
        className={cn(
          "flex shrink-0 items-center justify-center overflow-hidden bg-surface-muted text-ink-3",
          className,
        )}
        title={failed ? "图片加载失败" : "没有主图"}
        aria-label={failed ? "图片加载失败" : "没有主图"}
        role="img"
      >
        <ImageOff size={16} aria-hidden="true" />
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
