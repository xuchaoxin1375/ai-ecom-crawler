# Scrapling／skatepro 运行复核

## 产物核对

- `valid.csv`：9 列与新合同一致，30 行、30 个唯一 `source_url`；价格 0.95～399.95 EUR，全部正价；主图完整，26 行有公开选项。
- `task-result.json`：`FINISHED`／`PARTIAL`／`BUDGET_EXHAUSTED`；计数不变量成立，`in_flight_products=0`；覆盖分母 6660，覆盖 30。
- `quality_exceptions` 9 条，均为正文完整但缺可空字段（规格表 7 条、公开选项 4 条，部分重合），字段结构符合 `09`。
- `manifest.yaml` 的 `08` 必需字段均存在；运行期零 LLM，34 个请求全部 200，无 429、无重试。
- 修复任务：新增 `availability`，从 JSON-LD `offers.availability` 聚合并与 PHP2JS `stock_level` 交叉核对；7.5 分钟，复跑 30／30 有效，共享字段 0 差异，9 列 CSV 不变。
- 本会话没有使用 `scrapling-official` skill：会话记录中没有该 skill 的加载或调用，运行仍属“无 skill”treatment。

## 与契约的差异

- `coverage.status` 又写成 `PARTIAL`，但分母是完整 sitemap（6660），按 `09` 应为 `KNOWN`；这是连续两轮出现的同一实现偏差，不能当站点差异解释。
- `DEFAULT_PLAN_VERSION` 在 v1 就写成最终值，`run-001` 的版本标签显示为 `2026.11.19-2`；审计中缺少 `availability` 可证明实际跑的是 v1，日志未改写。这是版本追溯缺陷，不是数据错误。
- `manifest.yaml` 只做顶层键扫描，没有 YAML 解析校验。
- `run-001` 的根级 `valid.csv` 被修复复跑覆盖，只保留审计与汇总；同方案复跑和字段对比仍可核对。
- 站点根据出口把配送地提示为美国，但报价保持 EUR、JSON-LD 配送和退货地区为 ES；未设国家 Cookie、未换汇，市场和币种证据需要并列说明。
- 未做干净环境导入复跑（A10），峰值内存未测。

## 与 Scrapy 的可比性

两者都从 sitemap 分母出发，但发现路径不同：Scrapy 取 sitemap 前 30 个 URL；Scrapling 从入口分类网格取 30 个商品，再用 sitemap 作为分母。因此商品样本不完全相同，价格区间和正文完整率不能逐项对齐。Scrapling 的首个有效商品更快（15.6 分钟对 25.2 分钟），但这一差异同时包含发现路径、站点响应和实现差异。

## 判断

Scrapling 本轮在 9 列合同下完成了 30 个有效商品、修复任务和复跑，数据完整性好；但 `coverage.status` 和 `plan_version` 两处追溯问题必须保留在报告中。它没有使用官方 skill，因此仍可与同轮无 skill 的 Scrapy 对比，不能与后续启用 skill 的 Scrapling 会话混算。
