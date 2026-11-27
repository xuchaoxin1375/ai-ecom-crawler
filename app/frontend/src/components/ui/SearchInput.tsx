import { useRef, type ChangeEventHandler, type InputHTMLAttributes } from "react";
import { Search, X } from "lucide-react";
import { cn } from "../../lib/cn";
import { Input } from "./Input";

interface SearchInputProps extends Omit<
  InputHTMLAttributes<HTMLInputElement>,
  "type" | "value" | "onChange"
> {
  value: string;
  onChange: ChangeEventHandler<HTMLInputElement>;
  onClear: () => void;
  clearLabel: string;
  density?: "sm" | "md";
  inputClassName?: string;
}

export function SearchInput({
  value,
  onChange,
  onClear,
  clearLabel,
  density = "md",
  className,
  inputClassName,
  onKeyDown,
  ...props
}: SearchInputProps) {
  const wrapperRef = useRef<HTMLDivElement>(null);
  const hasValue = value.length > 0;
  const iconSize = density === "sm" ? 12 : 15;

  function clear() {
    onClear();
    wrapperRef.current?.querySelector("input")?.focus();
  }

  return (
    <div ref={wrapperRef} className={cn("relative min-w-0", className)}>
      <Search
        className={cn(
          "pointer-events-none absolute top-1/2 -translate-y-1/2 text-ink-3",
          density === "sm" ? "left-2" : "left-3",
        )}
        size={iconSize}
        aria-hidden="true"
      />
      <Input
        type="text"
        role="searchbox"
        className={cn(
          density === "sm" ? "h-7 pl-7 pr-8 text-xs" : "h-9 pl-9 pr-9",
          inputClassName,
        )}
        value={value}
        onChange={onChange}
        onKeyDown={(event) => {
          if (event.key === "Escape" && hasValue) {
            event.preventDefault();
            event.stopPropagation();
            clear();
          }
          onKeyDown?.(event);
        }}
        {...props}
      />
      {hasValue ? (
        <button
          type="button"
          className={cn(
            "absolute top-1/2 flex h-6 w-6 -translate-y-1/2 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
            density === "sm" ? "right-0.5" : "right-1.5",
          )}
          aria-label={clearLabel}
          title={clearLabel}
          onMouseDown={(event) => event.preventDefault()}
          onClick={clear}
        >
          <X size={density === "sm" ? 12 : 14} aria-hidden="true" />
        </button>
      ) : null}
    </div>
  );
}
