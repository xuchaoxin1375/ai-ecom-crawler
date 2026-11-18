# 诊断目录说明

| 路径 | 内容 | 是否计入主结果 |
| --- | --- | --- |
| `events.json` | 主试跑的 429/退避事件（1 次 429，60s 后重试成功） | 是 |
| `run-meta.json` | 主试跑请求统计、页面状态、选中 30 个商品、首有效时间 | 是 |
| `scrapy.log` | 主试跑 Scrapy 日志 | 是 |
| `excluded_products.csv` | 主试跑业务排除；只有表头（本样本无零价/负价/无价/缺图商品） | 是 |
| `failed_products.csv` | 主试跑技术失败；只有表头（30 个全部有效） | 是 |
| `pending_products.csv` | 主试跑已选中但未处理；只有表头（30 个全部处理） | 是 |
| `run-001/` | 主试跑输出的归档副本（valid.csv、task-result.json、诊断、日志） | 是（副本） |
| `rerun/` | 第二次线上执行：0 valid、30 failed、`ACCESS_DENIED`；失败记录在 `rerun/diagnostics/failed_products.csv` | 否（复跑证据） |
| `fixture-validation/` | 本地 HTTP fixture 的链路验证；`source_url` 是 127.0.0.1，不是线上结果 | 否（测试证据） |

主 `valid.csv` 只包含主试跑的 30 个有效商品。零价、失败、排除记录不会写入该文件；本样本主试跑没有这些记录，复跑失败记录单独保留。
