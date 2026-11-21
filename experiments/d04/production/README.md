# D04 生产执行器 v0（Familidoo）

## 目的与边界

验证 `app/` 的第一个真实执行入口：`ecom-crawler run` 读取 D03 的声明式方案，完成发现、静态获取、提取，写入 SQLite 任务账本，再用 D02 导出 9 列 CSV 和任务结果。

- 方案：`experiments/d03/familidoo/familidoo-d03.yaml`，6 个首页商品。
- 执行：`app/src/ecom_crawler/execution.py`；底层为从 R06 抽取的静态单进程运行时。
- 出口：直连；未使用代理。
- 范围：只验证首页 6 个商品，不是全站。

## 结果

| 项 | 值 |
| --- | --- |
| 任务 | `d04-prod-001` |
| 目标请求 | 7（1 入口 + 6 商品页） |
| 墙钟 | 7 秒 |
| 商品 | 6／6 有效 |
| 排除／失败 | 0／0 |
| 任务状态 | `FINISHED`／`COMPLETED` |
| app 导出 | 6 有效、0 失败、`COMPLETED` |
| CSV SHA-256 | `139051525696051d6f6864ef4242d0c0759b4fdee7cab91e50bb323d32bc64b8` |

该 CSV 与 D05 WSL2 复用的 `products.csv` **字节一致**；`records.jsonl` 只有 `extracted_at` 不同。SQLite 账本中 1 个 navigation、6 个 product，全部 `DONE`，任务 `FINISHED/COMPLETED`。

## 执行

```powershell
python -m uv run --project app ecom-crawler run `
  --rule experiments/d03/familidoo/familidoo-d03.yaml `
  --db experiments/d04/production/tasks.db `
  --out-root experiments/d04/production/tasks `
  --task-id d04-prod-001 --task-type product `
  --max-urls 10 --max-products 6 --max-seconds 180 `
  --max-attempts 1 --per-domain-rps 1
```

产物：

- `tasks/d04-prod-001/task-result.json`：运行时任务结果。
- `tasks/d04-prod-001/products.jsonl`：提取后的商品记录。
- `tasks/d04-prod-001/app-run/`：转换后的 D02 输入。
- `tasks/d04-prod-001/export/`：9 列 CSV、任务结果、内部记录和诊断。
- `tasks.db`：任务账本。

## 实现边界

- `app/src/ecom_crawler/runtime/` 和 `executor/` 是从 `experiments/r06` 抽取的静态单进程实现；不是最终生产架构。
- 支持 R06 已有的发现来源（entry_links、sitemap、listing、html_index、public_json）和静态提取，但 `run` CLI 每次只跑一个任务，未暴露暂停／取消命令。
- 没有浏览器、跨进程租约、浏览器／进程资源回收、自动漂移修复；这些仍在 D07 缺口清单中。
- `bridge.py` 只把运行时已接受商品映射到 D02；不重新抓取或重新提取。
- 不保存整页原文、Cookie 或浏览器 profile。

## 验收映射

| 项 | 状态 | 证据 |
| --- | --- | --- |
| D04 无运行期 LLM 的实际采集入口 | 通过（v0） | `ecom-crawler run`，6／6，运行期 LLM 0 |
| D04 有效结果文件 | 通过 | `export/products.csv`、`task-result.json` |
| D04 错误／停止报告 | 通过（正常结束） | `task-result.json` 的 `stop_reason=NATURAL_END` |
| A09 无 AI 执行／复跑 | 原型层面通过 | D03／D04／D05 同一方案复跑；CSV 一致 |
| 生产执行器最终形态 | 未完成 | 仍是抽取的 R06 运行时；跨进程、浏览器和 app 原生状态模型待补 |
| 全站覆盖 | 未测 | 只取首页 6 商品，`coverage=PARTIAL` |
