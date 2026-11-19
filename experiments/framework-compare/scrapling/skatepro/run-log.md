# 运行记录 — skatepro.es / Scrapling 0.5.1

本轮为 `docs/13` 第 2 轮（9 列合同），站点 S2 见 `docs/14`。所有时间戳为 UTC，来自运行产物或文件时间。

## 环境

| 项 | 值 |
| --- | --- |
| 框架 | Scrapling 0.5.1（`scrapling[fetchers]`，`FetcherSession` / curl_cffi，静态 HTML） |
| 运行命令 | `python -m uv run --project experiments/framework-compare/scrapling python ...` |
| Python / OS | CPython 3.13（uv 项目环境）；Windows 10.0.19045 |
| 浏览器 | 未启动（`browser_launched: false`） |
| 代理 | 环境存在 `HTTP_PROXY`/`HTTPS_PROXY`（值未记录，未独立测量出口）；站点按出口 IP 提示“配送至美国”，报价仍为 EUR |
| 模型变体 | high（本轮控制变量） |
| 运行期 LLM 调用 | 0 |

## 复用范围（同一框架内）

只读取 `experiments/framework-compare/scrapling/` 下的实现，未打开、复制或运行 `scrapy/`、`crawlee/` 任何文件。

- 复用：`javaestate/javaestate_scraper/http.py` 的分页节奏与重试／停止骨架（并发 1、端到端间隔、429/403 停止、`Retry-After` 上限）；`export.py` 的 CSV/JSON 写法和公式保护；`normalize.py` 的 HTML 白名单清洗、选项序列化、单元格保护写法。
- 重写：`config.py`、`discovery.py`（分类／分页／sitemap 分母）、`extract.py`（PHP2JS 变体 + JSON-LD Product/ProductGroup）、`runner.py` 的任务结果与计数、`tools/`、`tests/`。
- 未复用：javaestate 的站点选择器、价格来源和方案标识。

## 时间线

| 时间（UTC） | 事件 | 证据 |
| --- | --- | --- |
| 02:57:00 | 构建开始（`build_started_at`） | 首次站点探测（03:00:14Z 的 robots 响应头）之前约 3 分钟；构建前在读任务文档，按首次探测前一刻取值，见“指标口径” |
| 03:00:14 | 首次站点请求：robots.txt（200） | 抓取响应头 |
| 03:00:24–03:03 | 侦查：入口页、sitemap、分类页 c2、商品页样本 | 本机 curl |
| 03:10:16 | 首次完整方案：`manifest.yaml` + 入口 + 模块可运行 | `manifest.yaml` 文件时间 |
| 03:10:29–03:11:31 | 冒烟运行 `smoke-001`（2 个商品） | `diagnostics/smoke-001/` |
| 03:11:46–03:18:25 | **主运行 `run-001`**（30 个商品，计划 v1） | `diagnostics/run-001/` |
| 03:19:45 | 修复任务开始（增加可空字段 `availability`） | 首次修复编辑 |
| 03:20:32–03:27:16 | **修复复跑 `fix-rerun`**（30 个商品，计划 v2） | `diagnostics/fix-rerun/` |
| 03:29 | 输出契约校验 + 单测通过 | `tools/validate_output.py`、`tests/test_contract.py` |

### 指标口径

- `first_valid_product_s` 与 `first_plan_s` 都从 `build_started_at` 起算；该值取首次站点探测前一刻（03:00:14Z 的 robots 响应头）回推约 3 分钟，误差约 3–5 分钟且偏向低估，因为之前的文档阅读没有独立时间戳。
- 主运行首个有效商品：03:12:36Z → `936.1 s`。
- 首次完整方案：03:10:16Z → `796 s`。
- 修复复跑首个有效商品：03:21:21Z → `1461.7 s`（同一构建起点，仅供对照，不是独立任务）。

## 命令

```bash
# 冒烟
python -m uv run --project experiments/framework-compare/scrapling \
  python experiments/framework-compare/scrapling/skatepro/run.py \
  --out-dir experiments/framework-compare/scrapling/skatepro --label smoke-001 \
  --max-products 2 --build-started-at 2026-11-19T02:57:00Z

# 主运行（计划 v1）
python -m uv run --project experiments/framework-compare/scrapling \
  python experiments/framework-compare/scrapling/skatepro/run.py \
  --out-dir experiments/framework-compare/scrapling/skatepro --label run-001 \
  --max-products 30 --plan-version 2026.11.19-1 --build-started-at 2026-11-19T02:57:00Z

# 修复复跑（计划 v2，新增 availability）
python -m uv run --project experiments/framework-compare/scrapling \
  python experiments/framework-compare/scrapling/skatepro/run.py \
  --out-dir experiments/framework-compare/scrapling/skatepro --label fix-rerun \
  --max-products 30 --plan-version 2026.11.19-2 --build-started-at 2026-11-19T02:57:00Z

# 校验（不联网）
python -m uv run --project experiments/framework-compare/scrapling \
  python experiments/framework-compare/scrapling/skatepro/tools/validate_output.py \
  --dir experiments/framework-compare/scrapling/skatepro
python -m uv run --project experiments/framework-compare/scrapling \
  python -X utf8 -m unittest discover -s experiments/framework-compare/scrapling/skatepro/tests
```

## 访问边界与 robots

`robots.txt`（运行内抓取，快照见 `diagnostics/<label>/robots.txt`）：

- `User-agent: *`：`disallow: /adminshop`、`/static`、`*/catalog`、`*/wishlist`。
- `Crawl-delay: 10` 只写在 `meta-externalagent` 段；按任务与 D01 S2 的边界，对 `*` 也使用 **10s 端到端间隔、并发 1**。
- `Sitemap: https://www.skatepro.es/sitemap.xml`。

实际访问：robots、入口、分类 `c2.htm`、sitemap、30 个商品页；没有请求 `/catalog`、购物车、账户、心愿单或搜索接口。未登录、未下单、未绕过任何访问控制。

## 运行结果

| 运行 | 请求 | 状态码 | 重试 | 有效 | 排除 | 失败 | 部分正文 | 墙钟 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| smoke-001（2 页） | 6 | 200×6 | 0 | 2 | 0 | 0 | 0 | 61.3s |
| **run-001（计划 v1）** | 34 | 200×34 | 0 | **30** | 0 | 0 | 0 | 398.8s |
| **fix-rerun（计划 v2）** | 34 | 200×34 | 0 | **30** | 0 | 0 | 0 | 404.7s |

- 未出现 429、403、5xx、挑战页或传输错误；因此无需退避，也没有触发访问停止。
- 30 个候选全部处理完成（`pending_products = 0`，`in_flight_products = 0`）；预算停止来自任务 30 页上限。
- 覆盖：`coverage.status = PARTIAL`，分母为运行内 `sitemap.xml` 的 6660 个商品型 URL（观测时点），覆盖 30；另有 3 个已发现未访问的导航入口（`c2.htm?page=2` 与前沿内两个分类）。
- 排除／失败清单均为空表头文件；零价、无价样本本批未出现，逻辑由单测覆盖，未伪造结果。

### 字段抽样核对

- 价格：`218-36511` 页面可见 `69,95 €`，产出 69.95 EUR；`243-35728` 卡片价 `49,95 €`，产出 49.95 EUR，一致。
- 变体：`99-33114`（T 恤）123 个变体，最低价 14.95 EUR；选项 `Talla#4-6|…|XXL~Color#…`（14 色）。
- 正文：`#product_description` 正文 + `#product_specifications` 规格表（如 34 行）合并输出；`Piezas compatibles`、`Fabricante`、评价未进入正文。
- 分类／品牌：来自本地化 JSON-LD（如 `Ropa > Camisetas`、`SkatePro`；`Patinetes > Freestyle`、`Longway`）。
- 主图：取灯箱原图 `static.skatepro.com/product/1800/…`，未取 logo、占位图或推荐图。
- `quality_exceptions`：9 条，均为正文完整但缺少可空字段（7 条无规格表、4 条无公开选项，部分重合）；`partial_description_products = 0`。

## 修复任务（增加 `docs/02` 可空字段 `availability`）

- 开始：03:19:45Z；复跑结束：03:27:16Z；`fix_minutes = 7.5`（其中复跑 6.7 分钟）。含输出校验与单测在 03:29 前完成。
- 改动文件：`skatepro_scraper/extract.py`（从 JSON-LD `offers.availability` 聚合 `Product`/`ProductGroup`/`hasVariant`，并用 PHP2JS `stock_level` 交叉计数）、`skatepro_scraper/runner.py`（`availability_summary` 写入任务结果与运行汇总）、`manifest.yaml`（`plan_version` → `2026.11.19-2`，补充提取与限制）。
- 复跑结果：30/30 有效，`availability_summary = {"in_stock": 30}`。
- 回归核对：v1 与 v2 的 30 条逐商品审计在 11 个共享字段（URL、名称、价格、币种、正文状态／长度、部分原因、分类、品牌、选项、缺失原因）上 **0 差异**；`valid.csv` 因不含该内部字段而内容不变。
- 未放宽字段要求、未删除失败样本。

## 错误记录

| 类别 | 内容 | 影响 |
| --- | --- | --- |
| 实现错误 | 首次启动前 `DEFAULT_MAX_CATEGORY_SEEDS` 未导入（NameError） | 未发出任何 HTTP 请求，导入后立即修复 |
| 标注错误 | `config.DEFAULT_PLAN_VERSION` 从一开始就写成了最终的 `2026.11.19-2`，导致 `smoke-001` 与 `run-001` 的运行汇总把 **v1 代码**记成 v2 | 只影响版本标签，不影响数据：`run-001` 的逐商品审计没有 `availability` 字段，可证明它跑的是 v1 代码；修复复跑用显式 `--plan-version 2026.11.19-2`。未改写已产出的日志 |
| 工具 | 计划 venv 未安装 PyYAML，无法用 YAML 解析器校验 manifest | 改用顶层键扫描校验必需字段；未安装新依赖 |
| 站点 | 无 429／403／5xx／挑战页 | — |

## 资源回收

无浏览器进程；每次运行使用一个 `FetcherSession`，退出时随上下文管理器关闭。没有遗留下载文件或临时目录（原始页面未保存）。

## 验收场景对照（A01～A07、A14）

| 场景 | 结论 | 证据 |
| --- | --- | --- |
| A01 正价／零价／无价 | 通过（逻辑）+ 单测 | 只接受有限正价；`zero_price`/`missing_price` 排除路径与单测；本批未出现零价样本，未伪造 |
| A02 变体最低价与选项 | 通过 | 取变体 `price_number` 最低正价；选项为公开维度／值；未枚举 SKU 组合 |
| A03 税价与市场 | 部分／有标注 | 静态 HTML 无含税／未税声明，`tax_basis = unknown_not_stated`；EUR 报价有同报价 JSON-LD 证据 |
| A04 完整正文与摘要 | 通过 | 正文 + 规格表合并；摘要回退只在 DOM 缺失时使用并标记 `fallback` |
| A05 复杂部分描述 | 通过（本批无触发） | 部分提取逻辑与 `partial_reason` 已实现；本批 30 条均为 complete，未把缺规格表硬判为部分 |
| A06 HTML 与裸文本 | 通过 | 正文 HTML 白名单清洗；CSV 统一输出 HTML |
| A07 主图／分类／品牌／单位 | 通过 | 原图优先、意义分类、无品牌留空；本批未出现销售单位场景 |
| A14 导出保真 | 通过 | 9 列、引号／逗号／换行／中文往返单测；`quality_exceptions` 9 条；公式保护只作用于文本列 |

## 未完成／限制

- 预算上限导致只覆盖入口主菜单的前 3 个分类前沿、30 个商品页；不是全站完成。
- 出口 IP 使站点提示“配送至美国”；报价仍为 EUR，JSON-LD 配送／退货地区为 ES，未设置国家 Cookie，未做汇率换算（记录为限制，不虚标市场）。
- `tax_basis` 只能标为未声明。
- `run-001` 的顶层 `valid.csv` 被 `fix-rerun` 覆盖（运行器只维护一份规范输出）；`run-001` 保留了逐商品审计与运行汇总，v1/v2 共享字段已核对 0 差异。`fix-rerun` 的 `valid.csv`、`task-result.json` 已在运行后从顶层输出原样归档到 `diagnostics/fix-rerun/`（内容未改）。
- 未做“干净环境导入”的第二台机器灰度；兼容字段与命令已写入 manifest，但未实测。
