# Tognar budget stop

## 目的与边界

用真实站点验证任务级 `max_seconds` 预算停止：同一 `next_link` 规则包分别设 6 秒和 12 秒预算，确认任务按 `BUDGET_EXHAUSTED` 结束并标为 `PARTIAL`，而不是把未完成样本写成自然完成。

只做 URL 发现，不请求商品页。

## 任务与结果

### 6 秒预算

- 任务：`tognar-budget-early`，`max_seconds=6`。
- 请求：第 1、2 页；第 3 页已排入导航队列但未处理。
- 输出：24 个唯一商品 URL，3 个导航项（1 个未处理）。
- 结果：`FINISHED`／`PARTIAL`，`stop_reason=BUDGET_EXHAUSTED`。

### 12 秒预算

- 任务：`tognar-budget-stop`，`max_seconds=12`。
- 请求：第 1、2、3 页；第 3 页完成后预算检查触发停止。
- 输出：30 个唯一商品 URL。
- 结果：`FINISHED`／`PARTIAL`，`stop_reason=BUDGET_EXHAUSTED`。

12 秒任务虽然达到了 30 URL 的样本上限，但预算在任务边界耗尽，仍标 `PARTIAL`；这不是 30 URL 等于全量或自然完成的证据。

## 复现

```powershell
$py = @('-m','uv','run','--project','experiments/framework-compare/scrapling','--with','pyyaml==6.0.3','python')
& python @py experiments/r06/runtime_cli.py task create `
  --db experiments/r06/tognar-budget-demo/tasks.db `
  --rule experiments/r06/plans/tognar-next-link-runtime.yaml `
  --task-type discovery --task-id tognar-budget-rerun-6 `
  --out-root experiments/r06/tognar-budget-demo/tasks --max-urls 30 --max-seconds 6 --start
& python @py experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/tognar-budget-demo/tasks.db `
  --out-root experiments/r06/tognar-budget-demo/tasks --max-tasks 1 --per-domain-rps 0.1
```

12 秒任务使用同一命令，把 `--task-id` 和 `--max-seconds` 改为 `tognar-budget-rerun-12`／`12`。

## 限制

- 预算在工作项边界检查，不强行中断已经开始或正在排队的请求；因此 6 秒任务仍可能完成第 2 页。
- 只验证 discovery；product 任务的预算停止未单独演练。
- 只验证一个站点和两个预算值；不证明所有站点的耗时分布。
- 不读取 robots；10 秒间隔来自该站既有 `Crawl-delay` 观察。
