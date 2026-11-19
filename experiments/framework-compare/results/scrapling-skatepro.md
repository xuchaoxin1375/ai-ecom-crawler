# Scrapling × skatepro.es（第 2 轮，9 列合同）

| 项 | 值 |
| --- | --- |
| 框架 / 版本 | Scrapling 0.5.1（`FetcherSession`，curl_cffi，静态 HTML） |
| 站点 / 市场 | `https://www.skatepro.es/`，ES／`es-ES`／EUR |
| 模型变体 | high |
| 方案 | `experiments/framework-compare/scrapling/skatepro/`，`plan_version` `2026.11.19-2`，`status: candidate` |
| 运行期 LLM 调用 | 0 |

## 构建与运行

| 指标 | 值 | 口径 |
| --- | --- | --- |
| `build_started_at` | 2026-11-19T02:57:00Z | 首次站点请求前回推约 3 分钟（估算，可能低估 3–5 分钟） |
| `first_plan_s` | 796 | 从 `build_started_at` 到 `manifest.yaml` 首次完整（03:10:16Z） |
| `first_valid_product_s` | 936.1 | 从 `build_started_at` 到主运行首个有效商品（03:12:36Z） |
| `implementation_revisions` | 2 | v1 初始方案；v2 修复任务新增 `availability` |
| 主运行 | 34 请求，398.8s，200×34，0 重试 | `diagnostics/run-001/` |
| 修复复跑 | 34 请求，404.7s，200×34 | `diagnostics/fix-rerun/` |
| 全部运行请求 | 74 | 冒烟 6 + 主运行 34 + 复跑 34 |
| 构建期侦查 | 约 9 次 | 方案成形前的手工探测，未计入运行 |

## 结果

- 有效 **30**／排除 **0**／失败 **0**；`partial_description_products = 0`。
- 正文状态：complete 30、partial／fallback／not_provided／failed 均 0。
- `quality_exceptions` **9**：正文完整但缺可空字段（7 条无规格表、4 条无公开选项，部分重合）。
- 覆盖 `PARTIAL`：分母为运行内 sitemap 的 6660 个商品型 URL，覆盖 30；另有 3 个已发现未访问的导航入口。
- 停止原因 `BUDGET_EXHAUSTED`（30 页任务上限），`outcome = PARTIAL`，`state = FINISHED`。

质量抽样：价格取变体最低正价（如 T 恤 123 变体→14.95 EUR），币种来自同报价 JSON-LD；主图取 1800px 原图；分类／品牌取本地化 JSON-LD；正文为正文块 + 规格表，交叉销售与评价已剔除。

## 修复任务

- 内容：新增 `docs/02` 可空字段 `availability`（JSON-LD `offers.availability` 聚合 + PHP2JS `stock_level` 交叉核对）。
- 耗时 **7.5 分钟**（03:19:45Z→03:27:16Z，含复跑 6.7 分钟）；输出校验与 12 项单测通过。
- 复跑：30/30 有效，`availability = in_stock ×30`；与 v1 的 11 个共享字段逐条比对 **0 差异**，未删除或放宽样本。

## 错误与限制

- 无 429／403／5xx／挑战页；`Retry-After` 分支未实测。
- 构建期一次 `NameError`（未发请求前修复）；`config.DEFAULT_PLAN_VERSION` 一开始就写成最终的 `2026.11.19-2`，使 v1 的两个运行把版本标签记成 v2（日志未改写；`run-001` 审计无 `availability` 字段可证明是 v1 代码）。PyYAML 不在固定环境，manifest 仅做顶层键扫描校验。
- 出口 IP 被站点判断为美国，页面提示“配送至美国”，报价仍为 EUR、JSON-LD 配送／退货地区为 ES；未设国家 Cookie、未换汇。
- 静态 HTML 无含税／未税声明，`tax_basis = unknown_not_stated`。
- 30 页为预算上限，不是全站覆盖；未做第二台机器的干净环境导入（A10）。
- `run-001` 的顶层 `valid.csv` 被后续复跑覆盖，仅保留逐商品审计与汇总；该限制已写入运行记录。

## 产物

- 方案包：`experiments/framework-compare/scrapling/skatepro/`
- 任务结果：同目录 `task-result.json`、`valid.csv`
- 运行记录：同目录 `run-log.md`
- 指标：`scrapling-skatepro.json` / 本文件
