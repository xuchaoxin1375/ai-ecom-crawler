# run-log — Scrapy 2.20.0 / skatepro.es（S2，第 2 轮 9 列合同）

本记录只写实际执行事实：数字来自 `task-result.json`、`diagnostics/run-meta.json`、
`diagnostics/scrapy.log.txt` 和 `results/scrapy-skatepro.json` 的汇总，不使用模型自报。

## 环境与控制变量

| 项 | 值 |
| --- | --- |
| 框架 | Scrapy 2.20.0 |
| Python | 3.13.13（`python -m uv run --project experiments/framework-compare/scrapy`） |
| 运行入口 | `experiments/framework-compare/scrapy/skatepro/run.py` |
| 市场／语言／币种 | ES／es-ES／EUR |
| 上限 | 30 个商品页或 600s，先到为准 |
| 并发／间隔／重试 | 1／10s（robots `Crawl-delay: 10`）／3 |
| robots | `ROBOTSTXT_OBEY=True`；禁 `/adminshop`、`/static`、`*/catalog`、`*/wishlist` |
| 网络出口 | 系统代理 `HTTP(S)_PROXY=http://localhost:7897`（名称记录；未做抓包或绕过） |
| 运行期 LLM 调用 | 0（抽取全部为确定性 Python） |
| 模型变体 | high |

## 复用范围（本框架内）

- 复用 `scrapy/javaestate/` 的**工程骨架**：`scrapy.cfg`、settings 结构、`run.py` 的
  CLI/指标汇总形态、`pipelines.py` 的 CSV/诊断写出模式，以及 `normalize.py` 中通用的
  HTML 清洗辅助（标签白名单、空标签清理、属性剥离）与 `csv_safe` 公式防护思路。
- 未复制 javaestate 的字段选择器、站点数据源或站点结论；skatepro 的发现、选择器、
  `php2js` 解析、ProductGroup 处理、描述状态判定与选项规则均为本次新写。
- 未读取、未复制、未运行 `scrapling/` 与 `crawlee/` 下的任何实现。

## 时间线与构建成本

| 时间（UTC） | 事件 |
| --- | --- |
| 02:13 | 构建会话起点（`build_started_at`，按会话最早工具活动重建，误差约 ±2 分钟） |
| 02:14–02:27 | 读规格与 docs/02、05、08、09、13、14；站点分诊（robots、sitemap、入口、分类、商品页样本） |
| 02:33 | 首个完整方案落盘（manifest + 代码 + 测试），`first_plan_s = 1229s` |
| 02:33:36–02:33:48 | 尝试 001：`/sitemap.xml` 收到 HTTP 403，立即按访问失败停止（2 请求） |
| 02:37:41–02:43:03 | 主运行：30 个商品页，24 有效 / 6 失败 |
| 02:44–02:52 | 修复任务：ProductGroup 页面修复 + 复跑（`fix_minutes = 8`） |
| 02:46:33–02:51:56 | 修复后复跑：30 有效 / 0 失败 |
| 02:52 | 2 商品 smoke 复跑（独立输出目录），验证诊断写出修复，不覆盖正式结果 |
| 02:56–02:58 | `rebuild_metrics.py` 从输出文件汇总指标（不重新抓取） |

构建期指标（从 `build_started_at` 起算）：

- `first_valid_product_s = 1513`（主运行首个有效商品，02:38:13）
- `first_plan_s = 1229`（02:33:29 方案首次完整落盘）
- `implementation_revisions = 5`

## 发现与获取

- 入口 robots.txt → `Sitemap: https://www.skatepro.es/sitemap.xml`；sitemap 为单个
  urlset（约 725 KB），商品 URL 形态 `/{category_id}-{product_id}.htm`，本次读到
  6660 个唯一商品 URL，按 sitemap 顺序取前 30 个。
- 分类页 `/c2.htm` 只作导航证据：服务端渲染 30 张卡片；`?page=2` 返回同一页面，
  后续分页由 JS `page_load_more` 组件完成，因此静态方案不使用分类分页，也不遍历目录。
- 商品页静态 HTML 已含 JSON-LD、`#product_description`、`#product_specifications`
  和公开的 `php2js` 变体载荷，无需浏览器。
- 主运行请求数 33：robots 1 + sitemap 1 + 分类 1 + 商品 30；无 429、无重试、
  全部 200。尝试 001 的 403 单独保留在 `diagnostics/attempt-001-403/`。

## 主运行结果（plan_version 2026.11.19-1）

- state `FINISHED`，outcome `PARTIAL`，stop_reason `BUDGET_EXHAUSTED`（有界样本）。
- 计数：candidates 6660，processed 30，valid 24，excluded 0，failed 6，
  pending 6630，partial 12。
- 6 个失败全部是 `product_json_ld_missing`（变量商品页只给 `ProductGroup`）：
  `116-3125`、`80-1063`、`57-417`、`61-315`、`61-260`、`206-227`。
  原始日志与 task-result 在 `diagnostics/run-001/`；按“不删失败样本”保留。

## 修复任务（8 分钟，复跑通过）

- 起点 02:44 UTC，通过 02:51:56 UTC；`fix_minutes = 8`。
- 改动：`skatepro/normalize.py` 与 `skatepro/spiders/products.py` 的 JSON-LD 读取
  同时接受 `Product` 与 `ProductGroup`；报价/币种/主图从 `hasVariant[]` 读取；
  `plan_version` 2026.11.19-1 → 2026.11.19-2。
- 复跑（同一 30 个 URL、同一 10s 间隔）：30 有效 / 0 排除 / 0 失败；16 部分描述、
  14 完整描述；请求 33，全部 200。`valid.csv` 与 `task-result.json` 为复跑结果，
  `results/scrapy-skatepro.json` 同时保留 `initial_run` 与 `fix` 两段。
- 修复后另做 2 商品 smoke（`diagnostics/smoke-2products/`），验证诊断文件写出逻辑；
  该次运行不计入正式计数。

## 数据质量核对

- `valid.csv` 30 行、9 列；UTF-8 with BOM、CRLF、最小引号；`description_html`
  逐行可被 HTML 解析，无 `script`/`img`，含规格表；无重复 `source_url`。
- 价格：30 行均为有限正数，币种全为 EUR；币种证据为同一 JSON-LD 报价对象的
  `priceCurrency`（ProductGroup 页面要求所有 variant offer 币种一致）。
- 正文状态：14 完整（编辑正文 + 规格表），16 部分（页面无规格表区块，
  `partial_reason = specifications_section_missing_or_empty`）；无摘要回退、
  无“原站未提供”、无提取失败。16 条部分描述全部进入 `quality_exceptions`。
- 选项：6 个商品有多值公开选项（尺码/颜色），其余为单品；单值维度按规格处理，
  不伪造选项。空 `attributes` 的原因记在 `diagnostics/valid_internal.json`
  （`option_note = NO_PUBLIC_CHOICE`），不作为缺失异常。
- 未纳入 CSV 的追溯字段（正文状态、税价口径 `NOT_STATED`、价格口径、币种证据、
  ProductGroup 类型）保存在 `diagnostics/valid_internal.json` 与任务结果中。

## 错误与访问边界

- 尝试 001：`sitemap` HTTP 403（`diagnostics/attempt-001-403/scrapy.log.txt`）。
  处理：补上与站点一致的 `Accept-Language: es-ES,es;q=0.9` 与固定
  `Accept-Encoding: gzip, deflate, br`；未增加请求并发或更换出口。
- 主运行与复跑无 429；如遇 429，spider 按 `Retry-After` 退避（上限 60s、最多 3 次），
  超过即停止并记 `http_429_after_retries`。
- 构建期人工探测曾收到一次 429（冷却后恢复），未用于正式结果；未绕过限流。

## 已知限制与未完成项

- 有界样本：只处理 sitemap 前 30 个商品，6660 个候选里余 6630 个未处理；
  不声称全站覆盖，`coverage.status = KNOWN` 但 `covered = 30`。
- 分类分页是 JS 组件，静态方案不能翻页；分类页只作导航证据。
- 部分描述按“页面缺规格表区块”判定，未用浏览器核对未渲染区块。
- 未做干净环境导入复跑（A10/D05），未做人工业务验收（`business_acceptance = NOT_REVIEWED`）。
- 续跑/断点恢复未实现（本次自然结束，未触发）。
- 站点 sitemap 顺序包含服务类条目（礼品卡、装配服务等），本方案按公开商品页处理并保留原分类。
- 代理出口为系统代理；未比较直连与代理的差异。
