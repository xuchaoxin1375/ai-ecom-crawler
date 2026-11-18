# Scrapy / javaestate.com 方案

本目录是框架对比实验（S1）中 Scrapy 侧的方案包，入口为 `manifest.yaml`，程序入口为 `run.py`。方案状态是 `candidate`：已完成一次有界试跑，但只覆盖商品 sitemap 的前 30 个商品，不声明全站覆盖率。

## 运行

在仓库根目录执行：

```powershell
python -m uv run --project experiments/framework-compare/scrapy `
  python experiments/framework-compare/scrapy/javaestate/run.py `
  --max-products 30 --max-seconds 600
```

`uv` 不在 PATH 时使用 `python -m uv`；依赖由 `experiments/framework-compare/scrapy/pyproject.toml` 与 `uv.lock` 固定，Scrapy 版本为 2.20.0。运行期不调用任何 LLM。

停止方式：

- 商品页上限 30 或墙钟 600 秒，先到为准。
- 按 Ctrl+C 中断；pipeline 在 spider 关闭时写出已接纳结果和待处理清单。
- 遇到 429 时按 `Retry-After` 退避，最多 3 次；仍失败则记录并以访问边界停止。

## 发现与获取

- 发现：读取 `https://javaestate.com/sitemap.xml`，找到 `sitemap_products_*.xml`，按 sitemap 顺序取前 30 个 `/products/{handle}`，按 handle 去重；不遍历分类或全站。
- 获取：商品 HTML 在构建探测中返回 HTTP 429（`Retry-After: 60`），因此运行期使用公开的 `https://javaestate.com/products.json?limit=250&page={page}` 目录 JSON。页面顺序按 `[3, 2, 4, 1]` 尝试，直到 30 个 handle 全部找到；当前目录规模下第 3 页包含最早的商品。
- 访问边界：`ROBOTSTXT_OBEY=True`；并发 1；请求间隔 2 秒；不登录、不使用 Cookie、不绕过访问控制。
- 429：记录到 `diagnostics/events.json` 与 `diagnostics/scrapy.log`，按 `Retry-After` 退避；商品 HTML 的 429 不逐商品重试，避免放大限流。

## 字段口径

- 价格：取所有变体（含缺货变体）中的最低有限价；零价、负价、非法价和无价商品进入排除诊断，不进入 `valid.csv`。不取划线价、运费或推荐商品价。
- 币种：`USD`。目录 JSON 没有逐报价币种字段，方案用固定任务市场 US/en-US/USD，并在运行时探测首页 `Shopify.currency.active`；`tax_basis` 记录为 `NOT_STATED`，不猜测含税/未税。
- 正文：来自目录 JSON 的 `body_html`，用 DOM 白名单清洗；移除脚本、样式、表单、图片、链接可点击能力和 BYOB 管理端警告。因为商品 HTML 页未能取得，正文统一标记 `partial`，`partial_reason` 说明缺失的是页面主题区块与 metafields。`description_format` 按清洗结果区分 `html` / `text`。
- 分类/品牌/选项：分类用 `product_type`，品牌用 `vendor`（`BYOB` 或空值留空），选项用公开 `options` 并按 `Name#A|B~Color#Red` 序列化；忽略 `Title/Default Title` 与数量组。缺失字段写入 `missing_reasons`。
- 库存：任一变体 `available` 为真记 `in_stock`，否则 `out_of_stock`；缺货有价商品仍保留。
- CSV：22 列，UTF-8 with BOM，CRLF，最小引号；逗号、引号、换行和中文由 `csv` 模块处理；以 `=`、`+`、`-`、`@` 开头的文本单元格加单引号防公式注入。

## 输出

- `valid.csv`：22 列有效商品集。
- `task-result.json`：`state`、`outcome`、`stop_reason`、`counts`、`coverage`、`business_acceptance`、`runtime`。
- `diagnostics/excluded_products.csv`：零价/负价/无价/缺图/币种不符等业务排除。
- `diagnostics/failed_products.csv`：获取、解析、提取或校验失败。
- `diagnostics/pending_products.csv`：预算停止时已选中但未处理的商品。
- `diagnostics/events.json`：429/退避/give-up 事件。
- `diagnostics/run-meta.json`：请求统计、页面状态、选中列表、首有效时间。
- `diagnostics/scrapy.log`：Scrapy 运行日志。

实验指标由 `run.py` 写入 `experiments/framework-compare/results/scrapy-javaestate.json` 和同名 `.md`。

## 计数与覆盖

`sitemap` 中商品 URL 数作为 `denominator`；本次只处理前 30 个，其余计入 `pending_products`。因此 `outcome` 预期为 `PARTIAL`，`stop_reason` 为 `BUDGET_EXHAUSTED`，`coverage.status=KNOWN` 但 `covered` 仅 30，不能解读为全站完成。

## 测试

```powershell
$env:PYTHONPATH = (Resolve-Path "experiments/framework-compare/scrapy/javaestate").Path
python -m uv run --project experiments/framework-compare/scrapy `
  python -X utf8 -m unittest discover `
  -s experiments/framework-compare/scrapy/javaestate/tests -v
```

测试覆盖正价/零价/负价、变体最低价、选项序列化与转义、正文清洗与状态、裸文本、22 列 CSV 往返和公式注入防护；不访问网络。

## 已知限制

- 商品 HTML 被 429 挡住，正文完整性和页面主题区块未核对；只能证明目录 `body_html` 的内容。
- 目录 JSON 不携带逐报价币种；USD 证据来自首页活动币种和固定任务市场。
- 目录页顺序是站点规模相关的启发式；目录量变化时需要调整 `fetch.per_url_type.catalog.page_order` 或依赖回退页。
- 构建期为了确认页序和字段形状一次性读取了目录 1–3 页（707 条），运行期只读第 3 页并处理 30 个；构建期数据未保留。
- 本次样本没有多选项商品和零价商品；相关规则由 `tests/` 的合成样例验证，不代表真实站点已覆盖所有路径。
- 第二次线上复跑在同日遇到更长的 429 窗口，以 `ACCESS_DENIED` 停止；见 `run-log.md` 与 `diagnostics/rerun/`。
- 只采公开商品，不采账户、购物车、结账、订单或推荐接口。

## 维护

- 选择器/字段规则在 `javaestate/normalize.py`；获取与发现流程在 `javaestate/spiders/products.py`；输出在 `javaestate/pipelines.py`。
- 站点结构或来源变化时递增 `manifest.yaml` 的 `plan_version`，并保留旧结果。
- 入口参数 `--base-url` 仅用于本地 fixture 测试；生产运行保持默认 `https://javaestate.com`。
