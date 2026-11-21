# 虚拟列表 hybrid adapter 原型（2026-11-22）

## 目的与边界

虚拟列表在滚动时**替换** DOM 行，最终页面只保留最后一批；等滚到底再读最终 DOM 会漏掉前面的商品。按 [ADR 0007](../../../docs/adr/0007-规则层与爬虫框架边界.md)，这是 C2 复杂交互，应走 `hybrid` adapter，而不是继续扩声明式 `load_more`／`infinite_scroll`。

本目录验证两层：

- 定义一个可执行的 adapter 子进程契约：输入任务上下文 JSON，输出 NDJSON；
- 用 Patchright 在本地虚拟列表 fixture 上逐批采集，按稳定 ID 累积，证明“替换 DOM”不会丢批次；
- `app run` 已接受 `kind: hybrid` 的 `discovery.sources[].type=adapter`：adapter 只负责 C2 discovery，商品页仍由 `fetch`／`extract` 的声明式部分抓取和提取；adapter 不拥有任务状态、计数或最终验收。

`manifest.example.yaml` 是完整可加载的 hybrid 方案示例；`run_app_demo.py` 用真实 adapter 跑端到端本地任务。

## 本地 fixture

`fixture.py` 提供 12 个商品、每批 3 个的虚拟列表：

- 初始只渲染 `p1`–`p3`；
- 每次滚动到底部替换为下一批，并把 `scrollTop` 归零；
- 最后一批 `p10`–`p12` 不再变化，用于验证“连续无新 ID”停止。

`run_demo.py` 启动 fixture、生成上下文并调用 adapter，把 NDJSON 写入 `evidence.ndjson`。

## 结果

`evidence.ndjson` 的摘要：

| 项 | 结果 |
| --- | --- |
| 批次 | 5 批（初始 1 批 + 4 次滚动） |
| 稳定 ID | `p1`–`p12`，12 个唯一 ID |
| 商品 URL | 12 个唯一 URL，无重复 |
| 停止 | `NO_NEW_ITEMS`（最后一批重复，连续无新 ID） |
| 请求 | 1 次列表页请求；未抓商品页 |
| 墙钟 | 约 0.9 秒（本机 headless） |
| 浏览器 | Patchright Chromium，headless；任务结束关闭 browser 和 Playwright |

关键行：

```json
{"event": "batch", "batch": 0, "ids": ["p1", "p2", "p3"], "new": 3, "total": 3}
{"event": "batch", "batch": 1, "ids": ["p4", "p5", "p6"], "new": 3, "total": 6}
{"event": "batch", "batch": 4, "ids": ["p10", "p11", "p12"], "new": 0, "total": 12}
{"event": "discovered", "count": 12, "urls": ["http://127.0.0.1:.../product/p1.html", "..."]}
{"event": "done", "stop": "NO_NEW_ITEMS", "batches": 4, "items": 12, "requests": 1, "url_changes": 0}
```

这不是基准站证据，也不是全量保证；它只证明虚拟列表逐批累积和停止条件在本地 fixture 上成立。

## app run 端到端结果

`run_app_demo.py` 启动同一 fixture，把 `adapter.py` 和 `manifest.example.yaml` 复制到临时方案包，再调用 `ecom_crawler.execution.run_and_export`：

- adapter 作为 `app run` 的子进程执行，4 次滚动后返回 12 个 URL；
- app 用静态 fetcher 抓取 12 个商品页并导出 9 列 CSV；
- `valid_products=12`、`excluded=0`、`failed=0`；
- `task-result.json` 的 `runtime.adapter` 记录 `discovered=12`、`added=12`、`skipped=0`、`stop=NO_NEW_ITEMS`、`batches=4`、`requests=1`、`elapsed_ms` 约 0.9 秒；
- `runtime.adapter.profile_mode=ephemeral`、`profile_dir=null`、`profile_removed=null`；任务目录不产生 `adapter-browser-profile`。需要持久会话的规则显式设 `profile_mode: task`，由 `test_hybrid.py` 覆盖注册和清理。

证据：`app-evidence/virtual-list-app-001/`。端口是临时端口，复跑会生成新的端口和任务目录。

## Adapter 契约（v1 草案）

### 调用

`app run` 通过 `runtime.entrypoint` 启动子进程；当前实现等价于：

```text
python adapter.py --context /path/to/context.json
```

- 工作目录是方案包根目录；`entrypoint` 用相对路径。
- stdout 只放 NDJSON，一行一个事件；stderr 留给日志和诊断。
- 退出码：`0` 成功并已输出 `done`；`2` 上下文无效；`3` 浏览器或运行期失败。
- 失败时输出 `error` 事件，不输出 `done`；调用方丢弃该任务的半成品结果。
- adapter 不拥有任务状态、计数、暂停／取消和最终验收；不绕过登录、付费、401／403、验证码或挑战页。
- `app run` 设置子进程超时并保存 `adapter-context.json`／`adapter.ndjson`；超时按进程组终止（Windows `taskkill /T`，POSIX `killpg`）。adapter 正常结束时自己关闭 browser，但尚未把 Chromium 纳入 `task_resources`。

### 输入上下文

`context.example.json` 是完整示例。必填字段：

| 字段 | 说明 |
| --- | --- |
| `entry_url` | 列表入口，必须是绝对 http(s) URL |
| `advance.item_selector` | 当前批次商品行的 CSS 选择器 |
| `advance.id_attribute` | 稳定 ID 属性，默认 `data-id`；缺失时回退到 `data-product-id`、`href` 或文本 |
| `advance.container` | 滚动容器选择器；为空时滚 window |
| `advance.mode` | `scroll`（默认）或 `wheel` |
| `advance.settle_ms` | 每次滚动后的等待时间 |
| `advance.no_new_stop` | 连续多少批没有新 ID 就停止 |
| `limits.max_items` | 唯一商品上限 |
| `limits.max_batches` | 滚动批次上限（不含初始批次） |
| `limits.max_seconds` | adapter 墙钟上限 |

可选：`plan_id`、`plan_version`、`adapter_id`、`adapter_version`、`task_id`、`task_type`、`scope.include`／`exclude`、`browser.headless`／`timeout_ms`／`locale`／`timezone`／`wait_state`（默认 `attached`，避免被隐藏的重复卡片阻塞）。`browser.profile_mode` 默认 `ephemeral`（临时 context，不落盘、不清理）；显式设 `task` 时 app 才传入任务级 `browser.profile_dir`，adapter 用 persistent context 启动，正常退出后由 app 登记并删除该目录。

### 输出事件

| 事件 | 关键字段 | 说明 |
| --- | --- | --- |
| `start` | `adapter_id`、`adapter_version`、`entry_url`、`limits` | 开始执行 |
| `batch` | `batch`、`ids`、`new`、`total`、`url` | 每个当前批次；`ids` 是当前 DOM，`new` 是新增唯一 ID 数 |
| `discovered` | `count`、`urls` | 成功完成后一次性给出唯一 URL，按首次出现顺序 |
| `done` | `stop`、`batches`、`items`、`requests`、`elapsed_ms`、`start_url`、`final_url`、`url_changes`、`urls` | 终止原因和资源统计 |
| `error` | `reason`、`failure_class`、`detail` | 结构化失败；无 `done` |

`stop` 取值：`NO_NEW_ITEMS`、`MAX_ITEMS`、`MAX_BATCHES`、`MAX_SECONDS`、`NO_ITEMS`。

### 与声明式 `infinite_scroll` 的区别

| 项 | 声明式 `infinite_scroll` | 本 adapter |
| --- | --- | --- |
| DOM 形态 | 追加型，最终 DOM 含全部条目 | 虚拟列表，只保留当前批次 |
| 采集时机 | 滚完读最终 DOM | 每批读取当前 DOM，按 ID 累积 |
| 规则层 | YAML `advance` | 方案包内 adapter 代码 |
| 适用层级 | C1 | C2 |

## 复跑

```powershell
python -m uv run --project app --extra dev python experiments/d07/virtual-list-hybrid/run_demo.py
python -m uv run --project app --extra dev python experiments/d07/virtual-list-hybrid/run_app_demo.py
python -m uv run --project app --extra dev python -m unittest discover -s experiments/d07/virtual-list-hybrid -v
python -m uv run --project app --extra dev python -m unittest app.tests.test_hybrid -v
```

`run_demo.py` 只跑 adapter；`run_app_demo.py` 会重写 `app-evidence/virtual-list-app-001/`；测试使用临时上下文和临时 fixture，不写仓库证据。

## 缺口

- `app run` 已支持 adapter discovery，超时按进程组终止；但 adapter 的浏览器实例和临时目录尚未登记到 `task_resources`，正常退出后的孤儿扫描仍需补。
- 未在真实基准站验证；虚拟列表的稳定 ID 属性、滚动容器和终止文案因站而异，需要逐站配置。
- 未实现浏览器实例配额和跨进程资源配额；跨机租约为 v1 外。
- 未处理登录、挑战页、私有 XHR、网络重放或多步状态；`app run` 目前只支持 adapter 返回 URL 后由声明式 `fetch`／`extract` 处理商品页。

## 文件

- `adapter.py`：最小虚拟列表 adapter（Patchright，NDJSON）。
- `fixture.py`：12 项、每批 3 项的替换式虚拟列表 fixture。
- `test_adapter.py`：本地 fixture 12／12、无重复、`NO_NEW_ITEMS` 停止；无效上下文返回 2。
- `run_demo.py`：只运行 adapter，生成 `evidence.ndjson`。
- `run_app_demo.py`：启动 fixture、跑 `app run` 端到端，生成 `app-evidence/`。
- `evidence.ndjson`：adapter 本机 headless 运行证据。
- `context.example.json`：任务上下文示例。
- `manifest.example.yaml`：可加载的 `kind: hybrid` 方案示例。
- `app-evidence/virtual-list-app-001/`：adapter + app 提取的 12／12 证据。
