# Tognar crash recovery

## 目的与边界

用真实站点验证 R06 的单 worker 崩溃恢复：任务运行中强制终止 worker 子进程，保留 `RUNNING` 状态和一个 `IN_FLIGHT` 工作项；再启动新 worker，确认任务被自动重排、`IN_FLIGHT` 被对账，最终完成 30 个 URL。

这是进程级强杀演练，不是断电、磁盘损坏或多进程租约测试。

## 规则与任务

- 规则：`../plans/tognar-next-link-runtime.yaml`；
- 任务：`tognar-crash-recovery`，discovery，`next_link`，3 页 / 30 URL；
- 同域间隔 0.1 rps（10 秒）；
- 第 5 秒终止 worker 子进程。

## 结果

- 强杀后：任务仍为 `RUNNING`；导航 1 个 `DONE`、1 个 `IN_FLIGHT`；商品 12 个 `DONE`。
- 新 worker 启动时自动把该 `RUNNING` 任务重排为 `QUEUED`，`TaskRunner` 对账 `IN_FLIGHT`：
  - `in_flight=1`
  - `reset=1`
  - `failed=0`
- 恢复后继续第 2、3 页：导航 3 个 `DONE`、商品 30 个 `DONE`，最终 `FINISHED`／`COMPLETED`。
- 任务结果中的 `recovery` 字段与 `worker-recovery.log` 保留了对账证据。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python -X utf8 experiments/r06/tools/crash_smoke.py `
  --rule experiments/r06/plans/tognar-next-link-runtime.yaml `
  --demo-dir experiments/r06/tognar-crash-demo `
  --task-id tognar-crash-rerun --kill-after 5 `
  --per-domain-rps 0.1 --max-urls 30 --timeout 240
```

任务 ID 不能重复；复跑时换 `--task-id`，或删除本次 demo 目录后重跑。

## 限制

- 只验证同一台机器、单 worker 进程；没有多进程租约，两个 worker 同时启动时可能重复接管同一任务。
- 只验证 `kill` 强杀，不验证断电、SQLite 文件损坏、磁盘写满或网络半包。
- 只验证 discovery 任务；product 任务和商品文件原子写未在真实强杀中演练。
- 恢复依赖 SQLite WAL 和启动时 `recover_orphaned_tasks()`；多进程 worker 接入前需要重新设计租约和归属判断。
- 不验证限速器的跨进程共享或 Web UI 恢复入口。
