import * as Dialog from "@radix-ui/react-dialog";
import { FilePlus2, Pencil, X } from "lucide-react";
import { useMemo, useState } from "react";
import type {
  RuleCatalogEntry,
  WorkbenchDefinition,
  WorkbenchNode,
  WorkbenchTaskCreateRequest,
  WorkbenchTaskUpdateRequest,
} from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { Input, Select, Textarea } from "../../components/ui/Input";

function nodePaths(nodes: WorkbenchNode[]): Map<string, string> {
  const byId = new Map(nodes.map((node) => [node.node_id, node]));
  const paths = new Map<string, string>();
  function resolve(node: WorkbenchNode, seen: Set<string>): string {
    const cached = paths.get(node.node_id);
    if (cached) return cached;
    if (seen.has(node.node_id)) return node.name;
    seen.add(node.node_id);
    const parent = node.parent_id ? byId.get(node.parent_id) : null;
    const path = parent ? `${resolve(parent, seen)} / ${node.name}` : node.name;
    paths.set(node.node_id, path);
    return path;
  }
  for (const node of nodes) {
    if (node.node_type === "group") resolve(node, new Set());
  }
  return paths;
}

interface WorkbenchTaskDialogProps {
  open: boolean;
  nodes: WorkbenchNode[];
  rules: RuleCatalogEntry[];
  mode?: "create" | "edit";
  definition?: WorkbenchDefinition | null;
  initialParentId?: string | null;
  busy?: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: (values: WorkbenchTaskCreateRequest) => void;
  onSubmitUpdate?: (values: WorkbenchTaskUpdateRequest) => void;
}

export function WorkbenchTaskDialog({
  open,
  nodes,
  rules,
  mode = "create",
  definition = null,
  initialParentId = null,
  busy = false,
  error = "",
  onOpenChange,
  onSubmit,
  onSubmitUpdate,
}: WorkbenchTaskDialogProps) {
  const editing = mode === "edit" && definition !== null;
  const [name, setName] = useState("");
  const [inputUrl, setInputUrl] = useState(definition?.input_url ?? "");
  const [parentId, setParentId] = useState(initialParentId ?? "");
  const [taskType, setTaskType] = useState<"product" | "discovery">(
    definition?.task_type === "discovery" ? "discovery" : "product",
  );
  const [ruleKey, setRuleKey] = useState(
    definition ? `${definition.rule_id}@${definition.rule_version}` : "",
  );
  const [collectionMode, setCollectionMode] = useState<"sample" | "formal">(
    definition?.collection_mode === "formal" ? "formal" : "sample",
  );
  const [country, setCountry] = useState(definition?.country ?? "");
  const [language, setLanguage] = useState(definition?.language ?? "");
  const [market, setMarket] = useState(definition?.market ?? "");
  const [category, setCategory] = useState(definition?.category ?? "");
  const [maxUrls, setMaxUrls] = useState(String(definition?.limits?.max_urls ?? 100));
  const [maxProducts, setMaxProducts] = useState(
    String(definition?.limits?.max_products ?? 20),
  );
  const [maxSeconds, setMaxSeconds] = useState(
    String(definition?.limits?.max_seconds ?? 180),
  );
  const [maxAttempts, setMaxAttempts] = useState(
    String(definition?.limits?.max_attempts ?? 2),
  );
  const [proxy, setProxy] = useState(definition?.proxy ?? "");
  const [note, setNote] = useState(definition?.note ?? "");
  const [localError, setLocalError] = useState("");

  const paths = useMemo(() => nodePaths(nodes), [nodes]);
  const groups = nodes
    .filter((node) => node.node_type === "group")
    .sort((left, right) =>
      (paths.get(left.node_id) ?? left.name).localeCompare(
        paths.get(right.node_id) ?? right.name,
        "zh-CN",
      ),
    );
  const validRules = useMemo(
    () =>
      rules.filter(
        (rule) => rule.valid && rule.rule_id && rule.task_types.includes(taskType),
      ),
    [rules, taskType],
  );

  const selectedRule =
    validRules.find((rule) => `${rule.rule_id}@${rule.rule_version}` === ruleKey) ??
    validRules[0];

  function submit() {
    const url = inputUrl.trim();
    if (!editing && !url) {
      setLocalError("站点 URL 不能为空");
      return;
    }
    if (!selectedRule?.rule_id || !selectedRule.rule_version) {
      setLocalError("请选择可用的规则包");
      return;
    }
    if (!editing) {
      const parsedUrl = (() => {
        try {
          return new URL(/^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : `https://${url}`);
        } catch {
          return null;
        }
      })();
      if (!parsedUrl || !/^https?:$/.test(parsedUrl.protocol)) {
        setLocalError("请输入有效的 http(s) URL");
        return;
      }
    }
    const urls = Number(maxUrls);
    const products = Number(maxProducts);
    const seconds = Number(maxSeconds);
    const attempts = Number(maxAttempts);
    if (
      !Number.isFinite(urls) ||
      urls < 1 ||
      !Number.isFinite(products) ||
      products < 1 ||
      !Number.isFinite(seconds) ||
      seconds < 1 ||
      !Number.isFinite(attempts) ||
      attempts < 1
    ) {
      setLocalError("采集限制必须是大于 0 的数字");
      return;
    }
    setLocalError("");
    const common = {
      collection_mode: collectionMode,
      country: country.trim() || null,
      language: language.trim() || null,
      market: market.trim() || null,
      category: category.trim() || null,
      limits: {
        max_urls: urls,
        max_products: products,
        max_seconds: seconds,
        max_attempts: attempts,
      },
      proxy: proxy.trim() || null,
      note: note.trim() || null,
    } satisfies WorkbenchTaskUpdateRequest;
    const initialRuleKey = definition
      ? `${definition.rule_id}@${definition.rule_version}`
      : "";
    const ruleChanged =
      !definition || ruleKey !== initialRuleKey || taskType !== definition.task_type;
    const update: WorkbenchTaskUpdateRequest = ruleChanged
      ? {
          ...common,
          rule_id: selectedRule.rule_id,
          rule_version: selectedRule.rule_version,
          task_type: taskType,
        }
      : common;
    if (editing) {
      onSubmitUpdate?.(update);
      return;
    }
    const parsedUrl = new URL(
      /^[a-z][a-z0-9+.-]*:\/\//i.test(url) ? url : `https://${url}`,
    );
    onSubmit({
      ...update,
      rule_id: selectedRule.rule_id,
      rule_version: selectedRule.rule_version,
      task_type: taskType,
      name: name.trim() || null,
      input_url: parsedUrl.toString(),
      parent_id: parentId || null,
    });
  }

  return (
    <Dialog.Root open={open} onOpenChange={(next) => !busy && onOpenChange(next)}>
      <Dialog.Portal>
        <Dialog.Overlay className="animate-overlay-in fixed inset-0 z-50 bg-ink/35" />
        <Dialog.Content
          className="animate-dialog-in fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[min(720px,calc(100vw-24px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-overlay border border-line bg-surface shadow-overlay"
          onOpenAutoFocus={(event) => {
            event.preventDefault();
            document
              .getElementById(editing ? "workbench-task-rule" : "workbench-task-url")
              ?.focus();
          }}
        >
          <header className="flex items-start justify-between gap-4 border-b border-line px-4 py-4 sm:px-6">
            <div className="flex items-start gap-3">
              <span
                className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-accent"
                aria-hidden="true"
              >
                {editing ? <Pencil size={17} /> : <FilePlus2 size={17} />}
              </span>
              <div>
                <Dialog.Title className="text-[20px] leading-7 font-semibold tracking-[-0.01em] text-ink">
                  {editing ? "编辑任务定义" : "新建单个任务"}
                </Dialog.Title>
                <Dialog.Description className="mt-1 text-sm leading-6 text-ink-2">
                  {editing
                    ? "属性只对之后创建的运行生效；当前运行保持入队时的规则与限制。"
                    : "任务定义可以独立存在，不强制批次；目录只决定位置。"}
                </Dialog.Description>
              </div>
            </div>
            <Dialog.Close asChild>
              <button
                type="button"
                className="flex h-8 w-8 shrink-0 items-center justify-center rounded-control text-ink-3 hover:bg-surface-muted hover:text-ink"
                aria-label={editing ? "关闭编辑任务" : "关闭新建任务"}
                disabled={busy}
              >
                <X size={17} aria-hidden="true" />
              </button>
            </Dialog.Close>
          </header>

          <div className="space-y-5 px-4 py-5 sm:px-6">
            {error ? (
              <ErrorNotice
                title={editing ? "未能保存任务定义" : "未能创建任务"}
                message={error}
                compact
              />
            ) : null}
            {validRules.length === 0 ? (
              <ErrorNotice
                title="没有可用规则包"
                message={`当前规则目录没有支持${taskType === "discovery" ? "发现" : "商品"}任务的规则。请先在采集批次中完成接入或激活规则。`}
                compact
              />
            ) : null}
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-url"
                >
                  站点 URL {editing ? null : <span className="text-danger">*</span>}
                </label>
                <Input
                  id="workbench-task-url"
                  value={inputUrl}
                  placeholder="https://www.example.com/"
                  disabled={editing}
                  onChange={(event) => {
                    setInputUrl(event.target.value);
                    setLocalError("");
                  }}
                />
                {editing ? (
                  <p className="mt-1 text-[11px] text-ink-3">
                    站点身份与批次来源只读；需要换站点时请新建任务定义。
                  </p>
                ) : null}
              </div>
              {editing && definition ? (
                <div className="grid gap-2 rounded-panel border border-line bg-surface-muted p-3 text-[11px] sm:col-span-2 sm:grid-cols-2">
                  <p>
                    <span className="text-ink-3">站点 key：</span>
                    <code className="font-mono text-ink-2">{definition.site_key}</code>
                  </p>
                  <p>
                    <span className="text-ink-3">批次来源：</span>
                    <span className="text-ink-2">
                      {definition.batch_id || "独立任务"}
                    </span>
                  </p>
                </div>
              ) : (
                <>
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-ink-3"
                      htmlFor="workbench-task-name"
                    >
                      显示名称
                    </label>
                    <Input
                      id="workbench-task-name"
                      value={name}
                      maxLength={80}
                      placeholder="默认使用域名"
                      onChange={(event) => setName(event.target.value)}
                    />
                  </div>
                  <div>
                    <label
                      className="mb-1 block text-xs font-medium text-ink-3"
                      htmlFor="workbench-task-parent"
                    >
                      目标目录
                    </label>
                    <Select
                      id="workbench-task-parent"
                      value={parentId}
                      onChange={(event) => setParentId(event.target.value)}
                    >
                      <option value="">根目录</option>
                      {groups.map((group) => (
                        <option key={group.node_id} value={group.node_id}>
                          {paths.get(group.node_id) ?? group.name}
                        </option>
                      ))}
                    </Select>
                  </div>
                </>
              )}
              {editing ? (
                <div>
                  <label
                    className="mb-1 block text-xs font-medium text-ink-3"
                    htmlFor="workbench-task-type"
                  >
                    任务类型
                  </label>
                  <Select
                    id="workbench-task-type"
                    value={taskType}
                    onChange={(event) => {
                      setTaskType(event.target.value as "product" | "discovery");
                      setRuleKey("");
                    }}
                  >
                    <option value="product">商品</option>
                    <option value="discovery">发现</option>
                  </Select>
                </div>
              ) : null}
              <div className="sm:col-span-2">
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-rule"
                >
                  规则包 <span className="text-danger">*</span>
                </label>
                <Select
                  id="workbench-task-rule"
                  value={
                    ruleKey ||
                    (selectedRule
                      ? `${selectedRule.rule_id}@${selectedRule.rule_version}`
                      : "")
                  }
                  onChange={(event) => {
                    setRuleKey(event.target.value);
                    const rule = validRules.find(
                      (item) =>
                        `${item.rule_id}@${item.rule_version}` === event.target.value,
                    );
                    if (rule?.market && !market) setMarket(rule.market);
                  }}
                >
                  {validRules.map((rule) => (
                    <option
                      key={`${rule.rule_id}@${rule.rule_version}`}
                      value={`${rule.rule_id}@${rule.rule_version}`}
                    >
                      {rule.rule_id} · {rule.rule_version}
                      {rule.market ? ` · ${rule.market}` : ""}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-mode"
                >
                  采集模式
                </label>
                <Select
                  id="workbench-task-mode"
                  value={collectionMode}
                  onChange={(event) =>
                    setCollectionMode(event.target.value as "sample" | "formal")
                  }
                >
                  <option value="sample">试采</option>
                  <option value="formal">正式采集</option>
                </Select>
              </div>
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-market"
                >
                  市场
                </label>
                <Input
                  id="workbench-task-market"
                  value={market}
                  maxLength={20}
                  onChange={(event) => setMarket(event.target.value)}
                />
              </div>
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-country"
                >
                  国家
                </label>
                <Input
                  id="workbench-task-country"
                  value={country}
                  maxLength={20}
                  onChange={(event) => setCountry(event.target.value)}
                />
              </div>
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-language"
                >
                  语言
                </label>
                <Input
                  id="workbench-task-language"
                  value={language}
                  maxLength={20}
                  onChange={(event) => setLanguage(event.target.value)}
                />
              </div>
              <div className="sm:col-span-2">
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-category"
                >
                  品类
                </label>
                <Input
                  id="workbench-task-category"
                  value={category}
                  maxLength={40}
                  onChange={(event) => setCategory(event.target.value)}
                />
              </div>
            </div>

            <fieldset className="rounded-panel border border-line bg-surface-muted p-4">
              <legend className="px-1 text-xs font-medium text-ink-3">采集限制</legend>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {[
                  ["最大 URL", maxUrls, setMaxUrls],
                  ["最大商品", maxProducts, setMaxProducts],
                  ["最大秒数", maxSeconds, setMaxSeconds],
                  ["最大尝试", maxAttempts, setMaxAttempts],
                ].map(([label, value, setter]) => (
                  <label key={label as string} className="text-xs text-ink-3">
                    {label as string}
                    <Input
                      className="mt-1"
                      type="number"
                      min="1"
                      value={value as string}
                      onChange={(event) =>
                        (setter as (value: string) => void)(event.target.value)
                      }
                    />
                  </label>
                ))}
              </div>
            </fieldset>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-proxy"
                >
                  代理（可选）
                </label>
                <Input
                  id="workbench-task-proxy"
                  value={proxy}
                  maxLength={500}
                  placeholder="http://127.0.0.1:7890"
                  onChange={(event) => setProxy(event.target.value)}
                />
              </div>
              <div className="sm:col-span-2">
                <label
                  className="mb-1 block text-xs font-medium text-ink-3"
                  htmlFor="workbench-task-note"
                >
                  备注（可选）
                </label>
                <Textarea
                  id="workbench-task-note"
                  value={note}
                  rows={3}
                  maxLength={2000}
                  placeholder="只影响后续运行；不改变批次或导出归属。"
                  onChange={(event) => setNote(event.target.value)}
                />
              </div>
            </div>
            {localError ? <p className="text-xs text-danger">{localError}</p> : null}
          </div>

          <footer className="flex justify-end gap-2 border-t border-line px-4 py-3 sm:px-6">
            <Dialog.Close asChild>
              <Button disabled={busy}>取消</Button>
            </Dialog.Close>
            <Button
              variant="primary"
              onClick={submit}
              disabled={busy || validRules.length === 0}
            >
              {busy
                ? editing
                  ? "保存中…"
                  : "创建中…"
                : editing
                  ? "保存定义"
                  : "创建任务"}
            </Button>
          </footer>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
