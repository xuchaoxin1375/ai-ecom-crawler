# R16 第二站：shopthebulkstore

## 目的与边界

用一个与 familidoo 不同的站点验证：**只增加规则包，不改运行时**，仍能完成 discovery 和 product。站点、入口和 10 条商品来自 D01 S5 的已有证据；这里不重新做站点评估，也不改变 D01 结论。

边界：`shopthebulkstore.com` 分类页第 1 页，最多 10 个商品；静态 HTML；不登录、不下单、不绕过访问控制；不覆盖 sitemap 或分类分页策略。价格是公开的按磅价（per lb），保留单位价，不乘包装重量。

## 规则包

`../plans/shopthebulkstore-runtime.yaml`（`shopthebulkstore-us-r06`）只声明：

- 入口：`https://shopthebulkstore.com/candy/bulk-candy-unwrapped`；
- 链接选择器：`a.product-item-link`；
- 商品 URL 正则：`^/[a-z0-9][a-z0-9-]*$`；
- 字段回退：Product JSON-LD、meta、DOM 面包屑和描述块。

运行时代码与 familidoo 运行相同；没有为本站修改 `runtime/` 或 `executor/`。

## 结果

| 任务 | 类型 | 结果 | 请求 | 起止（UTC） |
| --- | --- | --- | --- | --- |
| `sb-discovery` | discovery | 10 个 URL，`COMPLETED` | 2（robots＋分类页） | 12:32:41–12:32:46 |
| `sb-product` | product | 10 个商品，`COMPLETED` | 12（robots＋分类页＋10 商品） | 12:32:41–12:33:14 |

- 日期／出口／客户端：2026-11-20（UTC），直连，Scrapling `FetcherSession`（静态），14 次目标请求。
- 有效／排除／失败：10／0／0。
- 币种：10／10 USD。
- 首个样本：Boston Baked Beans，5.99 USD，`Candy`／`Ferrara`，描述含“sold by the pound”。
- `task-result.json` 输出 `plan_id=shopthebulkstore-us-r06`，`failure_classes` 全零，`recovery` 全零。
- 两任务同一秒启动，同域 1 rps 串行；总目标请求 14 次。

## 复现

先验证规则包：

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py rule validate `
  --rule experiments/r06/plans/shopthebulkstore-runtime.yaml
```

创建任务并运行（复跑请换 `--task-id`，避免覆盖已有证据）：

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/shopthebulkstore-demo/tasks.db `
  --rule experiments/r06/plans/shopthebulkstore-runtime.yaml `
  --task-type discovery --task-id sb-discovery-rerun `
  --out-root experiments/r06/shopthebulkstore-demo/tasks --max-urls 10 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db experiments/r06/shopthebulkstore-demo/tasks.db `
  --rule experiments/r06/plans/shopthebulkstore-runtime.yaml `
  --task-type product --task-id sb-product-rerun `
  --out-root experiments/r06/shopthebulkstore-demo/tasks --max-products 10 --start

python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db experiments/r06/shopthebulkstore-demo/tasks.db `
  --out-root experiments/r06/shopthebulkstore-demo/tasks `
  --max-tasks 2 --per-domain-rps 1
```

校验：

```powershell
python experiments/r06/tools/validate_runtime.py --root experiments/r06/shopthebulkstore-demo
```

输出：`OK: runtime demo`，`sb-discovery` 10 URLs、`sb-product` 10 products。

## 结论与限制

- **已证明**：第二个站点只新增规则包即可跑通 discovery／product，运行时公共代码不变；分类页可作为入口页使用。
- **未证明**：sitemap、分类分页、公开 JSON、浏览器渲染、真实挑战页、跨环境导入、独立复跑和长期稳定性。
- 10 条是分类页第 1 页的有界样本，不是全站覆盖；D01 S5 的 30 条证据仍以 `experiments/d01/shopthebulkstore/` 为准。
