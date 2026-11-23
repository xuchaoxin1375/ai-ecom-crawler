import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Circle,
  FileUp,
  PauseCircle,
  RotateCcw,
} from "lucide-react";
import { Button } from "../../components/ui/Button";
import { cn } from "../../lib/cn";
import type { NextStep } from "./detail";

const toneClasses: Record<NextStep["tone"], string> = {
  neutral: "border-line bg-surface-muted text-ink-3",
  success: "border-success/20 bg-success-soft text-success",
  warning: "border-warning/25 bg-warning-soft text-warning",
  danger: "border-danger/25 bg-danger-soft text-danger",
  info: "border-info/20 bg-info-soft text-info",
};

function StepIcon({ step }: { step: NextStep }) {
  const props = { size: 18, strokeWidth: 1.75, "aria-hidden": true } as const;
  if (step.tone === "success") return <CheckCircle2 {...props} />;
  if (step.tone === "warning") return <AlertTriangle {...props} />;
  if (step.action.kind === "pause") return <PauseCircle {...props} />;
  if (step.action.kind === "restore") return <RotateCcw {...props} />;
  if (step.action.kind === "import") return <FileUp {...props} />;
  if (step.action.kind === "start") return <ArrowRight {...props} />;
  return <Circle {...props} />;
}

interface BatchNextStepProps {
  step: NextStep;
  onAction: () => void;
  disabled?: boolean;
  busy?: boolean;
}

export function BatchNextStep({
  step,
  onAction,
  disabled = false,
  busy = false,
}: BatchNextStepProps) {
  return (
    <section
      className={cn("rounded-panel border px-4 py-4", toneClasses[step.tone])}
      aria-labelledby="batch-next-step-title"
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-0.5 shrink-0">
          <StepIcon step={step} />
        </span>
        <div className="min-w-0">
          <h2
            id="batch-next-step-title"
            className="text-[15px] leading-6 font-semibold text-ink"
          >
            下一步
          </h2>
          <p className="mt-1 text-sm leading-6 font-medium text-ink">{step.title}</p>
          <p className="mt-1 text-xs leading-5 text-ink-2">{step.description}</p>
        </div>
      </div>
      {step.action.kind !== "none" && step.actionLabel ? (
        <Button
          className="mt-3 w-full"
          size="sm"
          variant="secondary"
          onClick={onAction}
          disabled={disabled || busy}
        >
          {busy ? "处理中…" : step.actionLabel}
          {step.action.kind === "export" ? (
            <ArrowRight size={13} aria-hidden="true" />
          ) : null}
        </Button>
      ) : null}
    </section>
  );
}
