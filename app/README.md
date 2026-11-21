# 生产应用（app/）

本目录是 monorepo 中生产应用的承载位置。当前已落地 **D02 数据合同与导出 CLI**、**D04 v0 静态执行器**、**浏览器 adapter v0**和 **hybrid adapter discovery**：规则包 → 发现／获取／提取 → SQLite 任务账本 → D02 导出。静态 worker 带跨进程任务租约和资源登记／回收；浏览器 worker 按任务启动 Patchright CDP，登记并回收浏览器进程和 profile；hybrid 规则把 C2 discovery 交给包内 adapter 子进程，商品页仍由声明式 `fetch`／`extract` 处理。完整跨进程 A20、adapter 浏览器资源配额和构建会话仍未实现。

## 边界

- `docs/` 是业务口径与验收的唯一入口；`app/` 不复制业务规则，只提供机器可执行的投影。
- `experiments/` 是实验与原型，不作为生产代码；本目录从原型的契约结论重建，不复制站点证据或任务数据库。
- `app/` 不进入 `scripts/export_docs.py` 的文档包；文档导出仍只包含 `docs/`。
- 生产代码最终闭源；第三方依赖保留各自许可证。

## 当前范围

已实现：

- 候选商品记录的形状校验与业务归类。
- 正价、变体最低价、税价候选、币种、市场一致性。
- 描述 HTML 白名单清洗、裸文本转 HTML、完整／部分／摘要／未提供状态。
- 主图相对路径解析与占位图识别。
- 分类过滤、选项合并与 `attributes` 兼容序列化。
- 9 列业务 CSV、`task-result.json`、内部记录和排除／失败诊断。
- 计数不变量、`outcome` 推导、`quality_exceptions` 异常索引。
- `export`、`validate`、`run`、`submit`、`worker`、`pause`、`resume`、`cancel`、`status`、`list` 和 `serve` CLI 子命令。
- 声明式规则包读取与校验；`entry_links`、`sitemap`、`listing`、`html_index`、`public_json` 发现来源。
- 静态发现、获取、提取、基础重试和 SQLite 任务账本。
- 浏览器 fetcher：`fetch.default_engine: browser`、`fetch.per_url_type` 按 `navigation`／`product` 路由、Patchright CDP 启动、任务级 profile、`wait_selector`／`wait_until`／`wait_ms`／`network_idle`、渲染后的有效状态读取和任务级进程／目录登记回收。
- 浏览器列表推进：`schema_version: "1.2"` 的 `listing` 支持 `load_more`（按钮点击）和 `infinite_scroll`（window／容器滚动），记录 `steps`／`items`／`stop`；只支持追加型列表。
- `run` 执行 product 任务并自动接入 D02 导出。
- 单 worker 控制面：`submit` 入队，`worker` 常驻执行，`pause`／`resume`／`cancel` 从另一个进程改账本，runner 在检查点响应并拒收迟到结果。
- 跨进程任务租约：`tasks` 表保存 `lease_owner`、单调递增的 `lease_token`、到期时间和心跳；`claim_tasks` 原子领取，心跳线程续约，过期任务由任意 worker 对账回收，旧持有者的写入按租约条件拒绝。
- `task_resources` 资源登记：登记子进程 PID 和 profile／临时目录；任务结束、取消或过期接管时按租约令牌回收，避免误删新持有者的资源。
- 构建 harness 适配器：`harness/` 提供 `HarnessAdapter`、`OpenCodeHttpAdapter`、`OpenCodeServer`、构建工作区、HTTP/SSE 客户端和事件归一化；真实 `opencode serve` 的 session／事件／权限探针已跑通。
- FastAPI API：健康、规则目录、任务列表／详情、创建／启动／暂停／恢复／取消／归档／还原、URL／商品分页、SSE 和 zip 导出。
- 本地静态页面：任务列表、创建、详情、控制按钮、计数、质量异常、items 和导出入口。
- 账本增加 `site_key`、`domain_key`、`market`、`rule_path`、`archived_at` 和创建幂等键；旧库自动加列。

尚未实现：

- 虚拟列表、任意点击序列和 POST／GraphQL；当前 `load_more`／`infinite_scroll` 只支持追加型列表，内部滚动容器（`container`）的追加型列表已有本地 fixture。
- 跨进程 A20 的真实资源配额、浏览器实例配额和跨机租约；当前租约在单机 SQLite 上验证。
- 永久移除、异步残留回收、构建会话 UI、`request_dependency` 工具桥、真实依赖安装和完整前端原型评审。
- 生产级浏览器孤儿回收的跨机路径；本机强杀 worker 后的租约接管已演练，浏览器进程和 profile 会被回收。

## 布局

- `src/ecom_crawler/`：应用代码。
- `src/ecom_crawler/runtime/`、`executor/`：从 R06 抽取的静态运行时和提取器；`runtime/browser.py` 是 Patchright CDP 浏览器 fetcher。
- `src/ecom_crawler/web/`：本地 FastAPI 应用和静态页面。
- `src/ecom_crawler/execution.py`、`bridge.py`：执行入口与 R06→D02 转换。
- `schemas/`：候选输入、内部商品记录和任务结果的 JSON Schema。
- `tests/`：T1 契约／单元测试和本地 fixture 集成测试，无外部网络。
- `pyproject.toml`：独立依赖与 `ecom-crawler` 入口。
- `uv.lock`：应用依赖锁定。

## 环境与测试

```powershell
python -m uv run --project app --extra dev python -m unittest discover -s app/tests -t app -v
python -m uv run --project app --extra dev ruff check app
```

`jsonschema`、`httpx` 和 `ruff` 是开发依赖；`jsonschema`／`httpx` 缺失时测试会失败，不会 skip。应用运行依赖包括 `lxml`、`pyyaml`、`scrapling[fetchers]`、`patchright`、`protego`、`fastapi` 和 `uvicorn`；`scrapling[fetchers]` 会带 `curl_cffi`、`playwright`、`browserforge` 和 `msgspec`。浏览器模式还需要 Chromium：

```powershell
python -m patchright install chromium
```

`real_chrome: true` 时使用系统 Chrome／Edge，不依赖 Patchright 的 Chromium 下载。

## CLI

```powershell
python -m uv run --project app ecom-crawler --version
python -m uv run --project app ecom-crawler run --rule /path/to/rule.yaml --db /path/to/tasks.db --out-root /path/to/tasks --task-id sample-001 --task-type product --max-products 6
python -m uv run --project app ecom-crawler submit --rule /path/to/rule.yaml --db /path/to/tasks.db --task-id sample-002
python -m uv run --project app ecom-crawler worker --db /path/to/tasks.db --out-root /path/to/tasks
python -m uv run --project app ecom-crawler worker --db /path/to/tasks.db --out-root /path/to/tasks --allow-multi-worker --lease-ttl 30
python -m uv run --project app ecom-crawler serve --db /path/to/tasks.db --out-root /path/to/tasks --rules-dir /path/to/rules --port 8765
python -m uv run --project app ecom-crawler pause --db /path/to/tasks.db --task-id sample-002
python -m uv run --project app ecom-crawler resume --db /path/to/tasks.db --task-id sample-002
python -m uv run --project app ecom-crawler cancel --db /path/to/tasks.db --task-id sample-002
python -m uv run --project app ecom-crawler status --db /path/to/tasks.db --task-id sample-002 --json
python -m uv run --project app ecom-crawler list --db /path/to/tasks.db --state RUNNING
python -m uv run --project app ecom-crawler export --run-dir /path/to/run --out-dir /path/to/out
python -m uv run --project app ecom-crawler validate --run-dir /path/to/out
python -m uv run --project app ecom-crawler validate --task-result /path/to/task-result.json
```

- `run` 每次执行一个任务；product 任务完成后自动导出到 `<out-root>/<task-id>/export`，discovery 任务只写运行时 URL 清单和任务结果。
- `run` 的退出码表示任务是否实际执行；业务结论看 `task-result.json` 的 `outcome`。计划或用法错误返回 2。
- `run` 是一次性入口，不提供可恢复的控制；需要暂停／恢复／取消时用 `submit` 入队，再在另一个 shell 运行 `worker`，用 `pause`／`resume`／`cancel` 控制。外部暂停 `run` 任务后，`run` 以 2 退出并提示用 `worker` 恢复。
- `serve` 只绑定回环地址，默认启动托管 worker（持有 worker 单实例锁）；`--no-worker` 只提供 API／页面，执行由独立 `worker` 进程负责。页面关闭不会停止后台。
- `worker` 默认 `--max-tasks 1`，按 `QUEUED` 取任务；Ctrl+C 停止领取新任务并等待已启动任务结束，已取消任务用 `cancel` 处理。
- `pause` 只接受 `RUNNING`，`resume` 只接受 `PAUSED`；重复请求按当前状态幂等返回，非法转移返回 2。
- `status` 和 `list` 是只读入口；`--json` 输出可直接给脚本消费。任务计数仍以 `task-result.json` 和 `docs/09` 为准。
- `export` 默认拒绝覆盖已存在的 `products.csv`／`task-result.json`；需要覆盖时加 `--force`。
- `export` 的退出码表示导出流程是否成功，不表示业务结论；业务结论看 `task-result.json` 的 `outcome`。
- `export` 的输入或任务元数据错误返回 2；`validate` 的校验失败返回 1。

## 浏览器规则（browser）

```yaml
fetch:
  default_engine: "browser"
  per_url_type:
    navigation: {engine: "static"}
    product:
      engine: "browser"
      wait_selector: "h1.product-name"
  browser:
    headless: true
    real_chrome: false
    disable_resources: true
    challenge_wait_ms: 0
```

- `browser` 接受布尔值或选项对象。选项包括 `headless`、`real_chrome`、`executable_path`、`wait_until`、`wait_selector`、`wait_selector_state`、`wait_ms`、`network_idle`、`network_idle_timeout_ms`、`disable_resources`、`challenge_wait_ms`、`timeout_ms`、`locale`、`timezone`、`user_agent`、`extra_flags`、`profile_name`。
- 浏览器按任务懒启动：一个 Chromium/Chrome + 一个 page，请求串行；任务结果在 `runtime.browser` 记录 binary／version／pid／profile，在 `access.browser_launched` 和 `resources.browser_pid` 记录是否使用。
- listing 的 `advance` 支持 `load_more`／`infinite_scroll`（需要 `schema_version: "1.2"` 且 listing 走浏览器）：

```yaml
discovery:
  sources:
    - type: listing
      url: "https://example.test/category/"
      product_link_selector: ".product a"
      advance:
        type: load_more
        button_selector: "#load-more"
        max_clicks: 3
        settle_ms: 1500
        no_new_stop: 2
    - type: listing
      url: "https://example.test/all/"
      product_link_selector: ".product a"
      advance:
        type: infinite_scroll
        container: "#product-grid"
        mode: scroll
        max_scrolls: 5
        settle_ms: 1500
        no_new_stop: 2
```

  `load_more` 点击按钮并等条目数增加；`infinite_scroll` 滚动 window 或指定容器。`max_clicks`／`max_scrolls`、`settle_ms` 和 `no_new_stop` 是有界停止条件；listing 工作项的结果会带 `advance` 统计，包括 `start_url`、`final_url`、`url_changes` 和 `urls`。虚拟列表只保留最后一批，不能用该实现直接采全量。

  先检查交互后的地址栏／`history.pushState`：如果变成稳定的 `?page=N` 或 `/page/N`，且直接请求该 URL 返回对应页，改用 `page_param`／`next_link`，不要继续点击或滚动。`load_more`／`infinite_scroll` 只用于 URL 不可寻址、直接打开回到首屏／空壳或虚拟列表的站点。基准站 `ecolaines.com/3-laine` 与公开练习页 `scrapingcourse.com/infinite-url` 都有这种 URL 可寻址模式。
- 浏览器子进程和 `<out-root>/<task-id>/browser-profile` 登记在 `task_resources`；正常结束、取消、租约过期接管都会回收。本机强杀 worker 后由新 worker 接管并回收的演练见 `experiments/d07/browser-mercerine/`。
- 首次响应可能是 403／429／503 挑战壳，站点自己的 JS 跳转后才出现正文；fetcher 在等待完成后读取 navigation timing 的最终 `responseStatus`，并可用 `wait_selector` 作为就绪条件。它不点击、不过验证码、不绕过登录或付费。挑战识别是标题启发式，可能漏判或误判，最终以就绪信号、正文和任务结果为准。
- 浏览器 fetcher 是 thread-affine，浏览器任务不走线程池；暂停／取消在条目边界生效，单次导航仍受 `timeout_ms` 约束。

## Hybrid adapter（hybrid）

需要虚拟列表、网络重放、多步状态等 C2 交互时，规则包声明 `kind: hybrid`，把 discovery 交给包内 adapter，商品页仍由 `fetch`／`extract` 处理。运行时不 import adapter，而是按 `runtime.entrypoint` 启动子进程，传入上下文 JSON，按 NDJSON 读取 `discovered`／`done`／`error`。

```yaml
kind: "hybrid"
discovery:
  sources:
    - type: adapter
      url: "https://example.test/catalogue"
      advance: {item_selector: "a.product", container: "#feed", settle_ms: 100, no_new_stop: 1}
      max_batches: 10
      max_seconds: 30
  product_url_patterns: ['^/product/[^/]+$']
runtime:
  adapter_id: "virtual-list-patchright"
  adapter_version: "2026.11.22-1"
  entrypoint: "adapter.py"
  protocol: "ndjson-stdio-v1"
  capabilities: ["discovery"]
```

- adapter 子进程超时受 `source.max_seconds` 和任务 `max_seconds` 约束；超时按进程组终止（Windows `taskkill /T`，POSIX `killpg`）。stdout 写入 `<out-root>/<task-id>/adapter.ndjson`，输入上下文写入 `adapter-context.json`。
- 成功标准是 `done` + `discovered` 事件；`error` 或非零退出记为 `ADAPTER_FAILED`，不产生半成品商品。
- `task-result.json` 的 `runtime.adapter` 记录 `discovered`／`added`／`skipped`／`stop`／`batches`／`requests`／`elapsed_ms`。
- 当前只接入 adapter discovery，商品页仍由声明式 fetcher 处理。adapter 默认 `browser.profile_mode: ephemeral`，用临时 context，不分配 profile，也不产生 profile 清理；需要登录／挑战页／跨步骤会话时显式设 `profile_mode: task`，app 才分配任务级 `adapter-browser-profile`、登记到 `task_resources`，退出后删除，删除失败时按 profile 路径做 best-effort 进程扫描。超时已按进程组终止。浏览器实例配额（单进程／跨进程）已接入。本地端到端证据：`experiments/d07/virtual-list-hybrid/app-evidence/virtual-list-app-001/`；真实 JS 渲染列表证据：`experiments/d07/tissus-adapter/`（10／10）。

## 执行入口（run）

`run` 读取一个声明式或 hybrid 规则包，创建任务并在当前进程执行：

- 规则包：YAML manifest；`rule_id`／`rule_version` 必须与任务一致；声明式支持 `entry_links`、`sitemap`、`listing`、`html_index`、`public_json` 来源；hybrid 还支持 `discovery.sources[].type=adapter`。
- 账本：`--db` 指向的 SQLite 文件，记录任务、工作项、状态、尝试次数和失败分类。
- 输出：`<out-root>/<task-id>/` 下有 `task-result.json`、`products.jsonl`、`urls.csv`、`events.ndjson` 等运行时产物；product 任务另有 `app-run/` 和 `export/`。
- 当前是单进程运行时；静态 HTML、浏览器渲染、SQLite 租约、资源回收、`load_more`／`infinite_scroll` 和 hybrid adapter discovery 已接入；跨机租约、跨进程资源配额和 adapter 浏览器实例回收未接入。

## 控制面（submit / worker / pause / resume / cancel）

- `submit` 只创建 `QUEUED` 任务，不启动执行；`worker` 常驻读取账本中的 `QUEUED` 任务。
- `worker`／`serve` 的 `--max-browser-tasks` 限制每个 worker 进程同时运行的 browser／hybrid 任务数（默认 1，0 表示不限制）。同一 SQLite 账本上的多个 worker 通过 `browser_slot` 行协调到同一上限；跨机配额仍未实现。
- `pause` 把 `RUNNING` 改为 `PAUSING`；runner 停止派发新工作，等在途结清后写 `PAUSED`。
- `cancel` 把 `RUNNING`／`PAUSING` 改为 `CANCELLING`；runner 等在途结束，拒绝迟到结果，写 `CANCELLED`。`DRAFT`／`QUEUED`／`PAUSED` 直接进入 `CANCELLED`。
- `resume` 把 `PAUSED` 改回 `QUEUED`，由 `worker` 重新领取；不恢复浏览器内存或旧会话。
- 状态转移校验在 `TaskStore.request_*`，不在 CLI 或页面里重复实现；非法转移和未知任务返回 2。
- `worker` 默认获取 `<db>.worker.lock` 单实例锁；锁由操作系统在进程退出时释放，残留锁文件不会阻止下次启动。加 `--allow-multi-worker` 后跳过该锁，多个 worker 进程通过任务租约共享同一账本。
- 任务领取是原子的：`claim_tasks` 把 `QUEUED` 改为 `RUNNING` 并递增 `lease_token`；同一任务同一时刻只有一个持有者。心跳默认每 `min(5, ttl/3)` 秒续约；租约过期后，任意 worker 的对账扫描会把 `RUNNING` 放回 `QUEUED`、把 `PAUSING` 结清为 `PAUSED`、把 `CANCELLING` 结清为 `CANCELLED`。
- 旧持有者继续写会命中 `LeaseLostError`：`update_task`、`add_item`、`claim_items`、`mark_item` 和 `reconcile_task` 都支持同一事务内的租约校验。恢复时还会丢弃未被账本 `DONE` 工作项确认的 `products.jsonl` 尾行。
- 同进程 A20 已覆盖：同域两任务并行，暂停／取消一个，另一个继续并保持独立输出；同域请求共用限速器。
- 跨进程任务领取、过期接管和旧写拒绝已有测试；真实浏览器实例配额、跨进程资源配额和跨机租约仍未实现。
- 证据：`tests/test_control.py` 覆盖状态转移、启动对账和单实例锁；`tests/test_control_flow.py` 覆盖暂停结清、恢复、取消拒收迟到结果、`run_forever`、心跳续约、双 worker 单任务和过期接管；`tests/test_lease.py` 覆盖跨进程原子领取、过期回收、旧写拒绝和旧库迁移；`tests/test_resources.py` 覆盖进程／目录回收和租约令牌隔离。

## 租约与资源回收

- `TaskStore.claim_tasks(owner, limit, ttl_seconds)` 在 `BEGIN IMMEDIATE` 中领取任务，返回带 `lease_token` 的 `Lease`；重复调用不会把同一任务发给两个 worker。
- `renew_lease` 只在租约尚未过期且持有者、令牌和状态都匹配时续期；过期后不能“复活”，必须由对账重新排队。
- `settle_expired_tasks` 只处理租约缺失或已过期的任务，不碰活租约；`RUNNING` 回 `QUEUED` 并重置在途项，`PAUSING` 结清为 `PAUSED`，`CANCELLING` 结清为 `CANCELLED` 并拒收在途结果。
- `TaskRunner` 在每个循环、领取工作项、写结果和收尾前校验租约；写入层再用同一事务的条件更新做二次拒绝，避免旧持有者在新持有者接管后继续写账本。
- `runtime.resources` 提供 `register_process`、`register_path` 和 `cleanup_task_resources`：浏览器 fetcher 登记子进程 PID 和 `browser-profile` 目录，并带当前 `lease_token`；回收时不会碰更新令牌的资源。
- 资源记录存在 SQLite 的 `task_resources` 表，任务结束、取消和过期接管都会触发回收。浏览器路径已用本地 fixture 和真实站点验证正常回收；本机强杀 worker 后，新 worker 接管并杀掉遗留 Chromium、删除 profile 的演练见 `experiments/d07/browser-mercerine/crash_test.py`。

## 构建 harness 适配器

- `harness/` 只服务构建期，不进入采集运行时；执行期仍零 LLM。
- `OpenCodeServer` 在回环地址用随机端口和随机 `OPENCODE_PASSWORD` 启动 `opencode serve`，记录版本并在关闭时回收进程树；`OPENCODE_BIN` 可覆盖可执行文件。构建 server 的 cwd 指向 `work/`，使工作区内的 `.opencode/plugins/` 被发现。server 使用当前 OpenCode 的 provider 配置；构建工作区隔离，但 OpenCode 自身的数据目录尚未按构建强制隔离，当前每次冒烟会删除 session。
- `OpenCodeClient` 封装 ADR 0006 的最小端点：session 创建／查询／删除、prompt、permission 列表／创建／回复、model、interrupt、message、export 和 `/api/event` SSE。
- `OpenCodeHttpAdapter` 实现 `start_build`、`send_prompt`、`stream_events`、`reply_permission`、`pause`／`resume`、`cancel`、`collect_artifacts` 和 `close`；构建会话状态独立于采集任务状态。
- `BuildService` 管理 v1 单个活动构建：后台事件泵、事件日志、pending／held 权限、暂停后恢复时自动回复 held 权限、取消／关闭和依赖请求委托；这是服务边界，不是构建会话 UI。
- 每次构建在 `sessions/<build_id>/` 下创建 `input/`、`work/`、`out/`、`logs/` 和 `control/`；`control/pause.json` 是 pause-gate 的控制文件，读取失败按暂停处理（fail closed）。`BuildWorkspace.create` 会把 `pause-gate` 插件写入 `work/.opencode/plugins/pause-gate/`；插件在权限 hook 中把暂停期间原本 `allow` 的工具动作提升为 `ask`，并把动作和效果写入 `control/pause-gate.log`。真实 shell 工具冒烟已看到 `shell allow -> ask`。
- 事件归一化把 OpenCode 事件映射为 `phase_changed`、`tool_started`、`tool_finished`、`permission_requested`、`permission_replied`、`message_delta`、`finished`、`error` 等；推理事件只记录 `redacted`，不保存私有推理。
- `DependencyPolicy` 提供基线／allowlist 判定和隔离安装边界：包名、版本和 manager 先校验，安装只调用显式 build interpreter 的 `pip`，不经 shell；未配置策略或安装器时返回 `approval_required`。`OpenCodeHttpAdapter.request_dependency` 会写结构化事件，但 OpenCode 侧的 `request_dependency` 工具桥仍未接入。
- 真实、无模型的冒烟与结果见 `experiments/harness/README.md`。BuildService 和构建会话 UI 仍未接入；真实自然完成尚未验证。

## Web 服务（serve）

- `serve` 用 FastAPI 托管 `/api/*` 和 `static/`，默认 `127.0.0.1:8765`，拒绝非回环地址；`--rules-dir` 指向受管规则包目录。
- 默认启动托管 worker（`--max-tasks` 默认 1），持有 `<db>.worker.lock`；`--no-worker` 可只读启动，便于另跑 `worker`。
- 只读 API：`GET /api/health`、`GET /api/rules`、`GET /api/tasks`、`GET /api/tasks/{id}`、`GET /api/tasks/{id}/items?kind=url|product`、`GET /api/tasks/{id}/export`。
- 写 API：`POST /api/tasks`（`DRAFT` + `request_id` 幂等）、`start`、`pause`、`resume`、`cancel`、`archive`、`restore`。
- `GET /api/tasks/{id}/events` 是 SSE：连接先发 `snapshot`，再转发 `events.ndjson` 增量，终态发 `end`；断线重连以快照为准。
- 导出 zip 只允许 `products.csv`、`task-result.json`、`records.jsonl` 和 `diagnostics/` 下的排除／失败文件；`partial=true` 才允许导出未结束任务。
- 页面支持列表、创建、详情、控制按钮、计数、覆盖、质量异常、items 和导出；控制请求显示“已受理”，最终状态以账本为准。
- 托管 worker 在服务生命周期内执行 `QUEUED` 任务；服务退出时先停止领取新任务，再等待已启动任务结束。
- `--no-worker` 时创建／启动的任务保持 `QUEUED`，需要另跑 `ecom-crawler worker`；完整前端原型评审仍未做。
- 证据：`tests/test_web.py` 覆盖健康、规则目录、列表筛选、详情、items 分页、创建幂等、控制转移、归档／还原、SSE、导出白名单和错误码。

## 输入契约

`--run-dir` 至少包含 `task.json` 和 `candidates.jsonl`。

### task.json

| 字段 | 要求 |
| --- | --- |
| `task_id`、`plan_id`、`plan_version` | 非空；对应当前任务与方案版本 |
| `market`、`locale` | 非空；候选记录未单独给出时作为默认值 |
| `state` | `FINISHED` 或 `CANCELLED` |
| `stop_reason` | `docs/09` 的枚举；`CANCELLED` 必须配 `USER_CANCELLED` |
| `started_at`、`finished_at` | 非空 |
| `counts.discovered_urls` | 任务内唯一业务网址数；不得小于商品候选数 |
| `counts.pending_navigation_entries` | 尚未访问的导航网址数；大于零时结果不能是 `COMPLETED` |
| `counts.pending_products` | 尚未处理的商品候选数；默认 0 |
| `coverage` | 可选；缺省为 `UNKNOWN`，有分母时必须给出 `denominator` |
| `business_acceptance` | 可选；缺省为 `NOT_REVIEWED`，用户验收不覆盖系统停止原因 |
| `runtime` | 可选；默认 `llm_calls=0`、`raw_pages_retained=false` |
| `limitations`、`synthetic_example` | 可选；原样保留 |

`counts` 中的字段也可以放在顶层；`task_type` 缺省为 `product`。

### candidates.jsonl

每行一个 JSON 对象。完整的 docs/示例形状可直接使用；`price.variants`、`price.candidates`、`description.blocks` 和 `sales_unit` 是可选扩展。

| 字段 | 要求 |
| --- | --- |
| `source_url` | 必填；`http`／`https`，不含凭据；去 fragment 后用于去重 |
| `name` | 必填；只清理来源主机等价后缀，不猜删品牌词 |
| `price.amount` | 与 `price.currency` 一起构成主报价；支持数字或带符号／千位符的字符串 |
| `price.variants` | 可选；取最低正价变体（含缺货有价），合并变体选项，并在内部记录保留变体级价格／库存／SKU |
| `price.candidates` | 可选；按 `label` 标记 `displayed`／`pretax`，取较小正价 |
| `price.tax_basis` | `INCLUSIVE`、`EXCLUSIVE`、`NOT_SPECIFIED` 或 `UNSPECIFIED` |
| `primary_image_url` | 必填；相对路径按 `source_url` 解析；占位图不算主图 |
| `description_html`／`description_format` | 二选一或同时给出；`html` 走白名单清洗，`text` 转段落 HTML |
| `description` | 可选嵌套形式：`html`、`text`、`format`、`status`、`partial_reason`、`missing_reasons`、`blocks` |
| `description_status` | 必填；`COMPLETE`、`PARTIAL`、`SUMMARY_FALLBACK`、`NOT_PROVIDED`、`FAILED`；不从正文内容自动推断 |
| `categories` | 字符串或字符串数组；过滤 Home／Shop／Women／Clothing 等泛层级 |
| `brand` | 可空；不把店名或域名当品牌 |
| `options` | 维度和值数组；数量组、价格差值和空值会被移除 |
| `availability` | 可确认的库存状态；`OnlineOnly`／`InStoreOnly` 只作观察值，不映射为库存 |
| `sales_unit` | 可选；有正文且正文未包含时在开头补独立段落，不重复、不从控件推算 |
| `market`／`locale` | 可选；`market` 与任务不一致时进入排除流 |
| `extracted_at` | 可选；缺省用任务的 `finished_at` |

示例：

```json
{"source_url":"https://shop.example/products/shirt","name":"Example Shirt","price":{"amount":"29.00","currency":"GBP","tax_basis":"INCLUSIVE"},"primary_image_url":"/images/shirt.jpg","description_html":"<p>A shirt.</p>","description_status":"COMPLETE","categories":["Shirts"],"brand":"Example","options":[{"name":"Size","values":["S","M"]}],"market":"GB","locale":"en-GB","availability":"IN_STOCK"}
```

## 输出契约

| 文件 | 内容 |
| --- | --- |
| `products.csv` | `docs/02` 的固定 9 列，UTF-8，无 BOM |
| `task-result.json` | `docs/09` 的任务结果、计数、覆盖、业务验收和 `quality_exceptions` |
| `records.jsonl` | 内部规范化记录；含变体级价格／库存／SKU 和字段来源，CSV 是它的 9 列投影 |
| `diagnostics/excluded.jsonl` | 业务排除记录，保留 `source_url`、`reason` 和观察价 |
| `diagnostics/failed.jsonl` | 技术失败记录，保留 `source_url`、`reason` 和明细 |

CSV 对以 `=`、`+`、`-`、`@` 开头的文本单元格加单引号，防止表格软件公式注入；机器消费时需要按约定还原。

## 归类规则

排除流（业务排除，不进入有效集）：

- `MISSING_PRICE`、`NON_POSITIVE_PRICE`、`INVALID_PRICE`、`AMBIGUOUS_PRICE`
- `DUPLICATE_SOURCE_URL`
- `MARKET_MISMATCH`

失败流（技术或方案错误，不进入有效集）：

- 来源网址、名称、币种、主图缺失或非法
- 占位图
- 描述状态冲突、部分描述缺 `partial_reason`
- `missing_reasons` 与实际字段冲突
- 选项、分类、字段来源等形状错误

任务级 `outcome` 按 `docs/09` 从计数和停止原因推导：仍有待处理或技术失败为 `PARTIAL`；零有效且存在失败或环境／方案／访问错误为 `FAILED`；用户取消为 `CANCELLED`；其余为 `COMPLETED`。零有效但全部为业务排除时仍可为 `COMPLETED`，报告必须说明原因。

## D02 验收映射

| 场景 | 自动化证据 |
| --- | --- |
| A01 正价／零价／无价 | `test_pipeline.py::test_non_positive_and_missing_prices_are_excluded`、`test_normalize.py::PriceTests` |
| A02 变体最低价与选项 | `test_pipeline.py::test_variants_choose_lowest_positive_and_keep_options` |
| A03 税价与市场 | `test_pipeline.py::test_tax_candidates_choose_smaller_public_price`、`test_market_mismatch_is_excluded` |
| A04 完整正文与摘要 | `test_normalize.py::test_clean_html_preserves_tables_and_lists`、`test_summary_fallback_is_marked` |
| A05 复杂部分描述 | `test_normalize.py::test_partial_requires_reason`、`test_pipeline.py::test_quality_exception_lists_partial_and_missing_fields` |
| A06 HTML 与裸文本 | `test_normalize.py::test_plain_text_is_wrapped`、`test_csv_contract.py::test_nine_columns_and_text_escaping` |
| A07 主图／分类／品牌／单位 | `test_normalize.py::test_placeholder_image_detection`、`test_categories_drop_generic_levels_and_duplicates`、`test_pipeline.py::test_sales_unit_is_added_once_to_description` |
| A14 导出保真 | `test_csv_contract.py::test_nine_columns_and_text_escaping`、`test_export_run_writes_task_result_with_escaped_json` |
| A18 基础字段与分块描述 | `test_normalize.py::test_blocks_split_product_copy_relations_and_policy`、`test_availability_channel_values_are_not_stock`、`test_pipeline.py::test_missing_brand_reason_conflicts_with_present_brand` |
| 合成示例回归 | `test_golden_examples.py::test_examples_reproduce_csv_and_task_result` |

## D04 执行器证据

- `test_execution.py::test_fixture_rule_runs_and_exports`：本地 HTTP fixture，规则 → 2 商品采集 → 账本 → D02 导出。
- `test_execution.py::test_cli_run_command`：同一 fixture 走 `ecom-crawler run`。
- `tests/test_browser.py`：本地 JS 商品页，静态 HTML 不含名称／价格，浏览器渲染后 1／1 有效；断言 task result 的浏览器字段、导出 CSV、资源表清空、profile 删除和 PID 退出。
- `tests/test_browser_actions.py`：本地追加型列表，`load_more` 与 `infinite_scroll` 各 6／6；非法 schema 版本和静态 navigation 被拒绝。
- `tests/test_hybrid.py`：fake adapter + 本地商品页，覆盖 hybrid discovery → 3／3 商品导出、discovery URL 列表、adapter 失败和 entrypoint 校验。
- `experiments/d04/production/README.md`：`familidoo` 6 商品、7 请求、7 秒，CSV 与 D05 字节一致。
- `experiments/d07/browser-mercerine/`：mercerine 首页 503 挑战壳，浏览器渲染后 3／3 商品（EUR）；同一浏览器会话；强杀 worker 后新 worker 接管，遗留 Chromium PID 终止、profile 删除、资源表清空，任务重跑完成。
- `experiments/d07/browser-listing/`：`scrapingcourse.com` 公开练习页，`load_more` 1 次点击后 24 条、`infinite_scroll` 2 次滚动后 36 条，均取前 15 个商品、15／15 有效。

## 已知限制

- 当前有 T1 契约／单元测试和本地 HTTP fixture 集成；D03／A08／D04 有真实站点证据，但不是 T4 生产验收。浏览器路径另有本地 JS fixture、mercerine 真实站点和强杀接管证据。
- `runtime/`、`executor/` 从 R06 抽取；静态和浏览器两类 fetcher 共用同一 runner，浏览器任务逐条串行执行。租约和资源登记已支持多 worker 进程，但浏览器实例配额和跨机租约未接入。控制面支持暂停／恢复／取消。
- 浏览器 `load_more`／`infinite_scroll` 只支持追加型列表；内部滚动容器（`container`）已有本地 fixture（6／6）。虚拟列表不扩声明式 primitive，走 hybrid adapter：adapter discovery 已接入并有本地端到端 12／12；更复杂的内部滚动、任意点击序列和表单提交未实现。
- `run` 已接入 SQLite 任务账本；`export` 仍可独立使用 `task.json` + `candidates.jsonl`，不依赖账本。
- `description.blocks` 的 `kind` 由提取端标注；本层不按关键词猜测政策或适配区块。
- `description_status` 必须由提取端显式给出；本层不从正文长度或选择器命中情况推断完整／未提供。
- 单一分隔符后三位数字的价格必须带 `locale` 才能判定；缺省时按 `AMBIGUOUS_PRICE` 排除，不猜。
- `discovered_urls`、待处理数和导航数由调用方或运行时提供；导出层不构造全站分母。
- `outcome` 是推导值，不接受调用方直接覆盖。
- `schemas/` 目前随仓库分发，尚未打进 wheel；安装包与 schema 分发在 R14 处理。
