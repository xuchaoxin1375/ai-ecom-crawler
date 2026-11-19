# Scrapling／javaestate 运行复核

## 产物核对

- `valid.csv`：22 列与 `02` 一致，30 行、30 个唯一 `source_url`；价格 11.10～132.99，全部正价、USD；市场／语言 US／en-US。
- 正文 30 条全部 `complete`，长度 134～812 字符；未发现 `<script>`、内联事件、`style=` 或 `<iframe>`；分类和品牌非空。
- `task-result.json` 计数不变量成立，`in_flight_products = 0`；状态 `FINISHED`／`PARTIAL`／`BUDGET_EXHAUSTED`。
- `manifest.yaml` 的 `08` 必需字段均存在；`run.py` 只是入口，实际引擎在 `javaestate_scraper/runner.py`，使用 `scrapling.FetcherSession`，不是普通 requests 替代。
- 修复任务：`tax_basis` 从常量改为按公开 `variants[*].taxable` 提取，30 行中 28 行变化；同 URL 复跑 30 有效、0 排除、0 失败，业务字段一致。
- 主运行 34 个请求、51.12 秒、无 429／403／5xx；同方案 `run-002` 复跑通过，运行期 LLM 为 0。

## 与契约的差异

- `task-result.json` 的 `coverage.status` 写 `PARTIAL`，但分母是完整商品 sitemap（707），按 `09` 应为 `KNOWN`（30／707，剩余未处理）。相同的 30／706 情况在 Scrapy 记录中用了 `KNOWN`，两个框架口径不一致。
- `discovered_urls = 33` 包含入口和 sitemap 请求，和 `09` 的“业务网址”口径不完全一致；不影响有效商品数，但计数解释需统一。
- `manifest.yaml` 未做机器解析校验（环境没有 YAML 解析器），只做了人工逐行检查；不满足“执行端可机器校验”的理想状态。
- 30 个样本全部单变体、全部有 Product JSON-LD、全部完整正文；多选项、部分正文、缺价、429 退避只有离线测试或构建诊断，没有真实样本触发。
- 网络出口未独立测量，代理变量值为空但记录为“存在”；本轮按直连记录，存在不确定性。
- 实际模型变体为 `max`（子代理默认），与后续计划的 `high` 不一致，需按轮次统一处理。

## 与 Scrapy 的可比性

Scrapy 主运行因商品 HTML 429 改用公开目录 JSON，正文全部为部分提取；Scrapling 在同一站点取得 30 个商品 HTML，正文全部完整。差异同时受执行时间、站点限流和实现路径影响，不能单独归因于框架；报告中必须并列说明访问窗口，不能把正文完整率直接当成框架能力。

## 判断

Scrapling 本轮在数据完整性和正文质量上明显好于 Scrapy 本轮，且完成了修复任务与同方案复跑；但样本仍是有界 30 个商品，`coverage.status` 不符合 `09`，manifest 未机器校验。作为首次运行记录可用，不能写成稳定可复跑或全站覆盖证明。
