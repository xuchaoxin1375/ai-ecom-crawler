# Crawlee／javaestate 运行复核

## 产物核对

- `valid.csv`：22 列与旧合同一致，27 行、27 个唯一 `source_url`；价格 5.15～78.99，全部正价、USD；主图和来源网址完整。
- 正文：25 条 `complete`、2 条 `not_provided`；无部分／回退／失败；`missing_reasons` 可解析。
- `task-result.json`：`FINISHED`／`PARTIAL`／`BUDGET_EXHAUSTED`；`coverage.status=KNOWN`，27／706；计数不变量成立，`pending_products=3`、`in_flight_products=0`。
- `manifest.yaml` 的 `08` 必需字段均存在；实现实际使用 `PlaywrightCrawler`、`RequestQueue`、`ThrottlingRequestManager` 和浏览器池。
- 主运行 610 秒、28 个顶层请求、1 次浏览器启动；运行后无 Chromium／Playwright 残留。
- 修复任务：描述选择器命中空占位容器的问题，5.7 分钟修复，16 项测试通过；复跑 27 有效，主运行与复跑共有的 25 个商品业务值完全一致。

## 与契约的差异

- 最终只有 27 个有效商品，3 个在 10 分钟上限内未处理；不能写成 30 个或全站完成。
- `tax_basis` 全部为 `UNKNOWN`，站点未声明含税／未税，已逐行记因，没有猜测。
- 真实样本没有触发 partial／fallback 正文，只有合成契约测试覆盖。
- 构建期普通 HTTP 探测遇到 429，测量运行改用 Chromium 后无 429；两种请求方式不能混为同一计数。
- Crawlee 的节流子管理器曾在仓库根生成 `storage/` 队列目录，运行后已删除；运行级存储隔离是后续改进。
- 构建期 63 分钟，接近 90 分钟盒但未超；主运行 10 分钟是站点上限，不是自然结束。

## 合同变更提醒

本次运行期间，`docs/02` 等文件被外部改为 9 列业务 CSV 加任务报告 `quality_exceptions`；不是本实现或本轮代理修改的。任务规格保留了“本轮继续 22 列、不重跑”的记录，Crawlee 产物按 22 列交付。该变更目前仍在工作区未提交，需确认后再决定是否作为新基线；第 1 轮三份结果都应视为旧 22 列合同证据。

## 判断

Crawlee 本轮完成了浏览器路径的有效采集、资源回收和修复复跑，数据质量与 Scrapling 接近，但有效商品少 3 个、正文有 2 个未提供。它与 Scrapy 的差异不能只归因于框架：Scrapy 在 429 窗口内改走目录 JSON，Crawlee 改走 Chromium；访问路径和观测时间都不同，报告中必须并列说明。
