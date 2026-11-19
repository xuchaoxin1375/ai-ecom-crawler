# javaestate.com — Scrapling 运行记录

## 1. 范围与环境

- 站点：`https://javaestate.com/`，S1，US／en-US／USD。
- 范围：商品 sitemap 前 30 个唯一 `/products/<handle>`；10 分钟墙钟上限。
- 访问边界：`robots.txt` 的 `*` 规则；不登录、不购物车、不结算、不访问 account/orders/services/recommendations。
- 框架：Scrapling 0.5.1，`FetcherSession`（curl_cffi，静态 HTML），单并发、请求间隔 1.1 s、最多 3 次尝试。
- 运行期不调用 LLM。不启动浏览器。
- 环境：Windows 11，Python 3.13.13；仓库内 `python -m uv run --project experiments/framework-compare/scrapling ...`；未安装或升级任何包。
- 网络：环境存在 `HTTP_PROXY`／`HTTPS_PROXY`／`NO_PROXY`；值未记录，出口未独立测量。

## 2. 时间线（UTC）

| 时间 | 事件 |
| --- | --- |
| 2026-11-18T23:45:00Z | 构建会话开始（`build_started_at`，分钟精度） |
| 23:48–23:58Z | 入口、robots、sitemap、商品页结构探针；确认 Shopify 静态 HTML、嵌入 `window.wpdExtensionIsProductPage`、JSON-LD 缺失页的货币来源 |
| 00:05Z | 方案包首版（manifest、runner、extractor、CSV、诊断、README、测试） |
| 00:04:52–00:05:01Z | 2 商品冒烟运行（6 请求，2 有效）；字段路径通过 |
| 00:07:05Z | 首次完整方案就绪（`first_plan_at`） |
| 00:07:15–00:08:06Z | 主运行 `run-001`：34 请求，30 有效，51.12 s |
| 00:07:22Z | 首个有效商品（`first_valid_product_at`） |
| 00:08:45–00:12:19Z | 修复任务 v2：`tax_basis` 实际提取；修复复跑与验收 |
| 00:11:11–00:12:02Z | 修复复跑 `fix-rerun`：34 请求，30 有效，50.9 s |
| 00:12:35–00:13:25Z | 同方案 v2 复跑 `run-002`：34 请求，30 有效，50.36 s |
| 00:12:19Z | 采集构建与修复验收结束；之后的离线测试与文档整理不计入上述构建/修复指标 |

`first_plan_s = 1325.0`，`first_valid_product_s = 1342.8`，均从 `build_started_at` 起算。

## 3. 发现与获取

1. `GET /robots.txt` 200；用 `protego` 解析，`*` 允许公开商品、分类、页面、博客，禁止 cart／checkout／account／orders／services／recommendations。
2. `GET /` 200；记录 `html lang="en"`、站点名 `Java Estate Roastery`。
3. `GET /sitemap.xml` 200；索引包含 `sitemap_products_1.xml?from=...&to=...`、pages、collections、blogs、agentic discovery。
4. 运行时解析索引并选择含 `sitemap_products` 的 URL，不硬编码 `from`/`to`。
5. `GET` 商品 sitemap 200；707 个 `<url><loc>`。按 sitemap 顺序扫描，取前 30 个唯一 `/products/<handle>` 后停止（`filtered_urls=1`，为扫描过程中出现的非商品/重复条目；未遍历剩余条目）。
6. 逐页 `GET` 30 个商品页，全部 200。

`discovered_urls = 33`（入口 1、sitemap index 1、商品 sitemap 1、商品 30）；`pending_navigation_entries = 0`（本方案不遍历分类分页，属于范围外）。

## 4. 提取与归一化

- 价格：`window.wpdExtensionIsProductPage.variants[*].price`（整数美分）取最小有限正值；含缺货有价变体。样本均为单变体。
- 币种：JSON-LD `Product.offers.priceCurrency` = USD；同报价对象。另有 `og:price:currency`、`Shopify.currency.active`、`ShopifyAnalytics.meta.currency` 作为回退。
- 主图：嵌入 `featured_image`（原尺寸 URL，无 `width=` 参数）；不使用 logo/占位图。
- 正文：嵌入商品 HTML 为主，`.product__description` 为可见 DOM 对照；DOM 文本显著短于嵌入正文或 DOM 块缺失时标 `partial` 并写原因。本次 30 个均为 `complete`。
- 名称：JSON-LD name → h1 → 嵌入 title → og:title；只清理明确站点后缀。
- 分类：JSON-LD `category`；回退嵌入 `type`；不使用 Home/Shop 泛层级。
- 品牌：JSON-LD brand → 公开 vendor；等于店名/域名时留空并记 `store_name_not_brand`。
- 选项：嵌入 options + variants option1..3；`select.product-variant-container` 为 DOM 回退；排除数量组、Default Title 和价格尾差。本次样本无多 variant，`attributes` 为空。
- 库存：任一变体 available → `in_stock`；全 false → `out_of_stock`；缺失不推断。
- 税价：v2 用 variants `taxable`：全 false → `no_tax_applied`；全 true → `unknown_not_stated`；混合 → `mixed_taxability`；缺失 → `unknown_not_stated`。

## 5. 主运行 `run-001`（v1）

命令：

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  python experiments/framework-compare/scrapling/javaestate/run.py `
  --out-dir experiments/framework-compare/scrapling/javaestate `
  --label run-001 `
  --max-products 30 --max-seconds 600 `
  --build-started-at 2026-11-18T23:45:00Z
```

结果：

- 34 请求（robots 1、入口 1、sitemap 2、商品 30），0 重试，全部 200。
- 30 有效，0 排除，0 失败，0 部分正文。
- 51.12 s；`outcome=PARTIAL`，`stop_reason=BUDGET_EXHAUSTED`（30 页上限，sitemap 共 707）。
- 无运行期错误；无 429。
- 根目录 `valid.csv`、`task-result.json` 当时为该次结果；随后 v2 修复复跑覆盖了根目录，v1 快照保留在 `diagnostics/run-001/`。

## 6. 修复任务（v2）

**问题**：v1 的 `tax_basis` 是常量 `unknown_not_stated`，没有使用页面已有的公开税标志；`02` 把 `tax_basis` 列为需携带的实际口径。

**改动**：

- `normalize.py`：新增 `tax_basis_from_variants()`。
- `extract.py`：`ProductRecord.tax_basis`，写入证据 `tax_basis_source`。
- `runner.py`：CSV 与审计使用记录值；限制说明更新。
- `config.py`／`manifest.yaml`：`plan_version` → `2026.11.19-2`；字段来源与 normalize 说明更新。
- `README.md`、`tests/test_contract.py`、`tools/validate_output.py`：规则、测试、允许值同步。

**复跑**：同一 30 个商品 URL，`fix-rerun`，34 请求，30 有效，0 排除，0 失败，50.9 s，0 模型调用。30 行中 28 行 `tax_basis` 从 `unknown_not_stated` 变为 `no_tax_applied`，2 行保持 `unknown_not_stated`；其余业务字段不变。

**耗时**：00:08:45–00:12:19Z，`fix_minutes = 3.6`（含复跑与验收），低于 30 分钟上限。

## 7. 同方案复跑 `run-002`（v2）

命令同主运行，`--label run-002`，输出到 `diagnostics/run-002/`。结果：34 请求、30 有效、0 排除、0 失败、50.36 s、0 模型调用；业务字段与 `fix-rerun` 完全一致，仅 `task_id`／`extracted_at` 不同。说明同版本方案的字段结果可重复。

## 8. 错误与处理

| 时间 | 错误 | 处理 |
| --- | --- | --- |
| 构建期 | 单元测试：`parse_positive_money` 把 `1,234` 接受为 1234 | 改为拒绝单一分隔符后三位数字；测试通过 |
| 构建期 | 固定环境无 PyYAML，`manifest.yaml` 未机器解析 | 逐行人工检查；未安装包；在指标中列为限制 |
| 运行期 | 无 | — |

未出现 429、403、5xx、挑战页或提取异常。

## 9. 资源与回收

- 未启动浏览器；`browser_processes_started = 0`。
- 每次运行一个进程内 `FetcherSession`，由上下文管理器关闭；三次完整运行各 1 个 session。
- 运行结束后无残留的商品抓取进程或浏览器进程；未测量峰值内存。
- 没有保存整页 HTML；只保存 robots、发现 URL 列表、事件、审计和诊断 CSV。

## 10. 验收场景对照（A01～A10、A12～A15、A17）

| 场景 | 状态 | 证据与限制 |
| --- | --- | --- |
| A01 正价／零价／无价 | 通过 | 30 行均为有限正价；另用 `java-jacket-drink-sleeves-8-24-oz-copy` 构建诊断验证 `zero_price` 排除（未入 valid.csv）；零价/缺价/非法金额在提取层排除并留因；`parse_positive_money` 单元测试覆盖 0、负数、NaN、Infinity、歧义分隔符 |
| A02 变体最低价与选项 | 有条件 | 价格取 variants 最小正值；公开选项从 variants/picker 构建；本次 30 个样本均为单变体，选项未由实站触发，仅有离线测试 |
| A03 税价与市场 | 通过（税制仅到可证程度） | 币种取同一 JSON-LD 报价的 USD；不混取其他市场；`tax_basis` 只依据公开 `taxable` 标志，不推断含税/未税 |
| A04 完整正文与摘要 | 通过 | 30 个样本正文 `complete`；嵌入正文与 DOM 对照；摘要回退与无正文分支由离线测试覆盖 |
| A05 复杂部分描述 | 未触发 | `partial` 分支已实现并由离线测试覆盖（DOM 缺失、DOM 明显更短）；本次未见难取区块 |
| A06 HTML 与裸文本 | 通过 | 实站为 HTML，经白名单清洗；`text` 回退由 `description_format=text` 路径与测试覆盖；未重复反转义 |
| A07 主图／分类／品牌／单位 | 通过 | 30/30 主图；分类来自 JSON-LD；品牌来自 JSON-LD/vendor，店名不冒充品牌；未从重量/数量推算销售单位 |
| A14 导出保真 | 通过 | 22 列；CSV 引号、逗号、换行、中文经 round-trip 测试；公式保护；`missing_reasons` JSON；市场/语言/库存/税价口径逐行携带 |
| A08 自主发现 | 通过 | 入口 → robots → sitemap index → product sitemap → 商品页；方案可保存，入口相对路径 |
| A09 无 AI 执行／复跑 | 通过 | `run-002` 同 v2 方案独立执行，0 模型调用；业务字段与 `fix-rerun` 一致 |
| A10 兼容环境复用 | 未运行 | 仅在当前固定环境验证；未在第二个干净环境导入 |
| A12 访问错误 | 未触发 | 无 429/403/5xx/挑战页；代码含 Retry-After 与停止规则，未获真实响应验证 |
| A13 中断与取消 | 未运行 | 顺序循环的 SIGINT 停止与 session 关闭已实现，但未做取消实测 |
| A15 漂移及修复 | 通过 | v1→v2 修复 `tax_basis` 并同 URL 复跑；旧 v1 结果保留在 `diagnostics/run-001/` |
| A17 覆盖与人工验收 | 部分 | 覆盖 `PARTIAL`（30/707）、剩余范围保留；`business_acceptance=NOT_REVIEWED` |

## 11. 已知限制与未完成项

- 30／707 个 sitemap 商品，不是全站覆盖。
- 30 个样本全部单变体，真实多 variant 选项未触发；选项逻辑由单元测试覆盖。
- 30 个样本全部 `complete` 正文；`partial`／`fallback`／`not_provided`／`failed` 未由真实样本触发。
- 30 个样本无零价／缺价；另用 `java-jacket-drink-sleeves-8-24-oz-copy` 构建诊断验证 `zero_price` 排除（未入 `valid.csv`），缺价/非法金额仍仅由单元测试覆盖。
- 429 `Retry-After` 路径未由真实响应触发。
- 所有 30 个样本都有 Product JSON-LD；无 JSON-LD 的回退路径在构建诊断 `java-jacket-drink-sleeves-8-24-oz-copy` 上实际走通（`og_price_currency`、h1、嵌入商品 JSON），未进入有效集。
- `tax_basis` 只依据 `taxable` 标志，不证明含税／未税定价。
- 静态 HTML；JS-only 内容未渲染。
- 代理值未记录，出口未独立测量；峰值内存未测。

## 12. 产物索引

- `manifest.yaml`、`run.py`、`javaestate_scraper/`、`README.md`
- `valid.csv`（v2，最新发布结果）
- `task-result.json`（v2，最新发布结果）
- `run-summary.json`（v2，最新发布结果）
- `diagnostics/run-001/`（v1 主运行，含 `valid.csv` 与 `task-result.json` 快照）
- `diagnostics/fix-rerun/`（v2 修复复跑）
- `diagnostics/run-002/`（v2 同方案复跑）
- `diagnostics/smoke-001/`（2 商品构建冒烟）
- `tools/`（构建探针与输出校验；运行入口不调用）
- `tests/test_contract.py`（18 项离线契约测试，含正文状态分支与税价口径）
- `experiments/framework-compare/results/scrapling-javaestate.json` 与 `.md`
