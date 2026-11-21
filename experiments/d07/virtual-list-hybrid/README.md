# 虚拟列表 hybrid adapter 原型（2026-11-22）

## 目的与边界

虚拟列表在滚动时**替换** DOM 行，最终页面只保留最后一批；等滚到底再读最终 DOM 会漏掉前面的商品。按 [ADR 0007](../../../docs/adr/0007-规则层与爬虫框架边界.md)，这是 C2 复杂交互，应走 `hybrid` adapter，而不是继续扩声明式 `load_more`／`infinite_scroll`。

本目录只做第一层验证：

- 定义一个可执行的 adapter 子进程契约：输入任务上下文 JSON，输出 NDJSON；
- 用 Patchright 在本地虚拟列表 fixture 上逐批采集，按稳定 ID 累积，证明“替换 DOM”不会丢批次；
- 不修改 `app run`，不新增 schema 推进类型，不把 adapter 代码 import 进主服务。

`app run` 目前仍只接受 `kind: declarative`；本目录的 `manifest.example.yaml` 是契约示例，不是可被 `app run` 直接消费的方案包。

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

## Adapter 契约（v1 草案）

### 调用

```text
python adapter.py --context /path/to/context.json
```

- 工作目录是方案包根目录；`entrypoint` 用相对路径。
- stdout 只放 NDJSON，一行一个事件；stderr 留给日志和诊断。
- 退出码：`0` 成功并已输出 `done`；`2` 上下文无效；`3` 浏览器或运行期失败。
- 失败时输出 `error` 事件，不输出 `done`；调用方丢弃该任务的半成品结果。
- adapter 不拥有任务状态、计数、暂停／取消和最终验收；不绕过登录、付费、401／403、验证码或挑战页。

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

可选：`plan_id`、`plan_version`、`adapter_id`、`adapter_version`、`task_id`、`task_type`、`scope.include`／`exclude`、`browser.headless`／`timeout_ms`／`locale`／`timezone`。

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
python -m uv run --project app --extra dev python -m unittest discover -s experiments/d07/virtual-list-hybrid -v
```

`run_demo.py` 会重写 `evidence.ndjson`；测试使用临时上下文和临时 fixture，不写仓库证据。

## 缺口

- `app run` 尚未接受 `kind: hybrid`，也没有把 adapter 的 `discovered` 事件接回任务账本；本目录只定义契约和验证执行器。
- 未在真实基准站验证；虚拟列表的稳定 ID 属性、滚动容器和终止文案因站而异，需要逐站配置。
- 未实现浏览器实例配额、跨进程资源配额和跨机租约；adapter 目前自己关闭 browser，尚未登记到 `task_resources`。
- 未处理登录、挑战页、私有 XHR、网络重放或多步状态。

## 文件

- `adapter.py`：最小虚拟列表 adapter（Patchright，NDJSON）。
- `fixture.py`：12 项、每批 3 项的替换式虚拟列表 fixture。
- `test_adapter.py`：本地 fixture 12／12、无重复、`NO_NEW_ITEMS` 停止；无效上下文返回 2。
- `run_demo.py`：生成 `evidence.ndjson`。
- `evidence.ndjson`：本机 headless 运行证据。
- `context.example.json`：任务上下文示例。
- `manifest.example.yaml`：`kind: hybrid` 契约示例，尚不能被 `app run` 消费。
