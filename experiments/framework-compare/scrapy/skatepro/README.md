# skatepro.es — Scrapy 2.20.0 采集方案

有界框架对比实验（S2，第 2 轮 9 列业务合同）的可复跑方案包。入口与契约见
`manifest.yaml`；本次实际执行记录见 `run-log.md`。

## 运行

在仓库根目录：

```powershell
python -m uv run --project experiments/framework-compare/scrapy `
  python experiments/framework-compare/scrapy/skatepro/run.py `
  --max-products 30 --max-seconds 600 `
  --build-started-at 2026-11-19T02:13:00Z
```

- 不调用任何 LLM；不使用浏览器；不登录。
- 并发 1、请求间隔 10s（站点 `Crawl-delay`），重试上限 3；429 按 `Retry-After` 退避。
- 只读公开入口：robots.txt、sitemap.xml、一个分类页、sitemap 顺序前 N 个商品页。

## 输出

| 文件 | 内容 |
| --- | --- |
| `valid.csv` | 9 列业务字段，UTF-8 BOM、CRLF |
| `task-result.json` | 09 契约的 state/outcome/stop_reason/counts/coverage/quality_exceptions |
| `diagnostics/` | 排除、失败、待处理、内部追溯、run-meta、events、scrapy.log |
| `results/scrapy-skatepro.json` / `.md` | 实验指标（`rebuild_metrics.py` 从输出汇总） |

## 停止与复跑

- 自然结束：30 个商品处理完；时间上限 `--max-seconds`（默认 600s）由
  `CLOSESPIDER_TIMEOUT` 兜底。
- 中断（Ctrl+C）时 pipeline 在关闭阶段写出已接纳结果与待处理清单；不会残留浏览器或子进程。
- 复跑直接重复上面的命令；同一 `(task_id, source_url)` 去重。
- 只想重建指标、不重新抓取：

```powershell
python -m uv run --project experiments/framework-compare/scrapy `
  python experiments/framework-compare/scrapy/skatepro/rebuild_metrics.py `
  --build-started-at 2026-11-19T02:13:00Z --plan-created-at 2026-11-19T02:40:00Z
```

## 维护要点

- 发现：sitemap 的 `loc` 必须匹配 `^https://www\.skatepro\.es/\d+-\d+\.htm$`；
  分类页 `?page=2` 不再是静态翻页，分页由 JS 组件完成。
- 商品页锚点：JSON-LD `Product` **或** `ProductGroup`；描述 `#product_description`；
  规格 `#product_specifications > .row`（两列）；变体与价格 `php2js.product[id].variants`。
- 价格口径：所有公开变体的最低正价（含缺货）；币种取同一报价对象的 ISO 代码，
  不接受仅有 `€` 符号。
- 正文状态：`complete` / `partial` / `fallback` / `not_provided` / `failed`；
  部分描述必须带原因并进入 `quality_exceptions`。
- 选项：只导出有 ≥2 个公开值的维度；单值维度是规格，不伪造为选项。
- 模板变化时：先看 `diagnostics/failed_products.csv` 与 `valid_internal.json`，
  修选择器后递增 `plan_version` 再复跑。

## 兼容性

- Scrapy 2.20.0、Python 3.11–3.13；依赖锁在 `../uv.lock`（实验目录共用环境）。
- Windows / Linux / WSL2；无 Cookie、无密钥、无私有接口。
- 运行前确认目标市场仍为 ES/es-ES/EUR，且 sitemap 与商品页结构未变。

## 测试

```powershell
python -m uv run --project experiments/framework-compare/scrapy `
  python -m unittest discover -s experiments/framework-compare/scrapy/skatepro/tests -v
```

测试只使用合成片段，不落盘整页原文。
