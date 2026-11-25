import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type PointerEvent,
} from "react";
import { cn } from "../../lib/cn";

const KEYBOARD_STEP = 8;
const SHIFT_STEP = 32;

interface ColumnResizeHandleProps {
  label: string;
  width: number;
  minWidth: number;
  maxWidth: number;
  onPreview: (width: number) => void;
  onCommit: (width: number) => void;
  onReset: () => void;
}

interface DragState {
  startX: number;
  startWidth: number;
  lastWidth: number;
}

/**
 * Focusable separator on a column header's right edge.
 * Pointer drag previews the width; pointer-up or a keyboard change commits it.
 */
export function ColumnResizeHandle({
  label,
  width,
  minWidth,
  maxWidth,
  onPreview,
  onCommit,
  onReset,
}: ColumnResizeHandleProps) {
  const dragRef = useRef<DragState | null>(null);
  const [active, setActive] = useState(false);

  const clamp = (value: number) =>
    Math.round(Math.min(maxWidth, Math.max(minWidth, value)));

  useEffect(() => {
    if (!active) return;
    const previousCursor = document.body.style.cursor;
    const previousSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousSelect;
    };
  }, [active]);

  function endDrag(revert: boolean) {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    setActive(false);
    if (revert) onPreview(drag.startWidth);
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    const step = event.shiftKey ? SHIFT_STEP : KEYBOARD_STEP;
    if (event.key === "ArrowLeft") {
      onCommit(clamp(width - step));
    } else if (event.key === "ArrowRight") {
      onCommit(clamp(width + step));
    } else if (event.key === "Home") {
      onCommit(minWidth);
    } else if (event.key === "End") {
      onCommit(maxWidth);
    } else if (event.key === "Enter") {
      onReset();
    } else {
      return;
    }
    event.preventDefault();
  }

  function handlePointerDown(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || !event.isPrimary) return;
    event.preventDefault();
    event.currentTarget.focus();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      startX: event.clientX,
      startWidth: width,
      lastWidth: width,
    };
    setActive(true);
  }

  function handlePointerMove(event: PointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    const next = clamp(drag.startWidth + event.clientX - drag.startX);
    drag.lastWidth = next;
    onPreview(next);
  }

  function handlePointerUp(event: PointerEvent<HTMLButtonElement>) {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    setActive(false);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (drag.lastWidth !== drag.startWidth) onCommit(drag.lastWidth);
  }

  return (
    <button
      type="button"
      // A focusable separator is the ARIA pattern for a column resizer.
      // eslint-disable-next-line jsx-a11y/no-interactive-element-to-noninteractive-role
      role="separator"
      aria-orientation="vertical"
      aria-label={`调整「${label}」列宽`}
      aria-valuenow={Math.round(width)}
      aria-valuemin={minWidth}
      aria-valuemax={maxWidth}
      aria-valuetext={`${Math.round(width)} 像素`}
      tabIndex={0}
      title="拖动调整列宽；双击或按 Enter 还原"
      data-column-resizer={label}
      className="col-resizer group/resizer absolute top-0 right-0 z-[1] flex h-full w-3 cursor-col-resize touch-none justify-end border-0 bg-transparent p-0 outline-none"
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => {
        event.preventDefault();
        onReset();
      }}
      onKeyDown={handleKeyDown}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={() => endDrag(true)}
      onLostPointerCapture={() => endDrag(true)}
    >
      <span
        aria-hidden="true"
        className={cn(
          "absolute top-2 right-[5px] bottom-2 w-0.5 rounded-full bg-line-strong transition-[width,background-color] duration-150",
          "group-hover/resizer:w-[3px] group-hover/resizer:bg-accent",
          "group-focus-visible/resizer:w-[3px] group-focus-visible/resizer:bg-accent",
          active && "w-[3px] bg-accent",
        )}
      />
    </button>
  );
}
