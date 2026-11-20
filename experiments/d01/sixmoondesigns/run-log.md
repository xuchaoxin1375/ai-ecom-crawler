# D01 S4 sixmoondesigns.com — Scrapling 公开 JSON 试点

## 范围与环境

- 站点：`https://www.sixmoondesigns.com/`，S4，US／en-US／USD。
- 范围：`products.json?limit=250&page=1&country=US` 的前 30 个商品；列表层提取，不逐页补描述。
- 市场参数：入口、API、首商品抽检均带 `?country=US`。无该参数时，站点按出口把 `Shopify.currency` 本地化为 CNY。
- 访问边界：robots 先取；不登录、不购物车、不结算、不访问账户／推荐接口。
- 框架：Scrapling 0.5.1，`FetcherSession`（curl_cffi，静态 HTML/JSON）；单并发、间隔 1.1s；LLM 0、浏览器 0。
- 环境：Windows，Python 3.13.13；直连（`HTTPS_PROXY`／`HTTP_PROXY` 未设置，`NO_PROXY` 已设置）。

## 运行

| label | 结果 | 请求 | 墙钟 | 有效／排除／失败 | 停止原因 |
| --- | --- | ---: | ---: | --- | --- |
| `d01-run-001` | 失败：入口 `Shopify.currency` 解析为空 | 2 | 52.31s | 0／0／0 | `PLAN_ERROR` |
| `d01-run-002` | 成功，计数字段待修正 | 4 | 10.46s | 29／1／0 | `BUDGET_EXHAUSTED` |
| `d01-run-003` | 最终发布结果 | 4 | 14.49s | 29／1／0 | `BUDGET_EXHAUSTED` |

最终运行：robots 1、US 入口 1、US `products.json` 1、首商品页抽检 1；全部 200。

## 失败与修复

`d01-run-001` 的入口请求第一次 45 秒超时，重试 200；Scrapling 对 740KB 的 HTML 响应把 `response.text` 留空，`response.html_content` 有完整 730,708 字节。解析器改用 `html_content`（robots 用 `body` 解码）后，`d01-run-002` 通过。

另一个质量修正：`description_not_provided_products` 原来把被排除的 Restocking Fee 也算进去，改为只统计有效商品；`d01-run-003` 为 5。

## 结果

- 有效 **29**／排除 **1**／失败 **0**。
- 排除项：`restocking-fee`（Restocking Fee，10.00 USD，缺主图）；是费用项而非商品，保留原因，不塞进有效集。
- 价格：10.00–425.00 USD；币种 29／29 USD；入口 `Shopify.currency.active=USD` 与首商品页 `product:price:currency=USD`、`product:price:amount=18.00` 一致。
- 描述：完整 24、原站未提供 5；空描述不拿名称补。
- `quality_exceptions`：18 条，均为可空字段或描述未提供，不是正文提取失败。
- 覆盖：`products.json` 页面 1 有 112 个商品，本次 30 个候选、29 个有效；`PARTIAL`，不写成全站覆盖。

## 输出校验

```powershell
python experiments/d01/sixmoondesigns/tools/validate_output.py `
  --dir experiments/d01/sixmoondesigns --expected-products 29
```

结果：`{"rows": 29, "problems": []}`。

## 证据位置

- `valid.csv`、`task-result.json`、`run-summary.json`：`d01-run-003` 发布结果。
- `diagnostics/d01-run-001/`：入口 `.text` 空值的失败证据。
- `diagnostics/d01-run-002/`：修复后的中间结果。
- `diagnostics/d01-run-003/`：最终结果、逐商品审计、robots 快照。
- `tests/`、`tools/validate_output.py`：离线测试与结果校验。

## 限制

- 列表层公开 JSON；没有逐页补全描述或规格，描述状态按 `body_html` 记录。
- 30 个候选是预算，不是 112 个商品的全量或全站结论。
- 站点按出口本地化；无 `country=US` 会得到 CNY，不能把 API 原始价格直接标 USD。
- Restocking Fee 这类非商品条目按排除处理；不同站点需要同类判型规则。
- 静态请求路径；未验证浏览器渲染、挑战页或登录场景。
