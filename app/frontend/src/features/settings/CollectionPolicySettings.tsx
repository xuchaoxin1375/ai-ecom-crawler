import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { useState } from "react";
import {
  getCollectionPolicy,
  setCollectionPolicy,
  type CollectionPolicy,
  type CollectionPolicyResponse,
} from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { Checkbox, Input } from "../../components/ui/Input";

interface Draft {
  formal_unlimited: boolean;
  formal_max_products: string;
  formal_max_seconds: string;
  default_per_domain_rps: string;
  default_concurrency: string;
}

function initialDraft(policy: CollectionPolicy): Draft {
  return {
    formal_unlimited: policy.formal_unlimited,
    formal_max_products: String(policy.formal_max_products),
    formal_max_seconds: String(policy.formal_max_seconds),
    default_per_domain_rps:
      policy.default_per_domain_rps === null
        ? ""
        : String(policy.default_per_domain_rps),
    default_concurrency:
      policy.default_concurrency === null ? "" : String(policy.default_concurrency),
  };
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function parseDraft(
  draft: Draft,
  fallback: CollectionPolicy,
): { policy: CollectionPolicy; error: string } {
  const products = draft.formal_max_products.trim()
    ? Number(draft.formal_max_products)
    : fallback.formal_max_products;
  const seconds = draft.formal_max_seconds.trim()
    ? Number(draft.formal_max_seconds)
    : fallback.formal_max_seconds;
  const rps = draft.default_per_domain_rps.trim()
    ? Number(draft.default_per_domain_rps)
    : null;
  const concurrency = draft.default_concurrency.trim()
    ? Number(draft.default_concurrency)
    : null;
  if (!Number.isInteger(products) || products < 1 || products > 100000) {
    return {
      policy: fallback,
      error: "正式采集商品上限必须是 1–100000 的整数。",
    };
  }
  if (!Number.isInteger(seconds) || seconds < 60 || seconds > 86400) {
    return {
      policy: fallback,
      error: "正式采集时长上限必须是 60–86400 秒的整数。",
    };
  }
  if (rps !== null && (!Number.isFinite(rps) || rps < 0.1 || rps > 10)) {
    return {
      policy: fallback,
      error: "默认每域 RPS 必须是 0.1–10，留空表示继承。",
    };
  }
  if (
    concurrency !== null &&
    (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 8)
  ) {
    return {
      policy: fallback,
      error: "默认并发必须是 1–8 的整数，留空表示继承。",
    };
  }
  return {
    policy: {
      formal_unlimited: draft.formal_unlimited,
      formal_max_products: products,
      formal_max_seconds: seconds,
      default_per_domain_rps: rps,
      default_concurrency: concurrency,
    },
    error: "",
  };
}

export function CollectionPolicySettings() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["collection-policy"],
    queryFn: ({ signal }) => getCollectionPolicy(signal),
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [notice, setNotice] = useState("");
  const save = useMutation({
    mutationFn: (policy: CollectionPolicy) => setCollectionPolicy(policy),
    onSuccess: (data: CollectionPolicyResponse) => {
      queryClient.setQueryData(["collection-policy"], data);
      setDraft(null);
      setNotice("已保存；对之后创建的任务生效，不需要重启。");
    },
  });
  const { mutate: savePolicy, isPending, isError, error, reset } = save;
  const currentDraft = draft ?? (query.data ? initialDraft(query.data.policy) : null);

  if (query.isPending) {
    return (
      <section className="rounded-panel border border-line bg-surface px-4 py-4 sm:px-6">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">采集计划与速率</h2>
        <p className="mt-2 text-sm text-ink-2" role="status">
          正在读取采集计划…
        </p>
      </section>
    );
  }
  if (query.isError || !query.data || !currentDraft) {
    return (
      <section className="rounded-panel border border-line bg-surface px-4 py-4 sm:px-6">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">采集计划与速率</h2>
        <p className="mt-2 text-sm text-danger" role="alert">
          读取采集计划失败：{errorText(query.error)}
        </p>
      </section>
    );
  }

  const parsed = parseDraft(currentDraft, query.data.policy);
  const disabled = currentDraft.formal_unlimited;
  const sitePolicies = query.data.site_policies;

  function change<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => {
      const base = current ?? (query.data ? initialDraft(query.data.policy) : null);
      return base ? { ...base, [key]: value } : null;
    });
    setNotice("");
    reset();
  }

  return (
    <section className="rounded-panel border border-line bg-surface">
      <div className="border-b border-line px-4 py-4 sm:px-6">
        <h2 className="text-[17px] leading-6 font-semibold text-ink">采集计划与速率</h2>
        <p className="mt-1 text-sm leading-6 text-ink-2">
          正式采集默认由规则和目录自然结束；这里设置服务层默认上限和没有站点级覆盖时的默认速率。站点级策略优先。
        </p>
      </div>
      <div className="grid gap-4 px-4 py-4 sm:px-6 lg:grid-cols-2">
        <div className="space-y-3">
          <div className="flex items-start gap-3 text-sm text-ink-2">
            <Checkbox
              id="collection-policy-unlimited"
              className="mt-0.5"
              checked={currentDraft.formal_unlimited}
              onChange={(event) => change("formal_unlimited", event.target.checked)}
            />
            <label htmlFor="collection-policy-unlimited" className="min-w-0">
              <span className="block font-medium text-ink">
                正式采集默认不设商品数或时长上限
              </span>
              <span className="block text-xs leading-5 text-ink-3">
                关闭后使用下面的商品数和时长上限；单次运行仍可通过 API 显式 limits
                覆盖。
              </span>
            </label>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1 text-sm text-ink-2">
              <label
                className="font-medium text-ink"
                htmlFor="collection-policy-products"
              >
                商品上限
              </label>
              <Input
                id="collection-policy-products"
                inputMode="numeric"
                disabled={disabled}
                value={currentDraft.formal_max_products}
                onChange={(event) => change("formal_max_products", event.target.value)}
              />
            </div>
            <div className="space-y-1 text-sm text-ink-2">
              <label
                className="font-medium text-ink"
                htmlFor="collection-policy-seconds"
              >
                时长上限（秒）
              </label>
              <Input
                id="collection-policy-seconds"
                inputMode="numeric"
                disabled={disabled}
                value={currentDraft.formal_max_seconds}
                onChange={(event) => change("formal_max_seconds", event.target.value)}
              />
            </div>
          </div>
        </div>
        <div className="space-y-3">
          <p className="text-sm font-medium text-ink">默认站点速率</p>
          <p className="text-xs leading-5 text-ink-3">
            只用于没有站点级覆盖的域名；留空继承规则／服务默认。只影响之后创建的任务。
          </p>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1 text-sm text-ink-2">
              <label className="font-medium text-ink" htmlFor="collection-policy-rps">
                每域 RPS
              </label>
              <Input
                id="collection-policy-rps"
                inputMode="decimal"
                placeholder="继承"
                value={currentDraft.default_per_domain_rps}
                onChange={(event) =>
                  change("default_per_domain_rps", event.target.value)
                }
              />
            </div>
            <div className="space-y-1 text-sm text-ink-2">
              <label
                className="font-medium text-ink"
                htmlFor="collection-policy-concurrency"
              >
                单任务并发
              </label>
              <Input
                id="collection-policy-concurrency"
                inputMode="numeric"
                placeholder="继承"
                value={currentDraft.default_concurrency}
                onChange={(event) => change("default_concurrency", event.target.value)}
              />
            </div>
          </div>
        </div>
      </div>
      <div className="border-t border-line px-4 py-4 sm:px-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs leading-5 text-ink-3">
            当前正式上限：{query.data.formal_limits.max_products ?? "不限"} 件 ·{" "}
            {query.data.formal_limits.max_seconds ?? "不限"} 秒
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              className="text-xs font-medium text-accent hover:underline"
              to="/batches"
            >
              去批次列表设置站点速率
            </Link>
            <span className="text-xs text-ink-3">
              {sitePolicies.length
                ? `已保存 ${sitePolicies.length} 个站点策略`
                : "暂无站点级覆盖"}
            </span>
            <Button
              size="sm"
              variant="primary"
              disabled={isPending || Boolean(parsed.error)}
              onClick={() => savePolicy(parsed.policy)}
            >
              {isPending ? "保存中…" : "保存采集计划"}
            </Button>
          </div>
        </div>
        {sitePolicies.length ? (
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-3">
            {sitePolicies.slice(0, 8).map((item) => (
              <li key={item.domain}>
                <code className="font-mono">{item.domain}</code>：RPS{" "}
                {item.per_domain_rps ?? "继承"} · 并发 {item.concurrency ?? "继承"}
              </li>
            ))}
            {sitePolicies.length > 8 ? <li>…</li> : null}
          </ul>
        ) : null}
        {parsed.error ? (
          <p className="mt-2 text-sm text-danger" role="alert">
            {parsed.error}
          </p>
        ) : null}
        {isError ? (
          <p className="mt-2 text-sm text-danger" role="alert">
            {errorText(error)}
          </p>
        ) : null}
        {notice ? (
          <p className="mt-2 text-sm text-success" role="status">
            {notice}
          </p>
        ) : null}
      </div>
    </section>
  );
}
