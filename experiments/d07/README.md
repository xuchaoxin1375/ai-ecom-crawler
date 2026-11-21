# D07 可靠性缺口评估

## 目的与边界

对照 `docs/05` 的 A12／A13／A15／A20 和 `docs/09` 的状态、计数、取消语义，盘点当前实现的可靠性证据与缺口。D07 的生产目标需要 `app/` 执行器和任务账本；当前只有 R06 原型和 D02 导出层，所以本页是**缺口评估 + 一个已修正的字段分类问题**，不是 D07 完成声明。

## 证据盘点

| 领域 | 已有证据 | 状态 | 缺口 |
| --- | --- | --- | --- |
| A12 访问与重试 | R06 `RetryTests`（transient 重试、耗尽、blocked 分类）、`RobotsTests`；D01 S6 挑战页；A08 429／Chrome 指纹；D06 JSON／HTML 路径 | 部分 | 无浏览器会话复用自动化；无统一 429 `Retry-After` 处理；无代理／出口资源登记 |
| A13 暂停／取消／恢复 | R06 `ControlTests`（暂停恢复、取消拒收迟到结果）、`RecoveryTests`（在途重置、尝试耗尽、孤儿状态、plan 版本不匹配）；Tognar 真实暂停／取消／强杀恢复 | 原型通过 | 同进程单 worker；跨进程租约、心跳过期扫描、浏览器资源回收未实现 |
| A15 漂移与修复 | A08 两轮方案修订（入口前缀、正文／分类／选项）；D03／D04 同方案复跑；R06 提取缺失值测试 | 部分 | 没有自动化漂移检测／修复；没有旧结果失效标记；分类问题本轮修正 |
| A20 多任务并行 | R06 `ParallelTests` 两任务同时启动；runtime demo 两任务互不污染 | 部分 | 没有“暂停／取消其中一个、另一个继续”的自动化；无资源配额和站点级隔离 |
| 原子写与幂等 | R06 `AtomicTests`、`StoreTests`；D02 app 原子写和幂等键 | 通过（单进程） | 跨进程幂等、租约和迟到结果拒收未验证 |
| 资源回收 | R06 `resources` 字段、无浏览器路径；D02 无外部资源 | 部分 | 浏览器／进程登记、孤儿回收、取消后资源结清未实现 |

## 本轮修正：字段错误不再被当成业务排除

R06 原先把所有 `validate_product` 原因都映射为 `EXCLUDED`。这会掩盖选择器漂移：价格字段缺失、名称缺失或币种错误会被写成业务排除，而不是技术失败。

按 `docs/09` 改为：

- `zero_or_missing_price` → `EXCLUDED`（业务排除，保留原因）。
- 其他字段错误（`missing_name`、`missing_primary_image_url`、`missing_source_url`、`invalid_currency` 等）→ `FAILED`，`failure_class=permanent`，`reason=validation_error`，并保留 `reasons` 数组。

新增测试：

- `test_missing_name_is_failed_not_excluded`：缺名称 → `failed_products=1`、`excluded_products=0`、`outcome=FAILED`。
- `test_zero_price_is_excluded_not_failed`：零价 → `excluded_products=1`、`failed_products=0`、`outcome=COMPLETED`。

这与 D02 app 的归类一致：价格问题进排除流，字段／来源问题进失败流。

## 测试结果

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" --with "jsonschema>=4.23" `
  python -m unittest discover -s experiments/r06/tests -v
```

结果：**83 个测试通过**，无 skip。覆盖原子写、契约、提取、运行时、重试、恢复、控制、并行、Schema 和新的字段分类。

## D07 结论

- **不是 D07 完成**：生产 `app` 执行器、任务账本、跨进程租约、浏览器资源回收和自动化漂移修复仍未实现。
- **可复用的改进**：字段错误与业务排除的分类已修正，并进入 R06 回归测试；后续生产执行器应复用同一口径。
- **下一步优先级**：生产执行器接入（D04）优先于继续扩 R06；否则 D07 的跨进程和资源回收没有真实承载。

## 限制

- 现有真实站点控制证据来自 Tognar，是单 worker、同进程；不能代表多进程或浏览器池。
- R06 的 `RetryTests` 是 fixture 级，不覆盖真实 429 `Retry-After`、代理切换和会话复用。
- A20 只验证了并行启动，没有验证一个任务暂停／取消时另一个任务的计数和输出不受影响。
- 没有生产数据库、API 或 UI，不能验证用户可见的取消、归档和恢复旅程。
