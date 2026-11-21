# D07 可靠性缺口评估

## 目的与边界

对照 `docs/05` 的 A12／A13／A15／A20 和 `docs/09` 的状态、计数、取消语义，盘点当前实现的可靠性证据与缺口。D07 的生产目标需要 `app/` 执行器和任务账本；当前已有 R06 原型、D02 导出层、D04 v0 执行器和本轮补的单 worker 控制面，所以本页仍是**缺口评估 + 已修正的字段分类 + 控制面证据**，不是 D07 完成声明。

## 证据盘点

| 领域 | 已有证据 | 状态 | 缺口 |
| --- | --- | --- | --- |
| A12 访问与重试 | R06 `RetryTests`（transient 重试、耗尽、blocked 分类）、`RobotsTests`；D01 S6 挑战页；A08 429／Chrome 指纹；D06 JSON／HTML 路径；`app/tests/test_browser.py` 本地 JS fixture；`experiments/d07/browser-mercerine/` 真实站点 503 壳渲染与 3／3 | 部分 | 无统一 429 `Retry-After` 处理；无代理／出口资源登记；浏览器实例配额未验证 |
| A13 暂停／取消／恢复 | R06 `ControlTests`（暂停恢复、取消拒收迟到结果）、`RecoveryTests`（在途重置、尝试耗尽、孤儿状态、plan 版本不匹配）；Tognar 真实暂停／取消／强杀恢复；`app/tests/test_control.py`（状态转移、恢复对账、worker 单实例锁）、`test_control_flow.py`（暂停结清、恢复、取消拒收迟到结果、心跳续约、双 worker 单任务、过期接管）、`test_lease.py`（跨进程领取、旧写拒绝）；`experiments/d07/browser-mercerine/crash_test.py` 真实浏览器强杀接管 | 原型 + `app` 单机跨进程租约 + 浏览器接管通过 | 真实浏览器会话恢复（内存／页面状态）和跨机租约 |
| A15 漂移与修复 | A08 两轮方案修订（入口前缀、正文／分类／选项）；D03／D04 同方案复跑；R06 提取缺失值测试 | 部分 | 没有自动化漂移检测／修复；没有旧结果失效标记；分类问题本轮修正 |
| A20 多任务并行 | R06 `ParallelTests`；`app/tests/test_control_flow.py` 的 `test_a20_pause_*`／`test_a20_cancel_*`：同域两任务并行，暂停／取消一个，另一个继续并输出独立；`test_two_workers_process_one_task_once` 验证两个 worker 不重复领取；`test_same_domain_limiter_serializes` 验证同域限速 | 通过（同进程 + 单机双进程） | 无跨进程资源配额和浏览器实例配额；同域限速仍是进程内 |
| 原子写与幂等 | R06 `AtomicTests`、`StoreTests`；D02 app 原子写和幂等键；租约接管时丢弃未确认的商品输出尾行 | 通过（单机多进程） | 跨机幂等和真实浏览器输出未验证 |
| 资源回收 | R06 `resources` 字段、无浏览器路径；D02 无外部资源；`app` 取消后无 `IN_FLIGHT`、无临时文件残留，`run_forever` 停止时 join 运行线程；`task_resources` 登记进程／目录并按租约令牌回收；浏览器 fetcher 登记 Chromium PID 和 `browser-profile`，正常结束与强杀接管均回收 | 通过（本机静态 + 浏览器） | 浏览器实例配额、跨机回收和异步残留回收 |

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

## 2026-11-21 浏览器 adapter 与强杀接管

`app` 已接入 Patchright CDP 浏览器 fetcher，并按任务登记和回收 Chromium 进程与 profile。

- 规则：`fetch.default_engine: browser` 或 `per_url_type.<navigation|product>.engine`；`browser` 可为布尔值或选项对象。
- 生命周期：任务内懒启动一个 Chromium + 一个 page，请求串行；浏览器 fetcher 是 thread-affine，任务 item 不走线程池。
- 就绪与状态：支持 `wait_selector`／`wait_until`／`wait_ms`／`network_idle`；渲染后读取 navigation timing 的最终 `responseStatus`，挑战壳的 503 不再直接判死。
- 资源：Chromium PID 和 `<out-root>/<task-id>/browser-profile` 写入 `task_resources`；结束、取消和过期接管按租约令牌回收。
- 证据：
  - `app/tests/test_browser.py`：本地 JS 商品页，渲染后 1／1，资源表清空、profile 删除、PID 退出；另有配置、路由和非法引擎测试。
  - `experiments/d07/browser-mercerine/`：mercerine 首页 503 壳渲染后 3／3（约 80 秒），一个浏览器会话复用 4 个请求。
  - `crash_test.py`：强杀 worker 后 Chromium 仍存活；租约过期后新 worker 接管，终止遗留 Chromium、删除 profile、资源表清空，任务重跑 1／1。

## 2026-11-21 浏览器交互推进（load_more／infinite_scroll）

`app` 在浏览器 fetcher 上增加两种有界推进，要求 `schema_version: "1.2"` 且 listing navigation 走浏览器。

- `load_more`：`button_selector`、`max_clicks`、`settle_ms`、`no_new_stop`；点击后等条目数增加，按钮消失／禁用即停。
- `infinite_scroll`：`container`、`mode`（`auto`／`scroll`／`wheel`）、`max_scrolls`、`settle_ms`、`no_new_stop`；滚动 window 或指定容器。
- 只支持追加型列表：最终 DOM 保留前面条目；虚拟列表只保留最后一批，不能用该实现直接采全量。
- 列表工作项结果记录 `advance.type`、`steps`、`items`、`stop`、`start_url`、`final_url`、`url_changes` 和 `urls`；最终 DOM 仍走现有链接发现和 scope 过滤。
- 先看 URL：如果点击／滚动后地址栏更新为 `?page=N`，且直接打开该 URL 能返回对应页，优先用 `page_param`／`next_link`，不要把点击／滚动作为常规路径。基准站 `ecolaines.com/3-laine` 就是这种案例：页面用 `kiwik infinite scroll`，但 `?page=N` 可直接取页；静态 `page_param` 前两页 20／20、约 36 秒、无浏览器（`experiments/d07/ecolaines-url/`）。
- 证据：
  - `app/tests/test_browser_actions.py`：本地追加型列表，两种推进各 6／6；schema 版本和静态 navigation 校验。
  - `experiments/d07/browser-listing/`：`scrapingcourse.com` 公开练习页，`load_more` 1 次点击后 24 条、`infinite_scroll` 2 次滚动后 36 条，均取前 15 个商品、15／15 有效（多次复跑，约 75–88 秒）。
  - `experiments/d07/url-pagination-batch/`：5 个法国基准站的 URL 可寻址检查。`mapetitemercerie.com` 两页各 10／10（`?page=2`），`gaspardetleonie.com` 26／26（Shopify `rel=next`，第 2 页 2 条），`touchatou.fr` 22／22（`/page/2/`，第 2 页 2 条）；`atelier-leonie.fr` 单页 40、无下一页，`tissus.net` 静态无商品卡片、留待浏览器／API。全部静态、0 失败。

## 测试结果

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" --with "jsonschema>=4.23" `
  python -m unittest discover -s experiments/r06/tests -v
```

结果：**83 个测试通过**，无 skip。覆盖原子写、契约、提取、运行时、重试、恢复、控制、并行、Schema 和新的字段分类。`app` 当前 **140 个测试通过**（含 8 个浏览器配置／路由／fixture 用例、5 个 load_more／infinite_scroll 用例（含内部容器）、4 个桥接状态用例和 1 个原子写用例），`ruff check app` 通过；真实浏览器用例在缺少 Chromium 的环境中会跳过，本机运行结果为通过。

## D07 结论

- **不是 D07 完成**：生产 `app` 执行器、任务账本、控制面、单实例锁、同进程 A20、单机跨进程租约、进程／目录资源回收、真实浏览器进程／profile 回收和两种有界浏览器推进已落地；跨进程资源配额、浏览器实例配额、虚拟列表／更复杂的内部滚动（内部容器追加型已测）、跨机租约和自动化漂移修复仍未实现。
- **可复用的改进**：字段错误与业务排除的分类已修正，并进入 R06 回归测试；`app` 控制面复用同一状态语义；租约和资源登记不改变对外任务状态；浏览器挑战壳要按渲染后的最终状态判断，不能只看首个 HTTP 响应。
- **下一步优先级**：URL 可寻址检查已覆盖 `ecolaines` 与 5 个法国基准站；接下来补虚拟列表、更复杂的内部滚动、浏览器实例配额和跨进程资源配额，并对 `tissus.net` 这类 JS／API 列表做浏览器或公开 API 验证。D08 控制界面不得早于这些结论。

## 限制

- 现有真实站点控制证据来自 Tognar（静态）和 mercerine（浏览器），仍是单 worker、单机；不能代表多进程或浏览器池。
- 浏览器证据是首页 3 个商品的有界样本，不是全站；headless 通过不代表挑战站长期稳定。
- 浏览器 adapter 已支持渲染、任务级回收和追加型 `load_more`／`infinite_scroll`（含 `container` 内部滚动，本地 fixture 6／6）；虚拟列表、更复杂的内部滚动、浏览器实例配额和跨机回收未验证。
- 浏览器交互证据来自公开练习页和本地 fixture，不是基准站或生产店铺；只有首页列表的有界样本。
- R06 的 `RetryTests` 是 fixture 级，不覆盖真实 429 `Retry-After`、代理切换和会话复用。
- A20 只验证了并行启动，没有验证一个任务暂停／取消时另一个任务的计数和输出不受影响。
- 没有任务管理 API 或 Web UI，不能验证用户可见的取消、归档和恢复旅程；`app` 控制面目前是 CLI + SQLite，单 worker。
