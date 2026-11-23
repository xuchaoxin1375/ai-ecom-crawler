import type { BatchStatus } from "../../lib/api";
import { BATCH_STATUS_LABELS, batchStatusTone } from "../../lib/format";
import { Badge } from "./Badge";

export function BatchStatusBadge({ status }: { status: BatchStatus }) {
  return <Badge tone={batchStatusTone(status)}>{BATCH_STATUS_LABELS[status]}</Badge>;
}
