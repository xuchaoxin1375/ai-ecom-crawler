# D01 S5 shopthebulkstore.com — Scrapling 分类目录试点

## 范围与环境

- 站点：`https://shopthebulkstore.com/`，S5，US／en-US／USD。
- 范围：`/candy/bulk-candy-unwrapped` 分类页第 1 页，工具栏当时为 `Items 1-30 of 62`；取该页 30 个商品链接并逐页提取。
- 访问边界：robots 先取；`*` 组禁止 `/checkout/`、`/customer/`、`/catalog/`、`/catalogsearch/`、`/review/`、`/sendfriend/` 和查询串筛选；只请求允许的分类、商品和 sitemap 路径。站点另有 AI bot 专用 disallow 组，本方案使用普通桌面客户端路径，不切换 UA 规避。
- 框架：Scrapling 0.5.1，`FetcherSession`（curl_cffi，静态 HTML）；单并发、间隔 1.1s；LLM 0、浏览器 0。
- 环境：Windows，Python 3.13.13；直连（`HTTPS_PROXY`／`HTTP_PROXY` 未设置，`NO_PROXY` 已设置）。

## 运行

| label | 结果 | 请求 | 墙钟 | 有效／排除／失败 | 停止原因 |
| --- | --- | ---: | ---: | --- | --- |
| `dry-run-001` | 3 商品干跑，验证描述合并与按磅语义 | 6 | 12.01s | 3／0／0 | `BUDGET_EXHAUSTED`（3 商品上限） |
| `d01-run-001` | 30 商品全量；`Coconut Bon Bons` 单位记为 unknown | 33 | 71.26s | 30／0／0 | `BUDGET_EXHAUSTED` |
| `d01-run-002` | 最终发布结果；单位正则修复后重跑 | 33 | 66.67s | 30／0／0 | `BUDGET_EXHAUSTED` |

最终运行：robots 1、sitemap 1、分类页 1、商品页 30；全部 200；重试 0。

## 失败与修复

`d01-run-001` 的唯一单位缺口：`Coconut Bon Bons` 的售价说明是 `Price is per 12oz. bag`，原正则只接受 `per bag` 这类无尺寸写法，因此 `price_unit` 记为 unknown。修正为允许 `per <size> bag`，并把容器单位（bag／box／pack／dozen）排在重量单位之前，`d01-run-002` 记为 `per_bag`，`price_unit_text` 保留原文 `Price is per 12oz. bag`。

两次全量运行的 30 条 `product-audit.jsonl` 按业务字段比较差异 0；唯一差异是该商品的单位字段。`valid.csv` 由 `d01-run-002` 覆盖发布，`d01-run-001` 的逐商品审计仍在诊断目录。

## 结果

- 有效 **30**／排除 **0**／失败 **0**。
- 价格：2.44–11.99 USD；币种 30／30 USD。
- 单位：`per_lb` 27、`per_oz` 2、`per_bag` 1；价格是公开单位价，不乘包装重量。描述中保留 `Price is per lb.`／`per oz.`／`per 12oz. bag` 等原文。
- 库存：InStock 27、OutOfStock 3；3 个缺货商品仍有公开价，进入有效集；是否显示加购按钮不作为有效性规则。
- 描述：30／30 `complete`，长度 115–544 字符；按 DOM 顺序合并 overview 与 description，去掉被更长块包含的短块；未使用名称补正文。
- 品牌：24 个有品牌，6 个原站未提供（Coconut Bon Bons、Coconut Macaroons、Flying Saucers、Flying Saucers Sour、Jordan Almonds Assorted、Jordan Almonds White）；已核对其中一页，Product JSON-LD 与 DOM 都没有 brand／manufacturer 字段。
- `quality_exceptions`：6 条，均为 `brand: not_provided`。
- 覆盖：分类页 62 个商品，处理 30 个；`PARTIAL`，不写成全站覆盖。sitemap 2,528 条，30 个候选全部命中。
- 分类分布：Candy Unwrapped 24、Easter Candy 3、Halloween Candy Unwrapped 2、Valentine Candy Unwrapped 1。
- 计数口径：`discovered_urls=33` = robots／sitemap／分类页 3 个发现请求 + 30 个商品候选，沿用 S1／S2／S4 的现有计数写法；商品候选与有效数均为 30。

## 输出校验

```powershell
python experiments/d01/shopthebulkstore/tools/validate_output.py `
  --dir experiments/d01/shopthebulkstore --expected-products 30
```

结果：`{"rows": 30, "problems": []}`。

## 证据位置

- `valid.csv`、`task-result.json`、`run-summary.json`：`d01-run-002` 发布结果。
- `diagnostics/dry-run-001/`：3 商品干跑。
- `diagnostics/d01-run-001/`：单位缺口与首次全量证据。
- `diagnostics/d01-run-002/`：最终结果、逐商品审计、robots 快照、分类链接、sitemap 交叉核对。
- `tests/`、`tools/validate_output.py`：离线测试与结果校验。

## 限制

- 只取 Candy Unwrapped 分类第 1 页的 30 个商品（当时共 62 个）；不是该分类全量，也不是全站覆盖。
- 首页 `/all-products` 当时显示 2,381 个商品，仅作构建期观察，不是本运行的覆盖分母。
- 静态 HTML 路径；未验证浏览器指纹、挑战页、登录或加购。
- 站点描述块可能很短；本批全部为 `complete`，但“只含商品名／单位说明”的页面会记 `partial`。
- 单位识别依赖页面可见文案；新写法（如 `per 12oz. bag`）需要补正则，不能从重量控件反推。
- 站点结构、robots 与 sitemap 会变化；D01 执行前按当日结果复核。
