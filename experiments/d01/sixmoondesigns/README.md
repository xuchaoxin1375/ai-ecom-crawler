# sixmoondesigns.com — S4 公开 JSON 方案包

D01 S4 单站试点的 Scrapling 实现。站点：`https://www.sixmoondesigns.com/`，市场 US／`en-US`／USD，单站上限 30 个商品或 10 分钟。

## 组成

| 路径 | 内容 |
| --- | --- |
| `manifest.yaml` | 方案入口，满足 `docs/08` 必需字段（运行后 `status: verified`） |
| `run.py` | 程序入口；公开 JSON 列表层提取 |
| `valid.csv` | 最近一次运行的有效商品，`docs/02` 的 9 列业务字段 |
| `task-result.json` | `docs/09` 的状态、计数、覆盖、质量例外和运行记录 |
| `run-summary.json` | 请求、状态码、逐商品审计汇总 |
| `diagnostics/<label>/` | 事件流、排除／失败／待处理清单、逐商品审计、robots 快照 |
| `tests/test_contract.py` | 币种、价格、描述清洗、选项、9 列 CSV 单测（不联网） |
| `tools/validate_output.py` | 离线校验 CSV 与任务结果（不联网） |

## 运行

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  python experiments/d01/sixmoondesigns/run.py `
  --out-dir experiments/d01/sixmoondesigns --label d01-run-001
```

默认值：`--max-products 30 --max-seconds 600 --delay 1.1 --max-attempts 3 --timeout 45`。
运行期不调用 LLM，不需要密钥、Cookie 或浏览器。

校验已发布结果：

```powershell
python experiments/d01/sixmoondesigns/tools/validate_output.py `
  --dir experiments/d01/sixmoondesigns --expected-products 29
```

本次 S4 试点：4 请求、29 有效、1 排除（Restocking Fee，缺主图）、0 失败；14.49s；USD 10.00–425.00；覆盖 29／112。入口币种与首商品页抽检均为 USD，抽检价 18.00 与 API 一致。

## 方案要点

- **市场参数是必填**：无 `?country=US` 时，站点按出口把 `Shopify.currency` 本地化为 CNY，`products.json` 首商品会返回 124.00；加 `?country=US` 后返回 USD 18.00。方案固定 `entry`／`api`／`spot` 三条 URL 的 `country=US`。
- **发现**：一次 `/products.json?limit=250&page=1&country=US`，取前 30 个商品；页面 1 的 payload 数量作为采样分母，不写成全站总量。
- **币种抽检**：入口页 `Shopify.currency.active` + 首个商品页 `product:price:currency`／`product:price:amount` 交叉核对；不一致时停止，不用符号猜币种。
- **价格**：变体 `price` 取最小有限正值；零价／无价商品排除并保留下载网址。
- **描述**：`body_html` 白名单清洗；空正文保留商品但记 `not_provided`，不拿名称补。
- **选项**：`options` + `variants` 的公开值并集；去掉数量组和 `Default Title`；保留 `Size#S|M` 形式。
- **站点边界**：只读公开 JSON 和一次商品页抽检；不登录、不下单、不访问购物车／账户／推荐接口。

## 边界与限制

- 只取 `products.json` 第 1 页的前 30 个商品，页面 1 当时为 112 个商品；不是全站覆盖。
- 列表层提取，不逐页补商品描述；描述缺失按 `not_provided` 记录。
- 站点按出口 IP 做市场本地化；本方案显式传 `country=US`，没有做多市场换算。
- 30 页是预算，不是长期稳定性或全站通过结论。
