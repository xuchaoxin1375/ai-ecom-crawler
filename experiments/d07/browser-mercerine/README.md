# 浏览器 adapter 证据：mercerine（2026-11-21）

## 目的

验证 `app` 运行时用真实浏览器完成一次有界商品采集，并验证任务级浏览器资源在正常结束和 worker 强杀后都能回收。选择 `mercerine.com` 的原因：

- 静态请求首页和商品页都返回 503，正文由站点自己的 JS 验证 / 重新导航后出现；静态 fetcher 拿不到商品数据。
- 浏览器渲染后首页有商品链接，商品页有 Product JSON-LD；可以同时验证渲染、会话复用和 D02 导出。
- 站点是公开法国面料店，只读公开页面，未登录、未下单。

## 环境与入口

- 客户端：`ecom_crawler` 运行时，Patchright 1.64.4 CDP，Patchright Chromium `Chrome/156.0.8078.4`，headless。
- 出口：本机直连。
- 规则：`rule.yaml`（`mercerine-browser@2026.11.21-1`）。
- 任务：`browser-mercerine-003`，product 任务，`max_products=3`，`max_seconds=300`，`per_domain_rps=1`。
- 请求：首页 1 次 + 商品页 3 次；商品页首轮响应 503，渲染后的 navigation `responseStatus` 为 200。

## 正常结果

| 项 | 结果 |
| --- | --- |
| 任务状态 | `FINISHED` / `COMPLETED` |
| 有效商品 | 3 / 3 |
| 排除 / 失败 | 0 / 0 |
| 墙钟 | 约 80–110 秒：`browser-mercerine-003` 80 秒（14:13:15–14:14:35），`browser-mercerine-004` 109 秒（14:28:44–14:30:33） |
| 浏览器会话 | 一个浏览器进程复用 4 个页面请求 |
| 导出 | 9 列 `products.csv`，另有 `task-result.json`、`records.jsonl` 和诊断目录 |
| 字段来源 | 名称、价格、币种、主图、描述、分类、品牌都命中 JSON-LD；`source_url` 命中 canonical |
| 描述状态 | JSON-LD 摘要，运行时记为 `fallback`，D02 导出映射为 `SUMMARY_FALLBACK` |

3 条商品：

| 名称 | 价格 | 币种 |
| --- | --- | --- |
| Tissu Fausse Fourrure Poils Longs Brun Caramel | 1.89 | EUR |
| Tissu jacquard stretch vieux rose à motifs en relief | 2.89 | EUR |
| Tissu French Terry Crêpe Rose Motif Léopard | 1.495 | EUR |

价格是站点 JSON-LD 给出的默认报价，未做单位价或面料长度换算；该证据只证明渲染和字段路径，不证明价格口径已审计。

## 强杀接管

脚本：`crash_test.py`，任务 `browser-crash-001`，`lease_ttl=10`。

```powershell
app\.venv\Scripts\python.exe experiments\d07\browser-mercerine\crash_test.py --lease-ttl 10 --timeout 240
```

关键结果：

| 阶段 | 观察 |
| --- | --- |
| worker 启动后 | 任务 `RUNNING`，浏览器 PID 和 profile 已登记 |
| 强杀 worker | worker 退出码 1；Chromium 仍在运行（PID 未被动到） |
| 租约过期后新 worker | `settle_expired_tasks` 回收 1 个过期任务，租约令牌递增到 2 |
| 接管后 | 遗留 Chromium 已终止，profile 已删除，`task_resources` 为 0 |
| 重跑 | 任务 `FINISHED` / `COMPLETED`，1 / 1 有效，使用新的浏览器 PID |

接管摘要在 `crash-summary.json`；原始任务产物在 `crash/tasks/browser-crash-001/`。运行期 `tasks.db` 和浏览器 profile 不入库。

## 复跑

```powershell
python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/browser-mercerine/rule.yaml `
  --db experiments/d07/browser-mercerine/tasks.db `
  --out-root experiments/d07/browser-mercerine/tasks `
  --task-id browser-mercerine-004 `
  --task-type product --max-products 3 --max-seconds 300 --max-attempts 2 --per-domain-rps 1
```

需要新任务 ID，避免覆盖已有诊断。浏览器规则依赖：

```powershell
python -m patchright install chromium
```

## 边界

- 3 个商品是首页链接的有界样本，不是全站覆盖；分类、分页和 sitemap 未枚举。
- headless 浏览器通过了该站的 JS 验证；这不等于所有挑战站都能无头通过，也不代表站点长期稳定。
- 浏览器 adapter v0 只渲染页面；不点击 load more、不滚动、不提交表单，不绕过登录、付费、验证码或年龄门。
- 浏览器任务逐条串行；单次导航受 `timeout_ms` 约束，暂停／取消在条目边界生效。
- 同一站点、同一出口和同一渲染策略下的结果只代表 2026-11-21 的快照。

## 文件

- `rule.yaml`：规则包。
- `crash_test.py`：强杀接管与资源回收演练脚本。
- `crash-summary.json`：接管摘要（路径已改为相对路径）。
- `tasks/browser-mercerine-002/`：1 商品首次成功。
- `tasks/browser-mercerine-003/`：3 商品会话复用证据（80 秒）。
- `tasks/browser-mercerine-004/`：最终代码复跑，3 商品、109 秒。
- `crash/tasks/browser-crash-001/`：强杀接管后的重跑证据。
- `tasks/browser-mercerine-001/`：首次导出失败样本。运行时接受商品，但 D02 桥接没有把 `fallback` 映射为 `SUMMARY_FALLBACK`，导出进入失败流；修复 `bridge.py` 后 002 通过。保留该样本用于回归和诊断。
