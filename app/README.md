# 生产应用（app/）

本目录是 monorepo 中生产应用的承载位置。当前已落地 **D02 数据合同与导出 CLI**，以及 **D04 v0 静态单进程执行器**：规则包 → 发现／获取／提取 → SQLite 任务账本 → D02 导出。浏览器、跨进程租约、Web UI 和构建会话仍未实现。

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
- `export`、`validate`、`run`、`submit`、`worker`、`pause`、`resume`、`cancel`、`status` 和 `list` CLI 子命令。
- 声明式规则包读取与校验；`entry_links`、`sitemap`、`listing`、`html_index`、`public_json` 发现来源。
- 静态发现、获取、提取、基础重试和 SQLite 任务账本。
- `run` 执行 product 任务并自动接入 D02 导出。
- 单 worker 控制面：`submit` 入队，`worker` 常驻执行，`pause`／`resume`／`cancel` 从另一个进程改账本，runner 在检查点响应并拒收迟到结果。

尚未实现：

- 浏览器／动态渲染、挑战页会话复用和资源回收。
- 跨进程租约；当前只允许一个 `worker` 消费同一账本。
- app 原生状态模型、Web UI 和构建会话。
- 生产级浏览器／进程孤儿回收；R06 的静态单进程能力已抽取，但不是最终形态。

## 布局

- `src/ecom_crawler/`：应用代码。
- `src/ecom_crawler/runtime/`、`executor/`：从 R06 抽取的静态单进程运行时和提取器。
- `src/ecom_crawler/execution.py`、`bridge.py`：执行入口与 R06→D02 转换。
- `schemas/`：候选输入、内部商品记录和任务结果的 JSON Schema。
- `tests/`：T1 契约／单元测试和本地 fixture 集成测试，无外部网络。
- `pyproject.toml`：独立依赖与 `ecom-crawler` 入口。
- `uv.lock`：应用依赖锁定。

## 环境与测试

```powershell
python -m uv run --project app --extra dev python -m unittest discover -s app/tests -t app -v
python -m uv run ruff check app
```

`jsonschema` 是测试依赖；缺失时测试会失败，不会 skip。应用运行依赖包括 `lxml`、`pyyaml`、`scrapling`、`curl_cffi`、`patchright`、`browserforge` 和 `protego`。

## CLI

```powershell
python -m uv run --project app ecom-crawler --version
python -m uv run --project app ecom-crawler run --rule /path/to/rule.yaml --db /path/to/tasks.db --out-root /path/to/tasks --task-id sample-001 --task-type product --max-products 6
python -m uv run --project app ecom-crawler submit --rule /path/to/rule.yaml --db /path/to/tasks.db --task-id sample-002
python -m uv run --project app ecom-crawler worker --db /path/to/tasks.db --out-root /path/to/tasks
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
- `worker` 默认 `--max-tasks 1`，按 `QUEUED` 取任务；Ctrl+C 停止领取新任务并等待已启动任务结束，已取消任务用 `cancel` 处理。
- `pause` 只接受 `RUNNING`，`resume` 只接受 `PAUSED`；重复请求按当前状态幂等返回，非法转移返回 2。
- `status` 和 `list` 是只读入口；`--json` 输出可直接给脚本消费。任务计数仍以 `task-result.json` 和 `docs/09` 为准。
- `export` 默认拒绝覆盖已存在的 `products.csv`／`task-result.json`；需要覆盖时加 `--force`。
- `export` 的退出码表示导出流程是否成功，不表示业务结论；业务结论看 `task-result.json` 的 `outcome`。
- `export` 的输入或任务元数据错误返回 2；`validate` 的校验失败返回 1。

## 执行入口（run）

`run` 读取一个声明式规则包，创建任务并在当前进程执行：

- 规则包：YAML manifest；`rule_id`／`rule_version` 必须与任务一致；支持 `entry_links`、`sitemap`、`listing`、`html_index`、`public_json` 来源。
- 账本：`--db` 指向的 SQLite 文件，记录任务、工作项、状态、尝试次数和失败分类。
- 输出：`<out-root>/<task-id>/` 下有 `task-result.json`、`products.jsonl`、`urls.csv`、`events.ndjson` 等运行时产物；product 任务另有 `app-run/` 和 `export/`。
- 当前是单进程、静态 HTML；浏览器、跨进程租约和资源回收未接入。

## 控制面（submit / worker / pause / resume / cancel）

- `submit` 只创建 `QUEUED` 任务，不启动执行；`worker` 常驻读取账本中的 `QUEUED` 任务。
- `pause` 把 `RUNNING` 改为 `PAUSING`；runner 停止派发新工作，等在途结清后写 `PAUSED`。
- `cancel` 把 `RUNNING`／`PAUSING` 改为 `CANCELLING`；runner 等在途结束，拒绝迟到结果，写 `CANCELLED`。`DRAFT`／`QUEUED`／`PAUSED` 直接进入 `CANCELLED`。
- `resume` 把 `PAUSED` 改回 `QUEUED`，由 `worker` 重新领取；不恢复浏览器内存或旧会话。
- 状态转移校验在 `TaskStore.request_*`，不在 CLI 或页面里重复实现；非法转移和未知任务返回 2。
- `worker` 启动时获取 `<db>.worker.lock` 单实例锁；锁由操作系统在进程退出时释放，残留锁文件不会阻止下次启动。
- 同进程 A20 已覆盖：同域两任务并行，暂停／取消一个，另一个继续并保持独立输出；同域请求共用限速器。
- 跨进程租约、浏览器资源回收和跨进程 A20 仍未实现。
- 证据：`tests/test_control.py` 覆盖状态转移、启动对账和单实例锁；`tests/test_control_flow.py` 覆盖暂停结清、恢复、取消拒收迟到结果、`run_forever` 和同进程 A20。

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
- `experiments/d04/production/README.md`：`familidoo` 6 商品、7 请求、7 秒，CSV 与 D05 字节一致。

## 已知限制

- 当前有 T1 契约／单元测试和本地 HTTP fixture 集成；D03／A08／D04 有真实站点证据，但不是 T4 生产验收。
- `runtime/`、`executor/` 从 R06 抽取，当前是单进程、静态 HTML；浏览器、跨进程租约和浏览器资源回收未接入。控制面已支持单 worker 的暂停／恢复／取消。
- `run` 已接入 SQLite 任务账本；`export` 仍可独立使用 `task.json` + `candidates.jsonl`，不依赖账本。
- `description.blocks` 的 `kind` 由提取端标注；本层不按关键词猜测政策或适配区块。
- `description_status` 必须由提取端显式给出；本层不从正文长度或选择器命中情况推断完整／未提供。
- 单一分隔符后三位数字的价格必须带 `locale` 才能判定；缺省时按 `AMBIGUOUS_PRICE` 排除，不猜。
- `discovered_urls`、待处理数和导航数由调用方或运行时提供；导出层不构造全站分母。
- `outcome` 是推导值，不接受调用方直接覆盖。
- `schemas/` 目前随仓库分发，尚未打进 wheel；安装包与 schema 分发在 R14 处理。
