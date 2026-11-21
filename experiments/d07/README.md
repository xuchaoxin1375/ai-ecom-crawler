# D07 可靠性缺口评估

## 目的与边界

对照 `docs/05` 的 A12／A13／A15／A20 和 `docs/09` 的状态、计数、取消语义，盘点当前实现的可靠性证据与缺口。D07 的生产目标需要 `app/` 执行器和任务账本；当前已有 R06 原型、D02 导出层、D04 v0 执行器和本轮补的单 worker 控制面，所以本页仍是**缺口评估 + 已修正的字段分类 + 控制面证据**，不是 D07 完成声明。

## 证据盘点

| 领域 | 已有证据 | 状态 | 缺口 |
| --- | --- | --- | --- |
| A12 访问与重试 | R06 `RetryTests`（transient 重试、耗尽、blocked 分类）、`RobotsTests`；D01 S6 挑战页；A08 429／Chrome 指纹；D06 JSON／HTML 路径 | 部分 | 无浏览器会话复用自动化；无统一 429 `Retry-After` 处理；无代理／出口资源登记 |
| A13 暂停／取消／恢复 | R06 `ControlTests`（暂停恢复、取消拒收迟到结果）、`RecoveryTests`（在途重置、尝试耗尽、孤儿状态、plan 版本不匹配）；Tognar 真实暂停／取消／强杀恢复；`app/tests/test_control.py`（状态转移、恢复对账、worker 单实例锁）、`test_control_flow.py`（暂停结清、恢复、取消拒收迟到结果、`run_forever`） | 原型 + `app` 单 worker 控制面通过 | 同进程单 worker；跨进程租约、心跳过期扫描、浏览器资源回收未实现 |
| A15 漂移与修复 | A08 两轮方案修订（入口前缀、正文／分类／选项）；D03／D04 同方案复跑；R06 提取缺失值测试 | 部分 | 没有自动化漂移检测／修复；没有旧结果失效标记；分类问题本轮修正 |
| A20 多任务并行 | R06 `ParallelTests`；`app/tests/test_control_flow.py` 的 `test_a20_pause_*`／`test_a20_cancel_*`：同域两任务并行，暂停／取消一个，另一个继续并输出独立；`test_same_domain_limiter_serializes` 验证同域限速 | 通过（同进程） | 无跨进程资源配额和跨进程隔离；浏览器实例配额未实现 |
| 原子写与幂等 | R06 `AtomicTests`、`StoreTests`；D02 app 原子写和幂等键 | 通过（单进程） | 跨进程幂等、租约和迟到结果拒收未验证 |
| 资源回收 | R06 `resources` 字段、无浏览器路径；D02 无外部资源；`app` 取消后无 `IN_FLIGHT`、无临时文件残留，`run_forever` 停止时 join 运行线程 | 部分 | 浏览器／进程登记、孤儿回收、取消后跨进程资源结清未实现 |

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

测试：`app/tests/test_control.py`（10 个转移／恢复／锁用例）和 `app/tests/test_control_flow.py`（8 个流程／A20／CLI 用例）；`app` 总计 88 个测试通过（含 9 个 D08 Web API 用例），`ruff check app` 通过。

## 测试结果

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" --with "jsonschema>=4.23" `
  python -m unittest discover -s experiments/r06/tests -v
```

结果：**83 个测试通过**，无 skip。覆盖原子写、契约、提取、运行时、重试、恢复、控制、并行、Schema 和新的字段分类。

## D07 结论

- **不是 D07 完成**：生产 `app` 执行器、任务账本、单 worker 控制面、单实例锁和同进程 A20 隔离已落地；跨进程租约、浏览器资源回收、跨进程 A20 隔离和自动化漂移修复仍未实现。
- **可复用的改进**：字段错误与业务排除的分类已修正，并进入 R06 回归测试；`app` 控制面复用同一状态语义。
- **下一步优先级**：先补跨进程租约和浏览器资源回收，再扩展跨进程 A20；D08 控制界面不得早于这些结论。

## 限制

- 现有真实站点控制证据来自 Tognar，是单 worker、同进程；不能代表多进程或浏览器池。
- R06 的 `RetryTests` 是 fixture 级，不覆盖真实 429 `Retry-After`、代理切换和会话复用。
- A20 只验证了并行启动，没有验证一个任务暂停／取消时另一个任务的计数和输出不受影响。
- 没有任务管理 API 或 Web UI，不能验证用户可见的取消、归档和恢复旅程；`app` 控制面目前是 CLI + SQLite，单 worker。
