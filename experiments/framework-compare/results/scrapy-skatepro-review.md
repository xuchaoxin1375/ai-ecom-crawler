# Scrapy／skatepro 运行复核

## 产物核对

- `valid.csv`：9 列与 `02` 的新合同一致，30 行、30 个唯一 `source_url`；价格 0.95～219.95 EUR，全部正价；主图和名称完整。
- `task-result.json`：`FINISHED`／`PARTIAL`／`BUDGET_EXHAUSTED`；计数不变量成立，`in_flight_products=0`；覆盖 `KNOWN`，30／6660。
- `quality_exceptions` 16 条，字段包含 `source_url`、`description_status`、`partial_reason`、`missing_reasons`；全部为部分正文，原因写明规格表区块缺失。
- `manifest.yaml` 的 `08` 必需字段均存在；主运行 33 个请求全部 200，无 429、无重试，运行期零 LLM。
- 修复任务：JSON-LD 读取从只认 `Product` 扩展到 `ProductGroup`，报价和主图从 `hasVariant` 读取；8 分钟，初始 24 有效／6 失败，修复后 30 有效／0 失败。
- 构建期 `/sitemap.xml` 首次 403，补齐与站点一致的请求头后成功；该尝试单独留档，没有混入正式结果。

## 与规格的差异

- S2 的关注点是分类／分页，但分类第二页由 JS 组件加载，静态方案退回 sitemap；因此本轮实际验证的是“sitemap 发现＋商品详情”，分页路径没有真正跑通。这是站点与静态客户端的能力边界，不是字段错误。
- 16 个商品只取得编辑描述，规格表区块缺失，统一标 `partial`；没有用浏览器核对未渲染区块，部分状态成立。
- 未做干净环境导入复跑（A10／D05），也未做人工业务验收；`import_check` 记为 `not_run`。
- 构建期人工探测遇到一次 429，冷却后恢复；正式运行没有 429，`api_errors` 记为构建期 1 次。
- 本轮按新 9 列合同输出，`quality_exceptions` 已进入任务结果；与第 1 轮的 22 列结果不能逐列直接比较。

## 判断

Scrapy 在本站点完成了 sitemap 发现、30 个商品提取和一次有效的 ProductGroup 修复，数据合同和异常索引都成立。限制是静态分页没有跑通、16 个正文部分、未做导入复跑；这些要进入第 2 轮汇总，不能只看“30 个有效”就写成完整通过。
