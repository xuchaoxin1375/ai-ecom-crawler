# shopthebulkstore.com — S5 分类目录方案包

D01 S5 单站试点的 Scrapling 实现。站点：`https://shopthebulkstore.com/`，市场 US／`en-US`／USD，单站上限 30 个商品页或 10 分钟。

## 组成

| 路径 | 内容 |
| --- | --- |
| `manifest.yaml` | 方案入口，满足 `docs/08` 必需字段（运行后 `status: verified`） |
| `run.py` | 程序入口；分类页发现 + 商品页提取 |
| `valid.csv` | 最近一次运行的有效商品，`docs/02` 的 9 列业务字段 |
| `task-result.json` | `docs/09` 的状态、计数、覆盖、质量例外和运行记录 |
| `run-summary.json` | 请求、状态码、逐商品审计汇总 |
| `diagnostics/<label>/` | 事件流、排除／失败／待处理清单、逐商品审计、robots 快照、分类链接与 sitemap 交叉核对 |
| `tests/test_contract.py` | JSON-LD、描述合并、按磅语义、选项、9 列 CSV 单测（不联网） |
| `tools/validate_output.py` | 离线校验 CSV 与任务结果（不联网） |

## 运行

```powershell
python -m uv run --project experiments/framework-compare/scrapling `
  python experiments/d01/shopthebulkstore/run.py `
  --out-dir experiments/d01/shopthebulkstore --label d01-run-001
```

默认值：`--max-products 30 --max-seconds 600 --delay 1.1 --max-attempts 3 --timeout 45`。
运行期不调用 LLM，不需要密钥、Cookie 或浏览器。

校验已发布结果：

```powershell
python experiments/d01/shopthebulkstore/tools/validate_output.py `
  --dir experiments/d01/shopthebulkstore --expected-products 30
```

本次 S5 试点（`d01-run-002`）：33 请求、30 有效、0 排除、0 失败；66.67s；USD 2.44–11.99；单位 27 个 per_lb、2 个 per_oz、1 个 per_bag；描述 30/30 完整；6 个商品原站未提供品牌；3 个缺货商品保留公开价并进入有效集。分类工具栏为 62 个商品，覆盖 30；sitemap 交叉核对 30/30。

同方案前一次运行 `d01-run-001` 把 `Coconut Bon Bons` 的 `Price is per 12oz. bag` 记为 unknown；修正单位正则后重跑，两次运行的 30 条业务字段审计差异为 0，仅该商品的单位字段从 unknown 变为 per_bag。

## 方案要点

- **入口**：`/candy/bulk-candy-unwrapped` 分类页第 1 页，工具栏当时为 `Items 1-30 of 62`；取该页 30 个商品链接。商品 canonical 使用无 `www` 的 `shopthebulkstore.com` 主机。
- **交叉验证**：同一运行读取 `/sitemap.xml`，核对 30 个商品 URL 是否都在 sitemap 中；本次 30／30 命中。分类页仍是主入口，sitemap 只作交叉核对。
- **价格**：Product JSON-LD `offers.price`／`lowPrice`；回退 `product:price:amount` 和主价格框。价格是公开的单位价（多为 per lb），不乘包装重量。
- **按磅语义**：从描述块和售价区识别 `Price is per lb.`／`Price is per item.`；描述未包含时按 `docs/02` 补在开头独立段。内部审计记录 `price_unit`，不进入 9 列 CSV。
- **描述**：按 DOM 顺序合并 `.product.attribute.overview` 与 `.product.attribute.description`，去掉被更长块包含的短块；白名单清洗，保留列表／表格。只含商品名和计价单位的描述记 `partial`，不冒充完整。
- **库存**：JSON-LD `OutOfStock` 且有公开价格的商品仍进入有效集；是否显示加购按钮不作为有效性规则。
- **站点边界**：robots 的 `*` 组禁止 `/checkout/`、`/customer/`、`/catalog/`、`/catalogsearch/`、`/review/`、`/sendfriend/` 和查询串筛选；本方案只取允许的分类、商品和 sitemap 路径。站点另有 AI bot 专用 disallow 组，方案使用普通桌面客户端路径，不切换 UA 规避。

## 边界与限制

- 只取 Candy Unwrapped 分类第 1 页的 30 个商品（当时共 62 个）；不是全站覆盖，也不是该分类全量。
- 首页 `/all-products` 当时显示 2,381 个商品，仅作构建期观察，不是本运行的覆盖分母。
- 静态 HTML 路径；未验证浏览器指纹、挑战页、登录或加购。
- 描述块可能很短；短描述按实际内容记 `complete` 或 `partial`，不拿名称补正文。
- 站点结构、robots 与 sitemap 会变化；D01 执行前按当日结果复核。
