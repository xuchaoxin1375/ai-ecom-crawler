# Scrapling 0.5.1 — javaestate.com 实验指标

**站点**：`https://javaestate.com/`（S1，US／en-US／USD，静态 HTML＋站点地图）  
**方案**：`experiments/framework-compare/scrapling/javaestate/`（`plan_id: javaestate-us-scrapling`，v1 `2026.11.19-1`，v2 `2026.11.19-2`）  
**运行环境**：Windows 11，Python 3.13.13，Scrapling 0.5.1，静态 `FetcherSession`（curl_cffi），不启动浏览器。  
**网络**：环境存在 `HTTP_PROXY`／`HTTPS_PROXY`／`NO_PROXY`；未记录代理值，未独立测量出口。  
**模型调用**：运行期 `runtime_llm_calls = 0`。

## 构建与首次结果

`first_*` 均从 `build_started_at` 起算，不是从有界运行开始时间起算。

| 指标 | 值 |
| --- | --- |
| `build_started_at` | 2026-11-18T23:45:00Z（会话开始，分钟精度；首个构建产物 23:48:57Z） |
| `first_plan_at` | 2026-11-19T00:07:05Z |
| `first_plan_s` | **1325.0 s**（22 分 05 秒） |
| `first_valid_product_at` | 2026-11-19T00:07:22Z |
| `first_valid_product_s` | **1342.8 s**（22 分 22.8 秒） |
| `build_finished_at` | 2026-11-19T00:12:19Z（含修复任务与复跑验收） |
| `build_elapsed_s` | 1639.0 s（27 分 19 秒） |
| `implementation_revisions` | 3 |

修订记录：

- rev1：初始方案包、22 列 CSV、诊断、README、单元测试。
- rev2：冒烟后发现价格解析把歧义的 `1,234` 当作 1234；改为拒绝单一分隔符后三位数字。
- rev3：修复任务 v2，增加基于公开 `taxable` 标志的 `tax_basis` 提取。

## 有界运行

| 指标 | 主运行（v1） | 修复复跑（v2） | 同方案复跑（v2） |
| --- | --- | --- | --- |
| 标签 | `run-001` | `fix-rerun` | `run-002` |
| 开始／结束（UTC） | 00:07:15／00:08:06 | 00:11:11／00:12:02 | 00:12:35／00:13:25 |
| 墙钟 | 51.12 s | 50.9 s | 50.36 s |
| 请求数 | 34 | 34 | 34 |
| 重试 | 0 | 0 | 0 |
| 有效商品 | 30 | 30 | 30 |
| 排除 | 0 | 0 | 0 |
| 失败 | 0 | 0 | 0 |
| 部分正文 | 0 | 0 | 0 |
| 停止原因 | `BUDGET_EXHAUSTED` | `BUDGET_EXHAUSTED` | `BUDGET_EXHAUSTED` |
| 结果 | `PARTIAL` | `PARTIAL` | `PARTIAL` |

请求构成：robots 1、入口 1、sitemap index 1、商品 sitemap 1、商品页 30；全部 HTTP 200。

覆盖：商品 sitemap 声明 **707** 个 `<url><loc>`，本次按范围只取前 30 个唯一商品路径；`coverage.status = PARTIAL`，不是全站完成。

## 质量

| 检查项 | 结果 |
| --- | --- |
| 22 列 CSV | 通过；`tools/validate_output.py` OK |
| 有限正价 | 30／30 |
| 币种 | 30／30 `USD`，来自 JSON-LD `offers.priceCurrency`（同一报价） |
| 主图 | 30／30 |
| 正文状态 | `complete` 30；`partial` 0；`fallback` 0；`not_provided` 0；`failed` 0；状态分支由离线测试覆盖（DOM 缺失、DOM 明显更短、仅 meta 摘要、无正文） |
| 选项 | 30 个样本均为单变体，`attributes` 为空；选项逻辑由单元测试覆盖，未由本次真实样本触发 |
| 品牌 | Big Train、Ghirardelli；无店名冒充品牌 |
| 库存 | `in_stock` 27、`out_of_stock` 3；缺货有价变体仍计入有效集 |
| 分类 | Powdered Beverage Mixes、Condiments & Sauces |
| 去重 | 30 个唯一 `/products/<handle>`，无重复 |
| 公式保护 | 文本单元格以 `= + - @` 开头时加单引号；金额保持数值 |
| 429 | 未出现 |
| 请求间隔 | 34 次尝试最小间隔 1.372 s（并发 1；目标端到端起 1.1 s） |

## 修复任务

| 项 | 值 |
| --- | --- |
| 状态 | 通过 |
| 开始／结束（UTC） | 2026-11-19T00:08:45Z／00:12:19Z |
| `fix_minutes` | **3.6** |
| 类型 | 增加一个 `02` 可空字段的实际提取（`tax_basis`） |
| 改动 | v1 的 `tax_basis` 是常量 `unknown_not_stated`；v2 从嵌入 variants 的 `taxable` 标志推导：全 false → `no_tax_applied`，全 true → `unknown_not_stated`，混合 → `mixed_taxability`，缺失 → `unknown_not_stated` |
| 改动文件 | `normalize.py`、`extract.py`、`runner.py`、`config.py`、`manifest.yaml`、`README.md`、`tests/test_contract.py`、`tools/validate_output.py` |
| 行变化 | 30 行中 28 行 `tax_basis` 变化（`no_tax_applied` 28，`unknown_not_stated` 2） |
| 复跑 | 34 请求、30 有效、0 排除、0 失败、50.9 s、0 模型调用 |
| 样本 | 同一 30 个商品网址；未增删样本 |

同一 v2 方案再跑一次（`run-002`）：业务字段与 `fix-rerun` 完全一致，只有 `task_id` 和 `extracted_at` 变化；30 有效、0 排除、0 失败、50.36 s、0 模型调用。

## 错误

运行期错误：无。两次完整运行均 34 个请求、全部 200、无重试。

构建期错误：

- 单元测试发现 `1,234` 被错误接受为 1234；已修复为歧义拒绝。
- 固定环境没有 YAML 解析器，`manifest.yaml` 未做机器解析校验；已逐行人工检查，未安装包。

## 未完成项与限制

- 只覆盖 sitemap 前 30 个商品；剩余 677 个商品未访问，不能声称全站完成。
- 本次 30 个样本全部是单变体，选项提取未被真实多 variant 商品触发；修复任务因此选择 `tax_basis`，未改样本。
- 本次样本全部有完整正文；`partial`／`fallback`／`not_provided`／`failed` 状态未由真实样本触发。
- 本次 30 个样本无零价／缺价商品；另用 `java-jacket-drink-sleeves-8-24-oz-copy` 构建诊断验证零价排除（未入 `valid.csv`），缺价/非法金额仍仅由单元测试覆盖。
- 未触发 429，`Retry-After` 退避未获真实运行验证。
- 所有样本有 Product JSON-LD；无 JSON-LD 的回退路径在构建诊断 `java-jacket-drink-sleeves-8-24-oz-copy` 上实际走通（`og_price_currency`、h1、嵌入 vendor），但该商品未进入有效集。
- `tax_basis` 只依据公开 `taxable` 标志，不证明含税／未税定价。
- 静态 HTML；未渲染 JS-only 标签页或小部件。
- 峰值内存未测。
- 代理值未记录，出口未独立测量。

## 产物

- 方案与入口：`experiments/framework-compare/scrapling/javaestate/manifest.yaml`、`run.py`
- 有效集：`experiments/framework-compare/scrapling/javaestate/valid.csv`
- 任务结果：`experiments/framework-compare/scrapling/javaestate/task-result.json`
- 运行记录：`experiments/framework-compare/scrapling/javaestate/run-log.md`
- 主运行证据：`diagnostics/run-001/`
- 修复复跑证据：`diagnostics/fix-rerun/`
- 同方案复跑证据：`diagnostics/run-002/`
- 零价排除与无 JSON-LD 回退诊断：`diagnostics/zero-price-probe.json`

## 结论

在声明的 30 商品页／10 分钟边界内，Scrapling 0.5.1 静态 `FetcherSession` 方案可以独立复跑，产出 30 个符合 22 列与正价／币种／主图要求、正文状态为 `complete` 的有效商品，运行期无 LLM 调用。结果只能证明 javaestate.com 的静态商品页路径，不代表全站覆盖、选项/零价/429 的实站验证或长期稳定性。
