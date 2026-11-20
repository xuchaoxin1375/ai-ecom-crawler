# Runtime v0 demo

两个任务共用 `../plans/familidoo-runtime.yaml`，由 `../runtime_cli.py` 写入 `tasks.db`，再由 `worker run --max-tasks 2` 并行执行。

| 任务 | 类型 | 结果 | 请求 | 起止（UTC） |
| --- | --- | --- | --- | --- |
| `demo-discovery` | discovery | 6 个 URL，`COMPLETED` | 2（robots＋入口） | 12:26:20–12:26:24 |
| `demo-product` | product | 6 个商品，`COMPLETED` | 8（robots＋入口＋6 商品） | 12:26:20–12:26:38 |

两个任务同一秒启动；同域请求由 1 rps 限速器串行，输出目录和计数互不污染。discovery 没有请求商品页。

## 复现

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/runtime-demo/tasks.db `
  --rule experiments/r06/plans/familidoo-runtime.yaml `
  --task-type discovery --task-id demo-discovery `
  --out-root experiments/r06/runtime-demo/tasks --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/runtime-demo/tasks.db `
  --rule experiments/r06/plans/familidoo-runtime.yaml `
  --task-type product --task-id demo-product `
  --out-root experiments/r06/runtime-demo/tasks --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/runtime-demo/tasks.db `
  --out-root experiments/r06/runtime-demo/tasks `
  --max-tasks 2 --per-domain-rps 1
```

校验：

```powershell
python experiments/r06/tools/validate_runtime.py --root experiments/r06/runtime-demo
```

## 边界

这是单站、单入口、静态 HTML 的原型；`tasks.db` 是本地任务账本，包含任务状态和工作项，不包含整页 HTML。任务记录和 `task-result.json` 输出 `plan_*`；失败分类、重试上限、原子写和逻辑对账由无网络测试覆盖。真实站点的暂停／取消、跨进程和进程崩溃恢复仍未做。
