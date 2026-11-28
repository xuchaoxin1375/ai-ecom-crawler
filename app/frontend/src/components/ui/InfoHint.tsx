import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import { Info } from "lucide-react";
import { cn } from "../../lib/cn";

interface InfoHintProps {
  content: ReactNode;
  label: string;
  className?: string;
}

interface TooltipPosition {
  top: number;
  left: number;
  above: boolean;
  maxWidth: number;
}

/**
 * Small information control for table cells. The native hover target is a
 * 16px icon with a 24px invisible hit area; the explanation is portalled to
 * the body so it is not clipped by table overflow containers. Click pins the
 * hint for touch users, Escape or an outside pointer press closes it.
 */
export function InfoHint({ content, label, className }: InfoHintProps) {
  const id = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const [open, setOpen] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [position, setPosition] = useState<TooltipPosition>({
    top: 0,
    left: 0,
    above: true,
    maxWidth: 280,
  });

  function place() {
    const button = buttonRef.current;
    if (!button) return;
    const rect = button.getBoundingClientRect();
    const maxWidth = Math.min(280, window.innerWidth - 16);
    const half = maxWidth / 2;
    const left = Math.min(
      Math.max(rect.left + rect.width / 2, half + 8),
      window.innerWidth - half - 8,
    );
    const above = rect.top > 96;
    setPosition({
      top: above ? rect.top - 8 : rect.bottom + 8,
      left,
      above,
      maxWidth,
    });
  }

  function show(nextPinned = false) {
    place();
    setPinned(nextPinned);
    setOpen(true);
  }

  function hide() {
    setPinned(false);
    setOpen(false);
  }

  useEffect(() => {
    if (!open) return;
    const close = () => {
      setPinned(false);
      setOpen(false);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (buttonRef.current?.contains(event.target as Node)) return;
      close();
    };
    window.addEventListener("resize", close);
    document.addEventListener("scroll", close, true);
    document.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("resize", close);
      document.removeEventListener("scroll", close, true);
      document.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "Escape") return;
    event.preventDefault();
    event.stopPropagation();
    hide();
  }

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        className={cn(
          "relative flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-ink-3 transition-colors after:absolute after:-inset-1 after:content-[''] hover:text-accent focus-visible:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
          className,
        )}
        aria-label={label}
        aria-describedby={open ? id : undefined}
        onClick={(event) => {
          event.stopPropagation();
          if (open && pinned) {
            hide();
          } else {
            show(true);
          }
        }}
        onMouseEnter={() => {
          if (!open) show();
        }}
        onMouseLeave={() => {
          if (!pinned) hide();
        }}
        onFocus={() => {
          if (!open) show();
        }}
        onBlur={hide}
        onKeyDown={handleKeyDown}
      >
        <Info size={12} aria-hidden="true" />
      </button>
      {open
        ? createPortal(
            <div
              id={id}
              role="tooltip"
              className="pointer-events-none fixed z-50 rounded-control border border-line bg-surface px-2.5 py-2 text-[11px] leading-4 text-ink-2 shadow-raised"
              style={{
                top: position.top,
                left: position.left,
                maxWidth: position.maxWidth,
                transform: position.above
                  ? "translate(-50%, -100%)"
                  : "translate(-50%, 0)",
              }}
            >
              {content}
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
