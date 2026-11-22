# 同条件运行对照：skatepro.es（2026-11-22）

这是 `docs/13` 的补充实验，不是新的 AI 构建轮次。目的：在**同一站点、同一 URL 样本、同一预算、同一网络**下比较 Crawlee 和 Scrapy 的运行时表现，补上此前“两站三臂跨时间窗”缺少的严格同窗运行时对照。

## 固定条件

| 项 | 取值 |
| --- | --- |
| 站点 | `https://www.skatepro.es` |
| 样本 | sitemap 中 6660 个商品 URL 的 10 个均匀间隔 URL，见 `shared-urls.json` |
| 预算 | 10 个商品页 / 300 秒，先到为准 |
| 发现 | 两臂都读 robots.txt 和 sitemap.xml；Scrapy 另读一个分类页作为导航证据 |
| 网络 | 同机直连；两臂顺序执行，窗口记录在 `comparison.md` |
| 运行期模型 | 0；字段规则为确定性 Python |
| 框架 | Crawlee for Python 1.11.2（Playwright Chromium）；Scrapy 2.20.0（静态 HTTP） |

## 结果

| 指标 | Crawlee | Scrapy |
| --- | --- | --- |
| 请求数 | 11 | 13 |
| 墙钟 | 104.0s | 123.0s |
| 选中 / 处理 / 有效 | 10 / 10 / 10 | 10 / 10 / 10 |
| 失败 / 排除 / 待处理 | 0 / 0 / 0 | 0 / 0 / 0 |
| 成功率 | 100% | 100% |
| 部分描述 | 0 | 1 |
| 结果 / 停止 | COMPLETED / BUDGET_EXHAUSTED | COMPLETED / NATURAL_END |

请求数口径：Crawlee 的 11 是 sitemap + 10 个商品，robots 另记为 `robots_txt_fetch=1`；Scrapy 的 13 含 robots + sitemap + 分类探针 + 10 个商品。

完整表、质量异常和样本校验见 [`comparison.md`](comparison.md)；机器可读结果见 [`comparison.json`](comparison.json)。

## 复跑

```bash
python -X utf8 experiments/framework-compare/same-window-2026-11-22/run_comparison.py
python -X utf8 experiments/framework-compare/same-window-2026-11-22/summarize.py
```

`run_comparison.py` 顺序执行两臂，日志写入 `crawlee-run.log`／`scrapy-run.log`，时间写入 `timing.json`。`summarize.py` 从两臂的 `task-result.json`、`run-meta.json` 和指标文件重新生成 `comparison.json`／`comparison.md`，并校验两臂选中的 URL 集合一致。

单独复跑一臂：

```bash
python -m uv run --project experiments/framework-compare/crawlee python -X utf8 \
  experiments/framework-compare/crawlee/skatepro/run.py \
  --run-id same-window-002 --max-products 10 --time-budget-seconds 300 \
  --urls-file experiments/framework-compare/same-window-2026-11-22/shared-urls.json \
  --output-dir experiments/framework-compare/same-window-2026-11-22/crawlee

python -m uv run --project experiments/framework-compare/scrapy python -X utf8 \
  experiments/framework-compare/scrapy/skatepro/run.py \
  --max-products 10 --max-seconds 300 \
  --urls-file experiments/framework-compare/same-window-2026-11-22/shared-urls.json \
  --output-dir experiments/framework-compare/same-window-2026-11-22/scrapy \
  --results-dir experiments/framework-compare/same-window-2026-11-22/scrapy/results \
  --task-id same-window-scrapy-003
```

## 实验控制改动

两臂都新增了可选 `--urls-file`：

- Crawlee 在 `crawlee_skatepro/runner.py` 中加载共享 URL 列表；有该文件时使用列表，不再按自己的 systematic sample 选样；
- Scrapy 在 `scrapy/skatepro/run.py` 和 `skatepro/spiders/products.py` 中加载共享 URL 列表；有该文件时使用列表，不再取 sitemap 前 N 个；
- 两臂仍读 sitemap 作为分母和发现证据，并校验共享 URL 属于该 sitemap；
- 这个参数只用于实验对照，不改变生产方案的默认选样。

Scrapy 的任务计数也在 attempt-002 修正：`product_candidates` 和 `pending_products` 现在按**选中样本**（10）计，不再把 sitemap 的 6660 个商品全部算成候选；`sitemap_products` 和 `coverage.denominator` 仍保留 6660 作为覆盖边界。attempt-001 的原始输出保留在 `scrapy-attempt-001/`，不删除也不改写。

## 边界

- 只有一站、10 个商品、每臂一次；差异是描述性的，不是统计显著或框架排名。
- Crawlee 用浏览器，Scrapy 用静态 HTTP；这是两套现有方案的引擎差异，不另加控制变量。
- 10 个商品 / 300 秒比此前第 1、2 轮的 30 个商品 / 600 秒小，不能与构建轮次表直接合并。
- 只证明公开商品页的运行时表现，不证明全站覆盖、长期稳定性或真实虚拟列表；真实虚拟列表仍未找到。
- `scrapy-attempt-001/` 是计数语义修正前的迭代证据；最终结果以根目录 `scrapy/` 和 `comparison.*` 为准。
