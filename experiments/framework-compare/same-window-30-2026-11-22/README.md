# 同条件运行对照：skatepro.es（30 商品／600 秒，2026-11-22）

这是 `docs/13` 的补充实验，不是新的 AI 构建轮次。目的：在**同一站点、同一 30 个 URL、同一 30 商品／600 秒预算、同一网络**下比较 Crawlee 和 Scrapy 的运行时表现。

## 固定条件

| 项 | 取值 |
| --- | --- |
| 站点 | `https://www.skatepro.es` |
| 样本 | sitemap 中 6660 个商品 URL 的 30 个均匀间隔 URL，见 `shared-urls.json` |
| 预算 | 30 个商品页／600 秒，先到为准 |
| 发现 | 两臂都读 robots.txt 和 sitemap.xml；Scrapy 另读一个分类页作为导航证据 |
| 网络 | 同机直连；两臂顺序执行，窗口记录在 `comparison.md` |
| 运行期模型 | 0；字段规则为确定性 Python |
| 框架 | Crawlee for Python 1.11.2（Playwright Chromium）；Scrapy 2.20.0（静态 HTTP） |

## 结果

| 指标 | Crawlee | Scrapy |
| --- | --- | --- |
| 请求数 | 31 | 33 |
| 墙钟 | 304.0s | 323.0s |
| 选中／处理／有效 | 30／30／29 | 30／30／29 |
| 失败／排除／待处理 | 0／1／0 | 0／1／0 |
| 成功率 | 97% | 97% |
| 部分描述 | 0 | 5 |
| 结果／停止 | COMPLETED／BUDGET_EXHAUSTED | COMPLETED／NATURAL_END |

两臂选中 URL 集合一致，且排除同一商品 `https://www.skatepro.es/250-21059.htm`，但原因不同：

- Crawlee：`NO_PRICE`，1 个变体无有限正价。
- Scrapy：`currency_unproven`，展示报价未绑定 ISO 4217 币种。
- 页面可见 `17,95 €`；这是需要后续判定的跨臂分歧，不当作两次成功。

完整表、质量异常和样本校验见 [`comparison.md`](comparison.md)；机器可读结果见 [`comparison.json`](comparison.json)。

## 构建耗时

本实验只运行现有方案，**未测 AI 构建耗时**。历史构建值（不同时间窗，不可直接比较）：Crawlee `skatepro` 首个方案 841.0s、首个有效 1104.0s；Scrapy 1229.0s、1513.0s。来源为 `../results/crawlee-skatepro.json` 与 `../results/scrapy-skatepro.json`。严格同窗的构建会话对照仍未做。

## 复跑

```bash
python -X utf8 experiments/framework-compare/same-window-30-2026-11-22/run_comparison.py
python -X utf8 experiments/framework-compare/same-window-30-2026-11-22/summarize.py
```

`run_comparison.py` 顺序执行两臂，日志写入 `crawlee-run.log`／`scrapy-run.log`，时间写入 `timing.json`。`summarize.py` 从两臂的 `task-result.json`、`run-meta.json` 和指标文件重新生成 `comparison.json`／`comparison.md`，并校验两臂选中的 URL 集合一致。

单独复跑一臂：

```bash
python -m uv run --project experiments/framework-compare/crawlee python -X utf8 \
  experiments/framework-compare/crawlee/skatepro/run.py \
  --run-id same-window-30-002 --max-products 30 --time-budget-seconds 600 \
  --urls-file experiments/framework-compare/same-window-30-2026-11-22/shared-urls.json \
  --output-dir experiments/framework-compare/same-window-30-2026-11-22/crawlee

python -m uv run --project experiments/framework-compare/scrapy python -X utf8 \
  experiments/framework-compare/scrapy/skatepro/run.py \
  --max-products 30 --max-seconds 600 \
  --urls-file experiments/framework-compare/same-window-30-2026-11-22/shared-urls.json \
  --output-dir experiments/framework-compare/same-window-30-2026-11-22/scrapy \
  --results-dir experiments/framework-compare/same-window-30-2026-11-22/scrapy/results \
  --task-id same-window-30-scrapy-002
```

## 实验控制改动

两臂都新增了可选 `--urls-file`：

- Crawlee 在 `crawlee_skatepro/runner.py` 中加载共享 URL 列表；有该文件时使用列表，不再按自己的 systematic sample 选样；
- Scrapy 在 `scrapy/skatepro/run.py` 和 `skatepro/spiders/products.py` 中加载共享 URL 列表；有该文件时使用列表，不再取 sitemap 前 N 个；
- 两臂仍读 sitemap 作为分母和发现证据，并校验共享 URL 属于该 sitemap；
- 这个参数只用于实验对照，不改变生产方案的默认选样。

Scrapy 的任务计数已改为按**选中样本**计，`product_candidates` 和 `pending_products` 不再把 sitemap 的 6660 个商品全部算成候选；`sitemap_products` 和 `coverage.denominator` 仍保留 6660 作为覆盖边界。

## 边界

- 只有一站、30 个商品、每臂一次；差异是描述性的，不是统计显著或框架排名。
- Crawlee 用浏览器，Scrapy 用静态 HTTP；这是两套现有方案的引擎差异，不另加控制变量。
- 30 商品／600 秒是完整运行预算，但仍是单站单次；不能与之前的 10 商品／300 秒冒烟或构建轮次表直接合并。
- 只证明公开商品页的运行时表现，不证明全站覆盖、长期稳定性或真实虚拟列表。
- 两臂排除同一商品但原因不同，说明字段规则仍有需要核对的边界；本实验只记录，不修实现。
