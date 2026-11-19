# skatepro.es 样本与证据

- `robots.txt`：2026-11-19 抓取的原文（站点声明的 sitemap、disallow 与 `Crawl-delay: 10`）。方案据此设定 10 秒间隔。
- 商品页 HTML、sitemap 全文和分类页原文均未保存：`docs/08` 默认不保存整页原文，且本方案不依赖离线重放。
- 抽取证据保存在 `diagnostics/<run-id>/products.jsonl`：每个商品的 `variant_prices`（sku／size／color／price／currency／availability）、所选变体、页面显示价、正文来源容器与清洗后长度、分类路径、选项维度。
- 发现证据保存在 `diagnostics/<run-id>/sitemap-summary.json` 与 `selected_urls.json`；两份试跑使用同一抽样规则，商品集合完全一致。
- 冒烟与超时证据：`diagnostics/smoke-2products/`（首次导航 45s 超时后重试成功）、`diagnostics/smoke-3products/`（中止脚本后 4 个请求、0 重试）。
