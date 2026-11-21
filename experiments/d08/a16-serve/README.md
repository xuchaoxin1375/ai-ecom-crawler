# A16 真实站点闭环（serve + 托管 worker）

## 目的与边界

用 `familidoo.fr` 的 D03 规则包，通过 `ecom-crawler serve` 的 Web API 和托管 worker 跑一次真实任务，验证 A16 的创建、执行、暂停／恢复、归档／还原、导出和页面关闭后继续执行。只覆盖一个简单 PrestaShop 站点、入口页 6 个商品；不是全站、跨平台或长期稳定性结论。

日期：2026-11-21。分支：`exp/framework-compare`。出口：本机直连。

## 环境与命令

```powershell
app/.venv/Scripts/python.exe -m ecom_crawler serve `
  --db /path/to/tasks.db `
  --out-root /path/to/tasks `
  --rules-dir experiments/d03/familidoo `
  --port 8769 `
  --per-domain-rps 0.4
```

`serve` 默认启动托管 worker，并持有 `<db>.worker.lock`。API 流程：

- `GET /api/rules` 选择 `familidoo-fr-d03@2026.11.21-1`。
- `POST /api/tasks` 创建 `DRAFT`，预算 `max_products=6`、`max_urls=20`、`max_seconds=180`。
- `POST /api/tasks/{id}/start` 进入 `QUEUED`。
- 运行中 `POST /pause`，在途商品结清后 `PAUSED`；`POST /resume` 后继续。
- `POST /archive` / `restore` 只改可见性；`GET /export` 下载 zip。

可复跑脚本：`run_a16.py`（固定端口 8769，按当前规则目录解析规则）。

## 结果

任务 `web-ce6f2cc5a950`：

- 时间线：`QUEUED` 0.03s → `RUNNING` 0.54s → 暂停请求 1.88s → `PAUSING` 2.17s → `PAUSED` 3.71s → 恢复 5.0s → `FINISHED` 17.49s。
- 计数：`navigation_urls=1`、`discovered_urls=7`、`product_candidates=6`、`processed_products=6`、`valid_products=6`、`excluded_products=0`、`failed_products=0`。
- `quality_exceptions=6`，均为品牌未提供（`brand: NOT_PROVIDED`）。
- 归档：默认列表不包含；`include_archived=true` 包含；还原后回到默认列表。
- 导出 zip：`products.csv`、`task-result.json`；`products.csv` 6 行数据。
- UI：`ui-list.png` 显示创建表单、筛选和任务行；`ui-detail.png` 显示计数、质量异常、items 和归档按钮。

取消：第三个任务 `web-86a325478932` 在 `RUNNING` 时请求取消，最终 `CANCELLED`／`USER_CANCELLED`；`valid_products=0`、`failed_products=1`、`pending_products=5`，在途结果被拒收，证据见 `cancel-evidence.json`。

页面关闭后继续执行：第二个任务 `web-07ef0932ba3b` 在 `RUNNING` 时把页面导航到 `about:blank`；之后任务仍完成，6／6 有效，证据见 `close-evidence.json`。该文件只保留了关闭页面后的最终采样，没有逐秒记录关闭瞬间。

## 文件

- `evidence.json`：规则、时间线、最终计数、归档结果、items 总数和导出文件清单。
- `cancel-evidence.json`：真实站点取消和迟到结果拒收。
- `close-evidence.json`：页面关闭后继续执行的任务。
- `task-result.json`、`products.csv`、`products.jsonl`：6 个商品的导出与内部记录。
- `ui-list.png`、`ui-detail.png`：1505×867 的真实页面截图。
- `run_a16.py`、`run_cancel.py`：API 驱动脚本。

## 限制

- 单站、入口页 6 个商品；不是全站覆盖。
- 没有浏览器渲染或挑战页路径；静态 HTML 直连。
- 页面关闭证据只有最终采样，未记录关闭后的每秒状态。
- UI 截图是技术验收证据，不是完整视觉回归或移动端验收。
- 站点结构变化会使规则失效；本证据只代表 2026-11-21 的响应。
