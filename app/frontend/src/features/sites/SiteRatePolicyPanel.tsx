import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getSiteRatePolicy,
  setSiteRatePolicy,
  type SiteRatePolicy,
  type SiteRatePolicyResponse,
} from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { Input } from "../../components/ui/Input";

const FIELDS = [
  {
    key: "per_domain_rps",
    label: "每域请求上限（RPS）",
    hint: "0.1–10；留空继承服务默认",
    integer: false,
  },
  {
    key: "concurrency",
    label: "单任务并发",
    hint: "1–8；留空继承规则／服务默认",
    integer: true,
  },
  {
    key: "delay_ms",
    label: "额外请求间隔（ms）",
    hint: "0–10000；在当前限速之外增加固定等待",
    integer: true,
  },
  {
    key: "max_attempts",
    label: "最大尝试次数",
    hint: "1–5；包含第一次请求",
    integer: true,
  },
  {
    key: "backoff_ms",
    label: "退避基数（ms）",
    hint: "0–60000；429／5xx 按指数退避",
    integer: true,
  },
] as const;

type FieldKey = (typeof FIELDS)[number]["key"];
type Draft = Record<FieldKey, string>;

function initialDraft(policy: Partial<SiteRatePolicy> | undefined): Draft {
  return Object.fromEntries(
    FIELDS.map((field) => [
      field.key,
      policy?.[field.key] === null || policy?.[field.key] === undefined
        ? ""
        : String(policy[field.key]),
    ]),
  ) as Draft;
}

function parseDraft(draft: Draft): { policy: Partial<SiteRatePolicy>; error: string } {
  const policy: Partial<SiteRatePolicy> = {};
  for (const field of FIELDS) {
    const raw = draft[field.key].trim();
    if (!raw) continue;
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      return { policy: {}, error: `${field.label}必须是数字。` };
    }
    if (field.integer && !Number.isInteger(value)) {
      return { policy: {}, error: `${field.label}必须是整数。` };
    }
    if (field.key === "per_domain_rps" && (value < 0.1 || value > 10)) {
      return { policy: {}, error: `${field.label}必须在 0.1–10 之间。` };
    }
    if (field.key === "concurrency" && (value < 1 || value > 8)) {
      return { policy: {}, error: `${field.label}必须在 1–8 之间。` };
    }
    if (field.key === "delay_ms" && (value < 0 || value > 10000)) {
      return { policy: {}, error: `${field.label}必须在 0–10000 之间。` };
    }
    if (field.key === "max_attempts" && (value < 1 || value > 5)) {
      return { policy: {}, error: `${field.label}必须在 1–5 之间。` };
    }
    if (field.key === "backoff_ms" && (value < 0 || value > 60000)) {
      return { policy: {}, error: `${field.label}必须在 0–60000 之间。` };
    }
    policy[field.key] = value;
  }
  return { policy, error: "" };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function SiteRatePolicyPanel({
  batchId,
  siteKey,
}: {
  batchId: string;
  siteKey: string;
}) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["site-rate-policy", batchId, siteKey],
    queryFn: ({ signal }) => getSiteRatePolicy(batchId, siteKey, signal),
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState("");
  const save = useMutation({
    mutationFn: (policy: Partial<SiteRatePolicy>) =>
      setSiteRatePolicy(batchId, siteKey, policy),
    onSuccess: (data: SiteRatePolicyResponse) => {
      queryClient.setQueryData(["site-rate-policy", batchId, siteKey], data);
      setDraft(null);
      setDirty(false);
      setNotice("已自动保存；对下一次任务生效。");
    },
  });
  const {
    mutate: savePolicy,
    isPending: saving,
    isError: saveFailed,
    reset: resetSave,
  } = save;
  const currentDraft = draft ?? (query.data ? initialDraft(query.data.policy) : null);
  const parsed = currentDraft
    ? parseDraft(currentDraft)
    : { policy: {} as Partial<SiteRatePolicy>, error: "" };

  useEffect(() => {
    if (!dirty || !currentDraft || saving || saveFailed) return;
    const next = parseDraft(currentDraft);
    if (next.error) return;
    const timer = window.setTimeout(() => savePolicy(next.policy), 800);
    return () => window.clearTimeout(timer);
  }, [dirty, currentDraft, saving, saveFailed, savePolicy]);

  function saveNow() {
    if (!currentDraft || saving) return;
    const next = parseDraft(currentDraft);
    if (next.error) return;
    savePolicy(next.policy);
  }

  function change(key: FieldKey, value: string) {
    setDraft((current) => {
      const base = current ?? (query.data ? initialDraft(query.data.policy) : null);
      return base ? { ...base, [key]: value } : null;
    });
    setDirty(true);
    setNotice("");
    resetSave();
  }

  if (query.isPending) {
    return (
      <section className="rounded-panel border border-line bg-surface px-4 py-4 sm:px-6">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">采集速率</h2>
        <p className="mt-2 text-sm text-ink-2" role="status">
          正在读取站点速率策略…
        </p>
      </section>
    );
  }
  if (query.isError || !query.data || !currentDraft) {
    return (
      <section className="rounded-panel border border-line bg-surface px-4 py-4 sm:px-6">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">采集速率</h2>
        <p className="mt-2 text-sm text-danger" role="alert">
          读取速率策略失败：{errorText(query.error)}
        </p>
      </section>
    );
  }

  const defaults = query.data.defaults;
  const effective = query.data.effective;
  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="border-b border-line px-4 py-4 sm:px-6">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">采集速率</h2>
        <p className="mt-1 text-sm leading-6 text-ink-2">
          只对下一次任务生效；正在运行或暂停的任务保持原计划。留空表示继承默认值。
        </p>
      </div>
      <div className="grid gap-3 px-4 py-4 sm:grid-cols-2 sm:px-6">
        {FIELDS.map((field) => (
          <label key={field.key} className="space-y-1 text-sm text-ink-2">
            <span className="font-medium text-ink">{field.label}</span>
            <Input
              inputMode={field.integer ? "numeric" : "decimal"}
              value={currentDraft[field.key]}
              placeholder={`继承 ${String(defaults[field.key])}`}
              onChange={(event) => change(field.key, event.target.value)}
              onBlur={saveNow}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  saveNow();
                }
              }}
            />
            <span className="block text-[11px] leading-4 text-ink-3">{field.hint}</span>
          </label>
        ))}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line px-4 py-3 sm:px-6">
        <p className="text-xs leading-5 text-ink-3">
          当前生效（新任务）：RPS {effective.per_domain_rps} · 并发{" "}
          {effective.concurrency} · 间隔 {effective.delay_ms}ms · 尝试{" "}
          {effective.max_attempts} · 退避 {effective.backoff_ms}ms
        </p>
        <div className="flex items-center gap-2">
          <Button
            size="sm"
            onClick={() => {
              setDraft(initialDraft({}));
              setDirty(true);
              resetSave();
            }}
          >
            恢复继承
          </Button>
          <Button size="sm" variant="primary" disabled={saving} onClick={saveNow}>
            {saving ? "保存中…" : "立即保存"}
          </Button>
        </div>
      </div>
      {parsed.error || saveFailed ? (
        <p className="px-4 pb-3 text-sm text-danger sm:px-6" role="alert">
          {parsed.error || errorText(save.error)}
        </p>
      ) : null}
      {notice ? (
        <p className="px-4 pb-3 text-sm text-success sm:px-6" role="status">
          {notice}
        </p>
      ) : null}
    </section>
  );
}
