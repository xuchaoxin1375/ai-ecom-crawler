# skatepro.es — Crawlee for Python 方案包

Crawlee for Python 1.11.2 的 skatepro.es 采集方案，属 `docs/13` 框架对比实验第 2 轮（docs/02 的 9 列业务 CSV）。方案成熟度 `candidate`，未做业务验收。

## 入口

```powershell
# 仓库根目录执行；uv 不在 PATH，用 python -m uv
python -m uv run --project experiments/framework-compare/crawlee python -X utf8 `
  experiments/framework-compare/crawlee/skatepro/run.py --run-id run-002
```

`manifest.yaml` 是方案入口，执行端先读它再加载 `run.py`。参数：

- `--run-id`：诊断目录名，默认 `run-001`。
- `--max-products`：默认 30，超过 30 被截断。
- `--time-budget-seconds`：默认 600，超过 600 被截断。
- `--build-started-at` / `--plan-ready-at`：构建时间戳，用于 `first_plan_s`、`first_valid_product_s`。
- `--implementation-revisions`：写入 run-meta 的修订次数。
- `--resume`：重放 `diagnostics/<run-id>/checkpoint.jsonl` 并跳过已处理商品；暂停/恢复正常运行未实现。
- `--headful`：有头浏览器，排查用。

## 关键约束（与 manifest 一致）

- 发现：`robots.txt` 声明的 `sitemap.xml`，按 `^https://www.skatepro.es/\d+-\d+\.htm$` 判定商品页，按均匀间隔抽 30 个；不遍历分类、不翻页。
- robots：Crawlee `respect_robots_txt_file=True`；`*/catalog`、`*/wishlist`、`/adminshop`、`/static` 一律不入队。
- 速率：并发 1，顶层请求间隔 10s（站点 `Crawl-delay: 10`），重试上限 2 次（共 3 次尝试），429 交给 `ThrottlingRequestManager` 退避，滞留超过 190s 以 `ACCESS_DENIED` 停止。
- 浏览器：Playwright Chromium，headless；图片、字体、样式、脚本在导航前中止（数据在服务端渲染）。
- 运行期不调用任何 LLM。

## 输出

| 路径 | 内容 |
| --- | --- |
| `valid.csv` | 9 列业务 CSV：`name, price_amount, price_currency, primary_image_url, description_html, category, brand, attributes, source_url` |
| `task-result.json` | `state/outcome/stop_reason/counts/coverage/business_acceptance`，正文异常或字段缺失时含 `quality_exceptions` |
| `diagnostics/<run-id>/` | `run.log`、`requests.jsonl`、`products.jsonl`（含内部字段与证据）、`checkpoint.jsonl`、`excluded/failed/pending.jsonl`、`run-meta.json`、`selected_urls.json`、`sitemap-summary.json` |
| `diagnostics/run-001/` | 首次有界试跑的归档导出（v1，plan_version 2026.11.19-1） |
| `diagnostics/fix-rerun/` | 修复任务复跑诊断（v2） |
| `diagnostics/smoke-2products/`、`smoke-3products/` | 两次小样冒烟，含首次导航超时证据 |
| `diagnostics/build-timeline.json` | 构建起点、方案就绪时间、修订记录与修复任务计时 |
| `diagnostics/storage-residue.json` | Crawlee 节流管理器在仓库根写出的 `storage/` 残留清单（已删除） |
| `../../results/crawlee-skatepro.json` / `.md` | 实验指标 |

内部记录（`products.jsonl`、checkpoint）保留 `description_format`、`description_status`、`partial_reason`、`missing_reasons`、`market`、`locale`、`availability`、`availability_source`、`tax_basis`、`tax_basis_note`、`variant_count` 等追溯字段，不进入 9 列 CSV。

## 维护

- 校验导出：`python -m uv run --project .. python -X utf8 tools/validate_output.py --valid-csv valid.csv --task-result task-result.json --diagnostics diagnostics/fix-rerun`
- 契约测试（20 个，纯合成样本，不联网）：`python -m uv run --project .. python -X utf8 -m unittest discover -s tests`
- 指标重建：`python -m uv run --project .. python -X utf8 tools/make_metrics.py`
- 模板变化：`#product_description`、`#product_specifications`、`#model_specifications`、`.product_prices .pi_price .price`、`jsonld ProductGroup.hasVariant[].offers` 是主要锚点；改版时先改 `extract.py`，递增 `plan_version`，再跑 2 个商品的小样复验。
