# diagnostics — 文件语义

| 文件 | 含义 |
| --- | --- |
| `scrapy.log.txt` | 最近一次正式运行的 Scrapy 日志（INFO 级）；仓库 `.gitignore` 忽略 `*.log`，故证据副本文本后缀为 `.log.txt` |
| `run-meta.json` | 运行元数据：任务结果、请求统计、选中 URL、分类探针、事件、错误 |
| `events.json` | 429 退避/放弃事件（本次为空） |
| `failed_products.csv` | 技术失败候选：访问、抽取、校验错误；与业务排除分开 |
| `excluded_products.csv` | 业务排除：零价/无价/非法价、缺主图、币种无证据 |
| `pending_products.csv` | 样本内已选中但未在停止前处理的 URL；样本外的剩余候选见 `task-result.json` 的 `counts.pending_products` |
| `valid_internal.json` | 有效商品的内部追溯：正文状态与原因、字段缺失、价格/税价口径、币种证据、选项跳过维度、JSON-LD 类型 |
| `attempt-001-403/` | 尝试 001 的原始日志与结果（sitemap 403，未产出数据），保留失败证据 |
| `run-001/` | 修复前主运行的 valid.csv、task-result、日志与内部记录（24 有效 / 6 失败） |
| `smoke-2products/` | 修复后 2 商品烟测（验证诊断写出），不计入正式计数 |

`valid.csv` 只含 9 列业务字段；正文状态、缺失原因、市场、库存与税价口径不在 CSV 重复，
由此目录和 `task-result.json` 的 `quality_exceptions` 承载。
