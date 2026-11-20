# D04 Familidoo 同方案独立复跑

## 目的与边界

用 D03 保存的同一方案、同一范围和同一市场，新建 `d04-product-rerun-001` 任务，在独立的任务数据库和输出目录中再跑一次。目的是验证关闭构建会话后仍能执行、复跑结果是否一致，以及普通批次没有逐页 LLM 调用。

- 方案：`experiments/d03/familidoo/familidoo-d03.yaml`，`familidoo-fr-d03`／`2026.11.21-1`。
- 范围：`familidoo.fr` 首页 6 个商品，FR／fr-FR／EUR。
- 执行：R06 任务运行时原型；不是 D04 的生产执行器。
- 出口：直连；未使用代理。

## 结果

| 项 | D03 构建 | D04 复跑 |
| --- | --- | --- |
| 任务 | `d03-product` | `d04-product-rerun-001` |
| 目标请求 | 8（2 入口 + 6 商品） | **7**（1 入口 + 6 商品） |
| 墙钟 | 9s | 7s |
| 商品 | 6／6 有效 | 6／6 有效 |
| 排除／失败 | 0／0 | 0／0 |
| 结果 | `COMPLETED`／`NATURAL_END` | `COMPLETED`／`NATURAL_END` |
| 运行期 LLM | 0 | 0 |

两次运行的产品集合、顺序和字段值一致；`tasks/d04-product-rerun-001/products.jsonl` 与 D03 的 `products.jsonl` SHA-256 相同：

```text
38781991A452CB4860540DCE5E27D0EE3FDE4D207C1C34190FC2DDA6222FD4F8
```

`app` 导出的 `products.csv` 也字节一致：

```text
3D637EBE9AA131B65CB60195BECA928A11E2853435E51CA717BF1D7FA7EB28FB
```

`records.jsonl` 只有 `extracted_at` 不同（取自各任务 `finished_at`），其余字段一致；`task-result.json` 的计数、`quality_exceptions` 和 `outcome` 相同。

## 执行

```powershell
$db = 'experiments/d04/familidoo/tasks.db'
$out = 'experiments/d04/familidoo/tasks'
$rule = 'experiments/d03/familidoo/familidoo-d03.yaml'
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py task create `
  --db $db --rule $rule --task-type product --task-id d04-product-rerun-001 `
  --out-root $out --max-urls 10 --max-products 6 --max-seconds 180 --start
python -m uv run --project experiments/framework-compare/scrapling `
  --with "pyyaml==6.0.3" `
  python experiments/r06/runtime_cli.py worker run `
  --db $db --out-root $out --max-tasks 1 --per-domain-rps 1
```

接入 app：

```powershell
python experiments/d03/familidoo/to_app_run.py `
  --task-result experiments/d04/familidoo/tasks/d04-product-rerun-001/task-result.json `
  --products experiments/d04/familidoo/tasks/d04-product-rerun-001/products.jsonl `
  --out-dir experiments/d04/familidoo/app-run
python -m uv run --project app ecom-crawler export `
  --run-dir experiments/d04/familidoo/app-run `
  --out-dir experiments/d04/familidoo/export
python -m uv run --project app ecom-crawler validate `
  --run-dir experiments/d04/familidoo/export
python experiments/r06/tools/validate_runtime.py --root experiments/d04/familidoo
```

## 验收映射

| 项 | 状态 | 证据 |
| --- | --- | --- |
| A09 无 AI 执行／复跑 | 原型层面通过 | 独立任务、无逐页 LLM、`runtime.llm_calls=0`、结果字节一致 |
| D04 独立执行入口 | 原型层面通过 | R06 CLI 在新建任务上读取同一方案并完成 6／6 |
| D04 生产执行器 | 未完成 | 仍是 R06 原型；生产 `app` 执行入口、任务账本和资源回收未实现 |
| A08 未知站点自主构建 | 未测 | 本次仍是已知站点复跑 |
| 全站覆盖 | 未测 | 只覆盖首页当前 6 商品 |

## 限制

- 两次运行相隔约 11 分钟，站点内容和首页商品顺序未变化；不能据此宣称长期稳定或能处理漂移。
- 结果字节一致只说明这个有界样本、这个方案版本和这个环境下可复现；不是全站或跨环境结论。
- 执行端仍是 R06 原型，不是 D04 的生产执行器；D04 的完整交付还要生产入口、SQLite 任务账本、资源回收和跨进程语义。
- 未验证浏览器、动态渲染、暂停／恢复、跨设备或代理路径。
- 不保存整页原文、Cookie 或浏览器 profile；只保留任务事件、规范化商品记录和导出结果。
