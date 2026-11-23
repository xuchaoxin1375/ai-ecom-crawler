import { formatNumber } from "../../lib/format";
import type { InlineNoticeTone } from "../../components/ui/InlineNotice";

export interface BulkNotice {
  tone: InlineNoticeTone;
  title: string;
  text: string;
  details?: string[];
}

export function noticeFor(
  title: string,
  succeeded: number,
  failed: string[],
): BulkNotice {
  return {
    tone: failed.length === 0 ? "success" : succeeded > 0 ? "warning" : "danger",
    title,
    text: `完成 ${formatNumber(succeeded)} 个${
      failed.length ? `，失败 ${formatNumber(failed.length)} 个` : ""
    }。`,
    details: failed.slice(0, 3),
  };
}
