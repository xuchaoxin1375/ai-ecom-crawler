# Scrapy / javaestate.com 运行记录

## 摘要

- 方案：`experiments/framework-compare/scrapy/javaestate/manifest.yaml`，`plan_version=2026.11.19-1`，状态 `candidate`。
- 主试跑：2026-11-18T23:29:03Z → 23:30:12Z，69s，6 次请求，30 个有效商品，0 排除，0 失败，30 个部分描述。
- 结果状态：`FINISHED` / `PARTIAL` / `BUDGET_EXHAUSTED`。商品 sitemap 有 706 个商品 URL，本次按上限只处理前 30 个，676 个待处理；不是全站完成。
- 构建时间：任务开始约 2026-11-19T06:37:00+08:00；manifest 草案 23:02:35Z（1535s），首个端到端可运行方案 23:06:20Z（1760s，fixture 通过），首个有效商品 23:30:12Z（3192s）。均在 90 分钟盒内。
- 运行期 LLM 调用：0。字段规则是确定性 Python，运行时不调用任何模型。

## 环境与访问边界

| 项 | 记录 |
| --- | --- |
| 系统 | Windows，仓库分支 `exp/framework-compare` |
| Python | 3.13.13 |
| Scrapy | 2.20.0 |
| 依赖管理 | `python -m uv run --project experiments/framework-compare/scrapy`；未安装或升级包 |
| 网络 | 系统 HTTP 代理的同一出口；未记录代理地址/凭据，未切换到直连或其他出口 |
| robots | `https://javaestate.com/robots.txt` 200；商品、sitemap 允许；购物车、账户、结账、订单、admin、services、推荐接口禁止。Scrapy `ROBOTSTXT_OBEY=True` |
| 并发/间隔/重试 | 并发 1；`DOWNLOAD_DELAY=2.0`；429 按 `Retry-After` 退避，最多 3 次；未登录、未使用 Cookie、未绕过访问控制 |
| 商品页上限 | 30 个商品身份或 600 秒，先到为准 |

## 构建期探测与 429

构建期用于选路的公开请求（不是主试跑计数）：

| 时间（+08） | 请求 | 结果 |
| --- | --- | --- |
| 06:40:40 | `/robots.txt` | 200 |
| 06:40:45 | `/sitemap.xml` | 200，索引中有 `sitemap_products_1.xml` |
| 06:40:51 | 商品 sitemap | 200，707 个 loc，其中 706 个商品 URL |
| 06:42:39 | 首页 `/` | 200，含 `Shopify.currency = {"active":"USD","rate":"1.0"}` |
| 06:41–06:46 | `/products/{handle}`、`/collections/all` | 429，`Retry-After: 60`；等待 65s 后仍 429 |
| 06:44:51 | `/products.json?limit=2` | 200，公开目录 JSON 可用 |
| 06:45–06:46 | `/products.json` 第 1–3 页 | 200，共 707 条；构建期一次性侦察，用于确认页序与字段形状 |
| 06:52–07:28 | `/products.json` 小探测 | 多次 429（18 字节 `local_rate_limited`） |
| 07:29:12 | 主试跑目录页 `limit=250&page=3` | 429；退避 60s 后 200 |

构建期的 1–3 页目录读取（707 条）比试跑样本宽，但不属于逐商品页遍历，也没有保留完整目录数据；运行期只读取 page 3（207 条），并只处理选中的 30 个商品。此点列入限制，避免把构建侦察误读为试跑覆盖。

结论：商品 HTML 路径在当前出口下被 429 边界挡住，公开 `products.json` 目录可用但不稳定。方案因此把商品 HTML 标记为 `disabled_after_429`，运行期只用目录 JSON；正文统一标记部分提取，不把目录 `body_html` 冒充已核对的完整页面正文。

## 发现与样本

- 从 sitemap 索引读取商品 sitemap，提取 706 个唯一 `/products/{handle}`，按 sitemap 顺序取前 30 个；按 handle 去重。
- 不遍历分类、分页或全站；不请求账户、购物车、结账、订单、推荐接口。
- 目录页按 `[3, 2, 4, 1]` 尝试；当前规模下第 3 页包含最早的商品，即前 30 个 sitemap 商品。找到全部 30 个 handle 后停止，不抓取剩余目录页。

## 主试跑（Run 001）

命令：

```powershell
python -m uv run --project experiments/framework-compare/scrapy `
  python experiments/framework-compare/scrapy/javaestate/run.py `
  --max-products 30 --max-seconds 600 `
  --build-started-at "2026-11-19T06:37:00+08:00" --revisions 0
```

时间线（UTC）：

| 时间 | 事件 |
| --- | --- |
| 23:29:03 | spider 启动 |
| 23:29:04 | robots.txt 200 |
| 23:29:08 | 商品 sitemap 200；发现 706 个商品 URL，选中 30 |
| 23:29:10 | 首页 200；`Shopify.currency.active=USD` |
| 23:29:12 | 目录页 429；按 `Retry-After: 60` 退避 |
| 23:30:12 | 目录页 200（207 条记录）；30/30 找到；首个有效商品 |
| 23:30:12 | 处理完成，写出输出 |

请求统计：6 次请求（robots 1、sitemap 2、首页 1、目录页 2），5×200、1×429；无 403/404；墙钟 69s。

计数（来自 `task-result.json` 与 `diagnostics/run-meta.json`）：

| 计数 | 值 |
| --- | --- |
| discovered_urls | 706 |
| product_candidates | 706 |
| processed_products | 30 |
| valid_products | 30 |
| excluded_products | 0 |
| failed_products | 0 |
| partial_description_products | 30 |
| pending_products | 676 |
| in_flight_products | 0 |

覆盖：`status=KNOWN`，denominator 706（商品 sitemap loc 数），covered 30；676 个商品 URL 未处理。

数据概况：

- 30 个唯一商品；价格 11.10–132.99 USD，全部为有限正价；27 个 `in_stock`，3 个 `out_of_stock`（缺货有价商品保留）。
- 分类 3 个：Frappes 21、Sauces 6、Cocoa 3；品牌 Ghirardelli / Big Train；样本均为单变体商品，因此 `attributes` 为空并在 `missing_reasons` 注记 `not_provided`。
- 正文均来自目录 JSON `body_html`，清洗后长度 134–812 字符；`description_format=html`，`description_status=partial`，`partial_reason` 统一说明 `product_html_http_429`、来源为 `products.json body_html`、页面主题区块与 metafields 未核对。
- `tax_basis=NOT_STATED`；`price_basis=lowest_public_current_variant_price`；`market=US`，`locale=en-US`。
- CSV：22 列，UTF-8 with BOM，CRLF，最小引号；32,419 字节。用 Python `csv` 模块回读验证 30 行×22 列，逗号/引号/换行/中文均可还原。
- 有效 CSV 中没有零价、负价、失败或诊断记录；本样本的排除/失败集为空。`diagnostics/excluded_products.csv` 与 `failed_products.csv` 只有表头。

## 第二次执行（Run 002）

命令与方案版本相同，输出到独立目录，避免覆盖主结果：

```powershell
python -m uv run --project experiments/framework-compare/scrapy `
  python experiments/framework-compare/scrapy/javaestate/run.py `
  --output-dir experiments/framework-compare/scrapy/javaestate/diagnostics/rerun `
  --results-dir experiments/framework-compare/scrapy/javaestate/diagnostics/rerun/results `
  --max-products 30 --max-seconds 600
```

结果：2026-11-18T23:31:30Z → 23:34:43Z，193s，8 次请求（4×200、4×429）；目录页连续 429，按 `Retry-After: 60` 退避 3 次后停止；`valid_products=0`，`failed_products=30`，`outcome=FAILED`，`stop_reason=ACCESS_DENIED`。30 条失败记录统一为 `catalog_access_denied_http_429`，保留在 `diagnostics/rerun/diagnostics/failed_products.csv`。

两次差异来自站点限流窗口，不是字段规则或代码路径变化：第一次 429 后重试成功，第二次在更长的 429 窗口内按上限停止。第二次执行前只做了非语义的 meta 清理（避免 `download_latency` 转发警告），`plan_version` 未变。主 `valid.csv` 与 `task-result.json` 仍是第一次执行的结果。

## 验证

- `python -m unittest discover -s experiments/framework-compare/scrapy/javaestate/tests`：16 项通过，覆盖正价/零价/负价、变体最低价、选项序列化与转义、正文清洗与状态、裸文本、22 列 CSV 往返、公式注入防护。
- 本地 HTTP fixture 运行：30 valid / 0 excluded / 0 failed，证明 Scrapy 发现→目录→字段映射→CSV 链路在关闭构建会话后可独立执行；fixture 的 `source_url` 是 `127.0.0.1`，不作为线上结果，见 `diagnostics/fixture-validation/`。

## 错误与限制

- 商品 HTML 和分类页在构建期返回 429（`Retry-After: 60`）；运行期目录页也不稳定。没有把 429 页面当作商品内容，也没有把失败商品混入有效集。
- 目录 JSON 不含逐报价币种；USD 依据是固定任务市场与首页 `Shopify.currency.active=USD`，不是货币符号猜测。
- 税价口径源站未说明，记录 `NOT_STATED`，未猜测含税/未税。
- 正文只取目录 `body_html`；页面主题区块、metafields 和展开区域未核对，因此全部标记部分提取。不能据此声称完整正文。
- 样本为 sitemap 顺序前 30 个，全部是单变体商品；A02 的多变体/选项路径由合成测试覆盖，未在本次真实样本中出现。零价/负价路径同样由测试覆盖；本次 sitemap 样本没有零价商品。
- 目录页顺序 `[3, 2, 4, 1]` 是当前目录规模的站点特定启发式；目录量变化时需要调整或依赖回退页。
- 构建期为了确认页序和字段形状，一次性读取了 `products.json` 第 1–3 页（707 条），比试跑样本宽；运行期只读 page 3 并处理 30 个，构建期数据未保留进方案包。
- 第二次线上复跑因 429 失败；线上可复现性受站点限流影响，方案包本身的执行入口和确定性字段规则仍可复跑。

## 资源回收

- 单进程 Python/Scrapy，无浏览器、无数据库、无队列、无子进程；进程退出后无残留。
- 未保存整页 HTML；主目录只保留商品级 CSV/JSON、诊断和日志。构建期大文件（完整目录 JSON、首页、sitemap 全文）不进入方案包。
- 运行期未调用 LLM；`runtime_llm_calls=0`。

## 文件

- 方案包：`manifest.yaml`、`run.py`、`scrapy.cfg`、`javaestate/`、`README.md`
- 主结果：`valid.csv`、`task-result.json`、`diagnostics/`
- 第一次原始输出：`diagnostics/run-001/`
- 第二次输出：`diagnostics/rerun/`
- fixture 验证：`diagnostics/fixture-validation/`
- 指标：`experiments/framework-compare/results/scrapy-javaestate.json`、`scrapy-javaestate.md`
