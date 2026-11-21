# D07 可靠性缺口评估

## 目的与边界

对照 `docs/05` 的 A12／A13／A15／A20 和 `docs/09` 的状态、计数、取消语义，盘点当前实现的可靠性证据与缺口。D07 的生产目标需要 `app/` 执行器和任务账本；当前已有 R06 原型、D02 导出层、D04 v0 执行器和本轮补的单 worker 控制面，所以本页仍是**缺口评估 + 已修正的字段分类 + 控制面证据**，不是 D07 完成声明。

## 证据盘点

| 领域 | 已有证据 | 状态 | 缺口 |
| --- | --- | --- | --- |
| A12 访问与重试 | R06 `RetryTests`（transient 重试、耗尽、blocked 分类）、`RobotsTests`；D01 S6 挑战页；A08 429／Chrome 指纹；D06 JSON／HTML 路径 | 部分 | 无浏览器会话复用自动化；无统一 429 `Retry-After` 处理；无代理／出口资源登记 |
| A13 暂停／取消／恢复 | R06 `ControlTests`（暂停恢复、取消拒收迟到结果）、`RecoveryTests`（在途重置、尝试耗尽、孤儿状态、plan 版本不匹配）；Tognar 真实暂停／取消／强杀恢复；`app/tests/test_control.py`（状态转移、恢复对账、worker 单实例锁）、`test_control_flow.py`（暂停结清、恢复、取消拒收迟到结果、心跳续约、双 worker 单任务、过期接管）、`test_lease.py`（跨进程领取、旧写拒绝） | 原型 + `app` 单机跨进程租约通过 | 真实浏览器会话恢复；真实进程强杀接管；跨机租约 |
| A15 漂移与修复 | A08 两轮方案修订（入口前缀、正文／分类／选项）；D03／D04 同方案复跑；R06 提取缺失值测试 | 部分 | 没有自动化漂移检测／修复；没有旧结果失效标记；分类问题本轮修正 |
| A20 多任务并行 | R06 `ParallelTests`；`app/tests/test_control_flow.py` 的 `test_a20_pause_*`／`test_a20_cancel_*`：同域两任务并行，暂停／取消一个，另一个继续并输出独立；`test_two_workers_process_one_task_once` 验证两个 worker 不重复领取；`test_same_domain_limiter_serializes` 验证同域限速 | 通过（同进程 + 单机双进程） | 无跨进程资源配额和浏览器实例配额；同域限速仍是进程内 |
| 原子写与幂等 | R06 `AtomicTests`、`StoreTests`；D02 app 原子写和幂等键；租约接管时丢弃未确认的商品输出尾行 | 通过（单机多进程） | 跨机幂等和真实浏览器输出未验证 |
| 资源回收 | R06 `resources` 字段、无浏览器路径；D02 无外部资源；`app` 取消后无 `IN_FLIGHT`、无临时文件残留，`run_forever` 停止时 join 运行线程；`task_resources` 登记进程／目录并按租约令牌回收 | 部分 | 浏览器 adapter 未接入；真实浏览器 profile／进程回收未验证 |

## 本轮修正：字段错误不再被当成业务排除

R06 原先把所有 `validate_product` 原因都映射为 `EXCLUDED`。这会掩盖选择器漂移：价格字段缺失、名称缺失或币种错误会被写成业务排除，而不是技术失败。

按 `docs/09` 改为：

- `zero_or_missing_price` → `EXCLUDED`（业务排除，保留原因）。
- 其他字段错误（`missing_name`、`missing_primary_image_url`、`missing_source_url`、`invalid_currency` 等）→ `FAILED`，`failure_class=permanent`，`reason=validation_error`，并保留 `reasons` 数组。

新增测试：

- `test_missing_name_is_failed_not_excluded`：缺名称 → `failed_products=1`、`excluded_products=0`、`outcome=FAILED`。
- `test_zero_price_is_excluded_not_failed`：零价 → `excluded_products=1`、`failed_products=0`、`outcome=COMPLETED`。

这与 D02 app 的归类一致：价格问题进排除流，字段／来源问题进失败流。

## 2026-11-21 app 单 worker 控制面

`app` 新增 `submit`／`worker`／`pause`／`resume`／`cancel`／`status`／`list`：

- `submit` 创建 `QUEUED` 任务但不执行；`worker` 常驻领取 `QUEUED`，默认 `max_tasks=1`。
- `pause` 只接受 `RUNNING` → `PAUSING`，runner 等在途结清后写 `PAUSED`。
- `cancel` 把 `RUNNING`／`PAUSING` → `CANCELLING`，runner 等在途结束后拒收迟到结果并写 `CANCELLED`；`DRAFT`／`QUEUED`／`PAUSED` 直接 `CANCELLED`。
- `resume` 只接受 `PAUSED` → `QUEUED`；重复控制请求幂等，非法转移返回 2。
- 启动时 `recover_orphaned_tasks()` 对账：`RUNNING` → `QUEUED`，`PAUSING` → `PAUSED`，`CANCELLING` → `CANCELLED`。
- 跨进程 `submit` → `status` → `cancel` 冒烟通过（独立 Python 进程共享同一 SQLite）；跨进程 `worker` 的暂停／恢复仍未做自动化。

测试：`app/tests/test_control.py`（10 个转移／恢复／锁用例）和 `app/tests/test_control_flow.py`（当时 8 个流程／A20／CLI 用例）；当时 `app` 总计 88 个测试通过（含 9 个 D08 Web API 用例），`ruff check app` 通过。租约补入后的当前测试数见下文“测试结果”。

## 2026-11-21 单机跨进程租约与资源回收

`app` 在 SQLite 账本上补了任务级租约，默认单 worker／单实例锁不变；需要多个 worker 进程时加 `--allow-multi-worker`。

- 领取：`TaskStore.claim_tasks` 在 `BEGIN IMMEDIATE` 中把 `QUEUED` 改为 `RUNNING`，写入 `lease_owner`、递增 `lease_token`、写入到期和心跳时间；同一任务只会被一个 worker 领到。
- 续约：worker 心跳线程默认每 `min(5, ttl/3)` 秒调用 `renew_lease`；租约过期后不能再续期，必须由对账重新排队。
- 回收：`settle_expired_tasks` 只处理租约缺失或过期的任务；`RUNNING` 回 `QUEUED` 并重置在途项，`PAUSING` 结清为 `PAUSED`，`CANCELLING` 结清为 `CANCELLED`。
- 防旧写：`update_task`、`add_item`、`claim_items`、`mark_item` 和 `reconcile_task` 支持同一事务内的租约校验；旧持有者写入得到 `LeaseLostError`。
- 输出一致性：接管启动时按账本 `DONE` 工作项过滤 `products.jsonl`，丢弃旧持有者未确认的尾行。
- 资源回收：`task_resources` 保存任务子进程 PID 和目录，`runtime.resources` 在结束、取消和过期接管时回收；按 `lease_token` 过滤，旧持有者不能删除新持有者的资源。

测试与证据：

- `app/tests/test_lease.py`：双线程／双进程领取唯一性、过期接管、旧写拒绝、心跳过期不可复活、`PAUSING`／`CANCELLING` 结清、旧库迁移。
- `app/tests/test_control_flow.py`：心跳保活、两个 worker 单任务只处理一次、过期任务接管后完成。
- `app/tests/test_resources.py`：子进程终止、目录删除和租约令牌隔离。
- `experiments/d07/lease/multiprocess_demo.py`：本机两个独立 worker 进程共享账本，2 个任务各 2 个商品，`lease_token=1` 且结束后 `lease_owner` 已清空；运行方式见脚本头部。
- WSL2 Ubuntu + Python 3.12.3：`test_lease.py` 7 个用例、`test_resources.py` 3 个用例通过；Linux 僵尸进程按 `/proc/<pid>/stat` 判死，避免把已终止子进程当成仍在运行。

## 测试结果

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" --with "jsonschema>=4.23" `
  python -m unittest discover -s experiments/r06/tests -v
```

结果：**83 个测试通过**，无 skip。覆盖原子写、契约、提取、运行时、重试、恢复、控制、并行、Schema 和新的字段分类。`app` 当前 **106 个测试通过**，含租约、资源回收、控制流和 Web API。

## D07 结论

- **不是 D07 完成**：生产 `app` 执行器、任务账本、控制面、单实例锁、同进程 A20、单机跨进程租约和进程／目录资源回收已落地；真实浏览器 adapter 回收、跨进程资源配额、真实进程强杀接管、跨机租约和自动化漂移修复仍未实现。
- **可复用的改进**：字段错误与业务排除的分类已修正，并进入 R06 回归测试；`app` 控制面复用同一状态语义；租约和资源登记不改变对外任务状态。
- **下一步优先级**：接浏览器 adapter 时把子进程和 profile 目录登记到 `task_resources`，再补跨进程资源配额和真实强杀接管；D08 控制界面不得早于这些结论。

## 限制

- 现有真实站点控制证据来自 Tognar，是单 worker、同进程；不能代表多进程或浏览器池。
- R06 的 `RetryTests` 是 fixture 级，不覆盖真实 429 `Retry-After`、代理切换和会话复用。
- A20 只验证了并行启动，没有验证一个任务暂停／取消时另一个任务的计数和输出不受影响。
- 没有任务管理 API 或 Web UI，不能验证用户可见的取消、归档和恢复旅程；`app` 控制面目前是 CLI + SQLite，单 worker。
