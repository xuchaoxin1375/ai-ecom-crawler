# R06 通用执行器与任务运行时原型

## 目的与边界

R06 验证两件事：

- 执行端只读 `manifest.yaml` 和声明式规则，就能跑完一个站，不再为站点写专用 `run.py`；
- 规则可以按任务类型停在 discovery，也可以继续做 product；多个任务可以并行，任务账本独立。

这是原型，不是生产执行器。当前支持：

- `kind: declarative`；
- `discovery.strategies: ["entry_links"]`，从一个入口页取商品链接；
- 静态 HTTP（Scrapling `FetcherSession`），请求间隔不低于 1000ms；
- 字段回退类型：`json_ld`、`css_text`、`css_attr`、`css_html`、`title`、`breadcrumb`、`option_groups`、`price_pair`、`canonical`、`constant`；
- 9 列业务 CSV、`task-result.json`、`run-summary.json` 和诊断文件；
- 任务账本、discovery／product 两种任务、SQLite 工作项检查点、并行 worker、暂停／恢复／取消；
- `failure_class`（`transient`／`permanent`／`blocked`）、任务级 `max_attempts`、临时失败退避；
- JSON／CSV 原子替换、JSONL 单次追加＋fsync、残缺尾行修复；
- 启动对账（`IN_FLIGHT` 重置或耗尽失败、方案版本校验、临时文件清理）和 `plan_*` 输出。

暂不支持 sitemap／分类分页、浏览器渲染、登录、跨进程队列、Web UI 和完整 NDJSON 协议；这些不在 R16 v0 范围内。

方案语义补充：`discovery.product_url_patterns` 和 `scope.exclude` 按正则匹配；`scope.include` 也按正则匹配 URL 的 path，不再使用 glob。`docs/08` 与 `docs/19` 已统一为这一语义。运行设计见 [`docs/19`](../../docs/19-采集规则与任务运行时.md)。

## 目录

| 路径 | 内容 |
| --- | --- |
| `executor/` | 单次运行执行器：manifest 校验、发现、获取、提取、清洗、输出 |
| `runtime/` | 任务运行时：SQLite 账本、工作项、discovery／product、并行 worker |
| `plans/familidoo.yaml` | 单次运行的站点声明式方案 |
| `plans/familidoo-runtime.yaml` | 运行时规则包；discovery 和 product 共用 |
| `familidoo/` | 单次运行的 9 列 CSV、任务结果和 `r06-run-001`～`004` 诊断 |
| `runtime-demo/` | 两个任务并行：discovery URL 清单和 product 9 列 CSV |
| `tests/` | 无网络契约、提取、任务账本和运行时测试 |
| `tools/validate_output.py` | 单次运行输出校验器 |
| `tools/validate_runtime.py` | 运行时 demo 校验器 |

## 运行

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/run.py `
  --plan experiments/r06/plans/familidoo.yaml `
  --out-dir experiments/r06/familidoo `
  --label r06-run-004
```

复跑请使用新的 `--label`，保留已有诊断；不要覆盖 `r06-run-001`～`003`。根目录的 CSV 和 JSON 是最近一次运行，诊断目录按 label 分开。

测试：

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python -m unittest discover -s experiments/r06/tests -v
```

规则包结构校验（`jsonschema` 未安装时该测试跳过）：

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  --with "jsonschema>=4.23" `
  python -m unittest discover -s experiments/r06/tests -p "test_schema.py" -v
```

校验输出：

```powershell
python experiments/r06/tools/validate_output.py --dir experiments/r06/familidoo
```

## 试点结果（`r06-run-001` 构建观测，`r06-run-002` 复跑）

| 项 | 值 |
| --- | --- |
| 站点与范围 | `familidoo.fr` 首页商品链接；FR／fr-FR／EUR |
| 有效／排除／失败 | 6／0／0（各次运行相同） |
| 商品候选 | 6（入口页只展示 6 个商品链接；方案上限 20） |
| 请求 | 8（robots 1、入口 1、商品 6），0 重试（各次运行相同） |
| 运行墙钟 | 16.77s（`r06-run-001`）；19.8s（`r06-run-002`）；16.31s（`r06-run-003`，最终代码）；18.38s（`r06-run-004`，正则语义复核） |
| 首次有效商品 | 2026-11-20T06:13:35Z（`r06-run-001`） |
| 方案构建起点 | 2026-11-20T06:11:45Z（开始写站点方案） |
| `first_valid_product_s` | 110.0s（约 1 分 50 秒；仅 `r06-run-001`） |
| 复跑业务 CSV | `r06-run-001`～`004` 的 `valid.csv` SHA-256 相同：`D70458FD0177C39BBC4D4420B6A75D3C0EED47E5042C819359BA9F413EFD6D1E` |
| 运行期 LLM 调用 | 0 |
| 浏览器 | 未启动 |
| 描述状态 | 6／6 `complete` |
| 价格口径 | 6／6 预税价；展示价 TTC 与采用价相差 20%，例如 615.00 → 512.50 |
| 品牌 | 6／6 页面未公开 manufacturer，留空并记 `NOT_PROVIDED` |
| 任务结果 | `outcome=COMPLETED`、`stop_reason=NATURAL_END`、`coverage=PARTIAL` |

根目录的 `valid.csv`、`task-result.json`、`run-summary.json` 是最近一次运行（当前为 `r06-run-004`）；`r06-run-001` 的构建观测值记录在上表，`valid.csv` 副本和诊断保留在 `diagnostics/r06-run-001/`，`r06-run-002/`、`r06-run-003/` 和 `r06-run-004/` 也保留各自的任务结果与运行摘要。`r06-run-004` 是 URL 正则语义复核，业务 CSV 与前三次数字节一致。这些运行只能说明同方案同环境可复现，不是独立复跑、漂移测试或跨环境验证。

字段命中路径（6／6 一致）：

| 字段 | 实际来源 |
| --- | --- |
| `name` | `h1[itemprop=name]` |
| `price.amount` | PrestaShop `product:pretax_price:amount`／`product:price:amount` 对，取较小者 |
| `price.currency` | `product:pretax_price:currency` |
| `primary_image_url` | `og:image` |
| `description_html` | `div.product_description_container` |
| `category` | 面包屑最深非首页项 |
| `source_url` | `link[rel=canonical]` |

`COMPLETED` 只表示入口页这个有界范围处理完了；`coverage=PARTIAL` 表示不是全站覆盖。

## 和 R04 的差异

| 项 | R04 | R06 |
| --- | --- | --- |
| 执行方式 | 站点专用 `run.py` | 通用执行器读 `plans/familidoo.yaml` |
| `kind` | `program` | `declarative` |
| 站点代码 | 有 | 无 |
| 构建观测 | 404.0s，含一次失败和修复 | 110.0s，首次运行即通过 |
| 运行墙钟 | 13.28s | 16.77s |
| 样本 | 首页 6 个 | 首页 6 个 |

R06 的方案构建时间不能直接和 R04 比：R06 的通用执行器是在同一会话里先写好的，110 秒只计“写站点方案到首个有效商品”，不计执行器开发；R04 的 404 秒计的是站点专用 runner 的构建。两者都不是受控基准，只作过程记录。可以确认的是：**R06 的站点侧不再需要写代码，方案只保留声明式覆盖。**

## 任务运行时 v0（R16 切片）

`plans/familidoo-runtime.yaml` 同时声明 discovery 和 product；任务类型决定停在哪一步。

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/familidoo-runtime.yaml

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

`task list`、`task status`、`task pause/resume/cancel` 使用同一个 `--db`；暂停和取消在工作项边界生效。

### 并行结果

| 任务 | 类型 | 结果 | 请求 | 起止 |
| --- | --- | --- | --- | --- |
| `demo-discovery` | discovery | 6 个 URL，`COMPLETED` | 2（robots＋入口） | 12:26:20–12:26:24 |
| `demo-product` | product | 6 个商品，`COMPLETED` | 8（robots＋入口＋6 商品） | 12:26:20–12:26:38 |

两个任务同一秒启动，discovery 先结束，product 继续；同域请求由全局限速器按 1 rps 串行，输出目录和计数互不污染。`demo-discovery` 没有请求商品页，验证了“只发现网址、不提取商品”的任务类型。

校验：

```powershell
python experiments/r06/tools/validate_runtime.py --root experiments/r06/runtime-demo
```

输出：`OK: runtime demo`，`demo-discovery` 6 URLs、`demo-product` 6 products。

### 运行时测试

无网络测试覆盖：

- 规则加载与非法发现策略拒绝；
- SQLite 任务账本、工作项去重、claim／reset；
- discovery 任务不请求商品页；
- product 任务输出 9 列；
- 两个任务必须同时进入 fetcher（`threading.Barrier`）才继续，验证 worker 并行启动；
- 暂停到 `PAUSED` 后恢复，最终 `COMPLETED`；
- 临时失败重试、重试耗尽、401／403 阻塞分类；
- `IN_FLIGHT` 对账重置、尝试次数耗尽失败、方案版本不匹配；
- `plan_*` 输出和原子写／JSONL 追加。

## 局限

- 入口页只展示 6 个商品，未做 10～20 个随机抽样；6／6 是小样本全量，不是全站覆盖。
- 只验证一个站点、一次运行；没有独立复跑和跨环境导入。
- 只支持静态 HTML；没有浏览器、登录、挑战处理或 JavaScript 渲染。
- 只支持一个入口页；没有 sitemap、分类分页、公开 JSON 或详情补全。
- 运行时只有单 worker；有逻辑对账和失败分类测试，但没有跨进程锁、队列或真实进程崩溃演练；暂停／恢复只在无网络测试中验证过。
- 单次运行执行器没有任务控制；任务控制只在 `runtime/` 中实现。
- 没有 Web UI；`task list/status` 是 CLI。
- `pyyaml` 通过 `uv run --with` 临时提供；共享基线锁在 `baseline/`，尚未并入 Scrapling 项目的锁文件。

## 下一步

- 用第二个站复测“只写方案、不写代码”，避免把单站结果当成通用结论。
- 增加 `sitemap` 或分类入口，才能做 10～20 个商品的随机抽查和更完整的范围。
- 把“两个任务并行 + 同域限速 + 暂停／取消”做成真实站点的验收记录，而不只用 fake fetcher。
- 补跨进程 worker 或至少一个单 worker 的崩溃恢复演练。
- 维护、漂移和长期稳定性仍后置（J08）；本轮不据此判断维护成本。
