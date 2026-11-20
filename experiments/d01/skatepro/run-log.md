# D01 S2 skatepro.es — Scrapling 试点运行记录

## 范围与环境

- 站点：`https://www.skatepro.es/`，S2，ES／es-ES／EUR。
- 范围：入口主菜单分类网格，最多 30 个唯一商品页；10 分钟墙钟上限。
- 访问边界：robots 允许公开分类／商品页；不请求 `*/catalog`、`/adminshop`、`/static`、`*/wishlist`；单并发、**10 秒**端到端间隔，符合站点公布的 `Crawl-delay: 10`。
- 框架：Scrapling 0.5.1，`FetcherSession`（curl_cffi，静态 HTML）；运行期不调用 LLM，不启动浏览器。
- 环境：Windows，Python 3.13.13；Scrapling venv；直连（`HTTPS_PROXY`／`HTTP_PROXY` 未设置，`NO_PROXY` 已设置）。
- 数据合同：`docs/02` 的 9 列业务 CSV；内部追溯字段保留在 `task-result.json` 和 `product-audit.jsonl`。

## 运行

| 项 | 值 |
| --- | --- |
| label | `d01-run-001` |
| 开始／结束（UTC） | 2026-11-20T00:29:26Z／00:35:44Z |
| 墙钟 | 378.23 s |
| 请求 | 34（robots 1、入口 1、分类 1、sitemap 1、商品 30）；全部 200；重试 0 |
| 有效／排除／失败 | 30／0／0 |
| 部分描述 | 0 |
| 停止原因 | `BUDGET_EXHAUSTED`（30 页上限） |
| 状态 | `FINISHED`／`PARTIAL` |

发现：入口主菜单有 450 个候选分类；本次只访问 `c2.htm` 一个分类，取 30 个唯一商品；另有 3 个已发现未访问的导航入口（`c2.htm?page=2`、`c251.htm`、`c252.htm`），`pending_navigation_entries = 3`。

覆盖：运行内 `sitemap.xml` 声明 6,665 个商品型 URL；本次覆盖 30，`coverage.status = PARTIAL`，不写成全站完成。

## 输出与质量

- `valid.csv`：9 列、30 行；30 个唯一商品 URL。
- 价格：0.95–399.95 EUR，全部为有限正数；币种 30／30 来自同报价证据。
- 名称、主图、描述：均非空；描述状态 30／30 `complete`。
- `quality_exceptions`：9 条，均为正文完整但缺可空字段（`specifications`／`options` 未提供），不是正文失败。
- 计数：`product_candidates = 30`，`processed = 30`，`valid = 30`，`excluded = 0`，`failed = 0`，`pending = 0`，`in_flight = 0`。
- 运行期 LLM 调用 0；浏览器启动 0。

## 输出校验

```powershell
python experiments/d01/skatepro/tools/validate_output.py --dir experiments/d01/skatepro
```

结果：`{"rows": 30, "problems": []}`。

## 复跑说明

本 D01 S2 包本次只跑了一次。相同实现的框架对比目录已有 `diagnostics/run-001` 与 `diagnostics/fix-rerun` 两次 30／30 记录，且共享字段差异为 0；本次沿用该稳定性证据，不把它算作本包的新复跑。S1 javaestate 已完成本 D01 的独立复跑闭环。

## 证据位置

- `valid.csv`、`task-result.json`、`run-summary.json`：本次发布结果。
- `diagnostics/d01-run-001/`：事件流、排除／失败／待处理清单、逐商品审计、robots 快照。
- `manifest.yaml`、`README.md`：方案入口与运行说明。
- `tests/`、`tools/validate_output.py`：离线测试与结果校验。

## 限制

- 只走入口一个分类网格，30 页是预算；未覆盖其余分类和 6,665 个 sitemap 商品。
- 静态 HTML；未验证 JS 展开区、浏览器渲染或挑战页。
- 站点按出口 IP 提示“配送至美国”，但报价仍为 EUR，JSON-LD 配送／退货政策指向 ES；未设国家 Cookie，未换汇。
- 静态页面未声明含税／未税，税价口径保持 `unknown_not_stated`。
- 可空字段缺失（规格／选项）记录在 `quality_exceptions`，不冒充完整规格。

## 复跑命令

```powershell
experiments/framework-compare/scrapling/.venv/Scripts/python.exe experiments/d01/skatepro/run.py `
  --out-dir experiments/d01/skatepro `
  --label d01-rerun
```
