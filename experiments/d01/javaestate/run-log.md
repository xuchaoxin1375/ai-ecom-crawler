# D01 S1 javaestate.com — Scrapling 试点运行记录

## 范围与环境

- 站点：`https://javaestate.com/`，S1，US／en-US／USD。
- 范围：商品 sitemap 前 30 个唯一 `/products/<handle>`；10 分钟墙钟上限。
- 访问边界：`robots.txt` 的 `*` 规则；不登录、不购物车、不结算、不访问 account／orders／services／recommendations。
- 框架：Scrapling 0.5.1，`FetcherSession`（curl_cffi，静态 HTML），单并发、请求间隔 1.1 s、最多 3 次尝试。
- 运行期不调用 LLM；不启动浏览器。
- 环境：Windows，Python 3.13.13；Scrapling venv；`HTTPS_PROXY`／`HTTP_PROXY` 未设置，`NO_PROXY` 已设置；直连。
- 数据合同：`docs/02` 的 9 列业务 CSV；内部追溯字段保留在 `task-result.json` 和 `product-audit.jsonl`。

## 运行

| label | 开始／结束（UTC） | 请求 | 重试 | 有效 | 排除 | 失败 | 部分描述 | 墙钟 | 停止原因 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `d01-run-001` | 15:55:30／15:57:26 | 34 | 0 | 30 | 0 | 0 | 0 | 115.99 s | `BUDGET_EXHAUSTED` |
| `d01-rerun` | 15:57:53／15:59:50 | 34 | 0 | 30 | 0 | 0 | 0 | 117.80 s | `BUDGET_EXHAUSTED` |

两次均为 `FINISHED`／`PARTIAL`；34 次请求全部 200，构成：robots 1、入口 1、sitemap index 1、商品 sitemap 1、商品页 30。

## 独立复跑

`d01-rerun` 使用同一 `manifest.yaml`、同一 30 个商品网址和同一命令，不依赖构建会话或 LLM。两次 `product-audit.jsonl` 的 30 条记录按 `source_url`、名称、价格、币种、描述状态、描述长度、分类、品牌、选项、库存、税价和缺失原因逐字段比较，差异为 0。

## 输出与质量

- `valid.csv`：9 列，30 行；30 个唯一商品 URL。
- 价格：11.10–132.99 USD，全部为有限正数；币种 30／30 来自同一报价证据。
- 名称、主图、描述：均非空；描述状态 30／30 `complete`；`quality_exceptions` 为空。
- 计数：`product_candidates = 30`，`processed = 30`，`valid = 30`，`excluded = 0`，`failed = 0`，`pending = 0`，`in_flight = 0`。
- 覆盖：商品 sitemap 声明 707 条，本次处理 30 条；`coverage.status = PARTIAL`，不是全站完成。
- 运行期 LLM 调用 0；浏览器启动 0。

## 输出校验

```powershell
python experiments/d01/javaestate/tools/validate_output.py --dir experiments/d01/javaestate
```

结果：`OK: 30 rows, 9 columns, 30 valid, 0 excluded, 0 failed`。

## 证据位置

- `valid.csv`、`task-result.json`、`run-summary.json`：最新发布的复跑结果。
- `diagnostics/d01-run-001/`：首跑日志、审计、排除／失败／待处理清单。
- `diagnostics/d01-rerun/`：独立复跑的同结构证据。
- `manifest.yaml`：方案入口；`README.md`：运行、字段和限制说明。

## 限制

- 只取 sitemap 前 30 个商品，不能写成 707 个商品或全站完成。
- 静态 HTML 路径；未验证浏览器渲染、JS 展开区或挑战页。
- 构建效率指标未记录（`first_valid_product_s` 为空），因为本轮没有单独固定构建开始时间。
- 429 处理已实现，但本轮未触发；不能据此证明所有限流场景。
- 主图 URL 可能在 Shopify 店面域名与 `cdn.shopify.com` 之间变化；同一资产不因此变成不同商品。

## 复跑命令

```powershell
experiments/framework-compare/scrapling/.venv/Scripts/python.exe experiments/d01/javaestate/run.py `
  --out-dir experiments/d01/javaestate `
  --label d01-rerun
```
