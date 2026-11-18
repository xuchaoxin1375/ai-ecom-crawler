# Scrapy／javaestate 运行复核

## 产物核对

- `valid.csv`：22 列与 `02` 完全一致，30 行，30 个唯一 `source_url`；价格全部为有限正数（11.10～132.99），币种均为 USD，市场／语言均为 US／en-US。
- `description_status` 全部为 `partial`，`partial_reason` 均非空，`missing_reasons` 均可解析为 JSON 对象。
- `task-result.json`：`FINISHED`／`PARTIAL`／`BUDGET_EXHAUSTED`；计数不变量成立，`in_flight_products = 0`；覆盖 30／706，676 个待处理。
- `manifest.yaml`：`08` 的必需字段均可检测到，`status=candidate`。
- 运行期 LLM 调用为 0；主运行 6 个请求、69 秒。

## 与规格的差异

- `revisions` 在指标 JSON 中写 0，`implementation_revisions` 写 6；评分表按实现修订 6 记录，后续统一用后者。
- `first_valid_product_s=3192`、`first_plan_s=1760` 以构建开始 `2026-11-18T22:37:00Z` 为起点，不是主运行开始时间；评分表已注明。
- 构建期模型调用、工具错误和文档查询未单独埋点，评分表记 `unknown`，不估算。
- `13` 要求的“增加字段或修复选择器”修复任务未执行；本轮只有首个方案、主运行和一次复跑。
- 商品 HTML 在构建期与复跑时遭遇 429，主运行改用公开 `products.json`；所有正文因此只能算部分提取。
- 同一方案的主运行成功，第二次线上复跑在 429 窗口内失败（0 有效／30 失败，`ACCESS_DENIED`）；两次结果并列保留，未覆盖。

## 判断

本次可作为 Scrapy 的首个有界运行记录：数据合同和计数成立，但正文完整性受站点限流限制，复跑稳定性失败，修复任务缺失。后续框架遇到同类 429 时按同样口径记录，不因主运行成功就写成稳定可复跑。
