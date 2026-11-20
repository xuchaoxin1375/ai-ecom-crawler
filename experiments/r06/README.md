# R06 通用执行器最小原型

## 目的与边界

R06 验证一件事：**执行端只读 `manifest.yaml` 和声明式规则，就能跑完一个站，不再为站点写专用 `run.py`。**

这是最小原型，不是生产执行器。当前只支持：

- `kind: declarative`；
- `discovery.strategies: ["entry_links"]`，从一个入口页取商品链接；
- 静态 HTTP（Scrapling `FetcherSession`），并发固定为 1，请求间隔不低于 1000ms；
- 字段回退类型：`json_ld`、`css_text`、`css_attr`、`css_html`、`title`、`breadcrumb`、`option_groups`、`price_pair`、`canonical`、`constant`；
- 9 列业务 CSV、`task-result.json`、`run-summary.json` 和诊断文件。

暂不支持 sitemap／分类分页、浏览器渲染、登录、断点续跑、取消回收和完整 NDJSON 协议；这些不在本轮“首次采集”范围内。

方案语义补充：`discovery.product_url_patterns` 和 `scope.exclude` 按正则匹配，`scope.include` 按 glob 匹配路径。`docs/08` 的最终语义仍待统一，R06 只实现这个可执行子集。

## 目录

| 路径 | 内容 |
| --- | --- |
| `executor/` | 通用执行器：manifest 校验、发现、获取、提取、清洗、输出 |
| `plans/familidoo.yaml` | 站点声明式方案；只有少量站点覆盖 |
| `familidoo/` | 9 列 CSV、任务结果、运行摘要和 `r06-run-001`～`003` 诊断 |
| `tests/` | 30 个无网络契约与提取测试 |
| `tools/validate_output.py` | 输出目录校验器 |

## 运行

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.2" `
  python experiments/r06/run.py `
  --plan experiments/r06/plans/familidoo.yaml `
  --out-dir experiments/r06/familidoo `
  --label r06-run-004
```

复跑请使用新的 `--label`，保留已有诊断；不要覆盖 `r06-run-001`～`003`。根目录的 CSV 和 JSON 是最近一次运行，诊断目录按 label 分开。

测试：

```powershell
python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.2" `
  python -m unittest discover -s experiments/r06/tests -v
```

校验输出：

```powershell
python experiments/r06/tools/validate_output.py --dir experiments/r06/familidoo
```

## 试点结果（`r06-run-001` 构建观测，`r06-run-002` 复跑）

| 项 | 值 |
| --- | --- |
| 站点与范围 | `familidoo.fr` 首页商品链接；FR／fr-FR／EUR |
| 有效／排除／失败 | 6／0／0（三次运行相同） |
| 商品候选 | 6（入口页只展示 6 个商品链接；方案上限 20） |
| 请求 | 8（robots 1、入口 1、商品 6），0 重试（三次运行相同） |
| 运行墙钟 | 16.77s（`r06-run-001`）；19.8s（`r06-run-002`）；16.31s（`r06-run-003`，最终代码） |
| 首次有效商品 | 2026-11-20T06:13:35Z（`r06-run-001`） |
| 方案构建起点 | 2026-11-20T06:11:45Z（开始写站点方案） |
| `first_valid_product_s` | 110.0s（约 1 分 50 秒；仅 `r06-run-001`） |
| 复跑业务 CSV | `r06-run-001`～`003` 的 `valid.csv` SHA-256 相同：`D70458FD0177C39BBC4D4420B6A75D3C0EED47E5042C819359BA9F413EFD6D1E` |
| 运行期 LLM 调用 | 0 |
| 浏览器 | 未启动 |
| 描述状态 | 6／6 `complete` |
| 价格口径 | 6／6 预税价；展示价 TTC 与采用价相差 20%，例如 615.00 → 512.50 |
| 品牌 | 6／6 页面未公开 manufacturer，留空并记 `NOT_PROVIDED` |
| 任务结果 | `outcome=COMPLETED`、`stop_reason=NATURAL_END`、`coverage=PARTIAL` |

根目录的 `valid.csv`、`task-result.json`、`run-summary.json` 是最近一次运行（当前为 `r06-run-003`）；`r06-run-001` 的构建观测值记录在上表，`valid.csv` 副本和诊断保留在 `diagnostics/r06-run-001/`，`r06-run-002/` 和 `r06-run-003/` 也保留各自的任务结果与运行摘要。三次运行相隔几分钟，只能说明同方案同环境可复现，不是独立复跑、漂移测试或跨环境验证。

字段命中路径（6／6 一致）：

| 字段 | 实际来源 |
| --- | --- |
| `name` | `h1[itemprop=name]` |
| `price.amount` | PrestaShop `product:pretax_price:amount`／`product:price:amount` 对，取较小者 |
| `price.currency` | `product:pretax_price:currency` |
| `primary_image_url` | `og:image` |
| `description_html` | `div.product_description_container` |
| `category` | 面包屑最深非首页项 |
| `source_url` | `link[rel=canonical]` |

`COMPLETED` 只表示入口页这个有界范围处理完了；`coverage=PARTIAL` 表示不是全站覆盖。

## 和 R04 的差异

| 项 | R04 | R06 |
| --- | --- | --- |
| 执行方式 | 站点专用 `run.py` | 通用执行器读 `plans/familidoo.yaml` |
| `kind` | `program` | `declarative` |
| 站点代码 | 有 | 无 |
| 构建观测 | 404.0s，含一次失败和修复 | 110.0s，首次运行即通过 |
| 运行墙钟 | 13.28s | 16.77s |
| 样本 | 首页 6 个 | 首页 6 个 |

R06 的方案构建时间不能直接和 R04 比：R06 的通用执行器是在同一会话里先写好的，110 秒只计“写站点方案到首个有效商品”，不计执行器开发；R04 的 404 秒计的是站点专用 runner 的构建。两者都不是受控基准，只作过程记录。可以确认的是：**R06 的站点侧不再需要写代码，方案只保留声明式覆盖。**

## 局限

- 入口页只展示 6 个商品，未做 10～20 个随机抽样；6／6 是小样本全量，不是全站覆盖。
- 只验证一个站点、一次运行；没有独立复跑和跨环境导入。
- 只支持静态 HTML；没有浏览器、登录、挑战处理或 JavaScript 渲染。
- 只支持一个入口页；没有 sitemap、分类分页、公开 JSON 或详情补全。
- 没有断点、取消、幂等键和恢复；`task-result.json` 只覆盖最小状态与计数。
- `pyyaml` 通过 `uv run --with` 临时提供，尚未加入 Scrapling 项目的锁文件。

## 下一步

- 用第二个站复测“只写方案、不写代码”的构建时间，避免把单站结果当成通用结论。
- 增加 `sitemap` 或分类入口，才能做 10～20 个商品的随机抽查和更完整的范围。
- 把 R06 的输出与 `docs/08`、`docs/09` 的差异列清楚，再决定哪些字段进入 v1 执行器。
- 维护、漂移和长期稳定性仍后置（J08）；本轮不据此判断维护成本。
