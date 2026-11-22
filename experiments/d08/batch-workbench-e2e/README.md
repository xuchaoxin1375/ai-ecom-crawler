# 批次工作台与任务控制台真实验收（2026-11-23）

## 目的与边界

本目录记录批次工作台阶段 1 与任务控制台并入 Vue 外壳后的真实验收证据。批次、任务和商品数据来自本地服务与真实站点，不使用 mock 数据；静态原型只作设计评审，不作为功能验收。

覆盖范围：

- 批次列表、批次详情、站点详情、新建批次导入预览；
- 任务列表、任务详情、筛选、归档／还原、导出入口；
- 批次站点详情到新任务详情 `/tasks/{task_id}` 的深链；
- 1280／1440／768／390 的外壳、侧栏、抽屉和主内容布局。

## 真实数据

- 批次：`b-586052683409`，`FINISHED`，2 个可采站点、2 个重复、1 个无效。
- 任务：`web-81551cae12c6`（familidoo，有效 6、失败 0）和 `web-7767a77021ea`（decohappy，有效 8、失败 0）。
- 批次汇总有效商品 14、失败商品 0；decohappy 有 8 条质量异常（描述部分），familidoo 0 条。
- 批次导出包含 `batch.json`、`sites.csv` 和两个站点的 `products.csv`／`task-result.json`。

## 截图索引

长页不以单张 full-page 作为详细验收证据；`*-full-index.png` 只作结构索引，细节看同目录的分段视口图。每张分段图约一个视口高度。

### 外壳与批次

| 文件 | 区域 | 看什么 |
| --- | --- | --- |
| `screens-shell/shell-batches-1280.png` | 1280 首屏，侧栏展开 | 当前项、品牌、面包屑、服务状态、批次列表 |
| `screens-shell/shell-batches-1440.png` | 1440 首屏 | 宽屏结构和卡片密度 |
| `screens-shell/shell-batches-768.png`、`shell-batches-390.png` | 768／390 批次列表（抽屉外） | 筛选、卡片和列表收纳 |
| `screens-shell/shell-rail-1280.png` | 1280 侧栏 Rail | 收起态只保留一条组间分隔线，图标和当前项可辨 |
| `screens-shell/shell-peek-1280.png` | 1280 Rail 悬停 | 面板浮层展开，主内容 left/width 不位移 |
| `screens-shell/shell-batch-1280.png` | 批次详情 | 卡片、站点表、状态与操作 |
| `screens-shell/shell-site-1280.png` | 站点详情 | 真实商品、质量异常、任务控制 |
| `screens-shell/shell-new-preview-1280.png` | 新建批次预览 | 无效／重复逐条原因、待接入提示、保存／启动 |
| `screens-shell/shell-drawer-768.png` | 768 抽屉 | 导航、遮罩、关闭入口 |
| `screens-shell/shell-drawer-390.png` | 390 抽屉 | 窄屏导航和顶部状态 |

### 任务控制台

| 文件 | 区域 | 看什么 |
| --- | --- | --- |
| `screens-tasks/tasks-1280.png` | 任务列表首屏 | 服务／worker、折叠的创建任务、筛选、计数、质量与操作 |
| `screens-tasks/tasks-768.png` | 768 任务列表 | 窄屏表格收纳和操作入口 |
| `screens-tasks/tasks-390.png` | 390 任务列表 | 窄屏布局；表格可左右滚动提示 |
| `screens-tasks/task-detail-1280-01-overview.png` | 任务详情首屏 | 状态、计数、覆盖、任务信息 |
| `screens-tasks/task-detail-1280-02-quality.png` | 质量段 | 质量异常说明与空状态 |
| `screens-tasks/task-detail-1280-03-items.png` | 明细段 | 商品 URL、名称、价格、状态、尝试与失败 |
| `screens-tasks/task-detail-8quality-1280-01-overview.png` | 8 条质量异常任务首屏 | 质量计数与任务信息 |
| `screens-tasks/task-detail-8quality-1280-02-quality.png` | 质量第 1 段 | 来源可点击、描述状态、缺失字段 |
| `screens-tasks/task-detail-8quality-1280-03-quality-more.png` | 质量第 2 段 | 质量列表承接和明细入口 |
| `screens-tasks/task-detail-8quality-1280-04-items.png` | 明细段 | 8 条商品与描述状态 |

`task-detail-1280-full-index.png`、`task-detail-8quality-1280-full-index.png`、`task-detail-768-full-index.png` 和 `task-detail-390-full-index.png` 仅作整页结构索引；判断文字、边界或操作时不看缩小后的长图。

## 验证结果

- 后端 193 个测试通过；Web API 14 个测试通过；ruff 通过。
- 前端 Vitest 2 个用例通过；`npm run build`（vue-tsc + Vite）通过。
- 1280／1440／768／390 的 document `scrollWidth` 等于 viewport 宽；控制台错误 0。
- 1280 侧栏展开 264、Rail 56、peek 面板 264 但槽位 56、主内容 left 56；Esc 关闭 peek 并回到 `main`。
- 768／390 抽屉可开、Esc 可关；任务详情无横向溢出。
- 任务筛选、归档／还原、批次站点到 `/tasks/{task_id}` 深链和任务明细分页已实际走查。

## 复跑入口

```powershell
cd app/frontend
npm install
npm run build
npm test

# 另开 shell，用已有账本和规则目录启动
app\.venv\Scripts\python.exe -m ecom_crawler serve `
  --db /path/to/tasks.db --out-root /path/to/tasks `
  --rules-dir /path/to/rules --host 127.0.0.1 --port 8791
```

浏览器打开 `http://127.0.0.1:8791/batch/#/batches`；任务控制台在 `http://127.0.0.1:8791/batch/#/tasks`。旧 `/` 控制台保留为技术兜底，不在主导航中。

## 限制

- 单次运行、两个站点，不等于全站或长期稳定性结论。
- 截图由 Chromium 无头采集；没有 NVDA／VoiceOver、Safari／Firefox 或深色主题证据。
- 768／390 以布局和溢出为主，详细视觉验收以 1280 分段图为主。
- 任务控制台并入 Vue 外壳已由 [ADR 0010](../../../docs/adr/0010-任务控制台并入批次工作台外壳.md) 收口；当前文档以 `docs/15`、`docs/21`、`docs/26` 和 `docs/33` 为准。
