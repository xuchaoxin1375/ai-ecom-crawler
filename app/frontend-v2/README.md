# 前端 v2 试点（桌面端）

本目录是 v2 前端的单页试点：React 19 + TypeScript + Vite + Tailwind CSS v4，先覆盖应用外壳和批次列表，用真实 API 验证设计方向。它不是当前生产入口，FastAPI 尚未挂载它；现有 Vue 应用仍在 `/batch/` 正常运行。

## 范围

- 桌面端：1280 主规格、1440 检查宽屏；768／390／320、移动抽屉和触屏适配后置。
- 已实现：应用外壳、服务状态、批次列表、筛选、指标条、状态徽标、站点就绪分段条、空／加载／错误状态。
- 未实现：批次详情、新建批次、站点详情、任务列表／详情、SSE、导出、构建面板；这些操作当前跳转旧版 `/batch/`。
- 链接策略：批次行和“新建批次”指向旧版路由，作为过渡期并行入口；功能对等后再替换。

## 启动

```powershell
cd app/frontend-v2
npm install
npm run dev
```

前端地址是 `http://127.0.0.1:5175/next/#/batches`。Vite 把 `/api`、`/batch` 和 `/legacy` 代理到 `http://127.0.0.1:8775`，需要另开一个 shell 启动本地服务：

```powershell
app\.venv\Scripts\python.exe -m ecom_crawler serve `
  --db /path/to/tasks.db --out-root /path/to/tasks `
  --rules-dir /path/to/rules --host 127.0.0.1 --port 8775
```

如果服务端口不同，修改 `vite.config.ts` 的代理目标。

## 校验

```powershell
cd app/frontend-v2
npm run lint
npm run typecheck
npm test
npm run build
npm run format:check
```

## 验证记录（2026-11-23）

- `lint`、`typecheck`、`test`（2 个用例）、`build`、`format:check` 通过；首屏 JS 约 128 KB gzip。
- 本地临时账本 10 个批次（合成站点列表，仅用于布局和状态走查，未入库）：1280／1440 无页面级横向溢出；筛选“草稿”后 4 行，搜索“德国”后 1 行；筛选写入 URL。
- 加载骨架、空态、读取失败、重试、刷新和“包含归档”状态已走查；错误态不再显示“还没有批次”。
- axe（WCAG 2.0／2.1／2.2 A／AA）0 violations、0 incomplete；控制台和页面错误 0。
- 批次行“查看”和“新建批次”通过 Vite 代理进入旧版 `/batch/` 对应路由；桌面端表头在页面滚动时吸附。
- 未执行：批次详情、新建、站点、任务、SSE、导出和构建面板的功能对等；真实批次 `b-586052683409` 对照；项目方视觉评审；768／390／320、移动抽屉、触屏、跨浏览器和读屏；FastAPI 挂载 `/next/` 和生产切换。

截图和临时账本按根目录 `AGENTS.md` 放在仓库外，不提交。

## 设计依据

- [前端设计系统与 v2 视觉方向](../../docs/35-前端设计系统与视觉方向.md)
- [ADR 0012：前端 v2 技术栈与设计系统](../../docs/adr/0012-前端v2技术栈与设计系统.md)

## 边界

- 这是 Proposed 方向的试点，不是生产验收；桌面端 1280／1440 通过后再扩到功能对等。
- 截图、运行期数据库和其他运行产物不提交到仓库；按根目录 `AGENTS.md` 和 `experiments/README.md` 的约定放到仓库外证据库。
- 现有 Vue 应用只修阻断缺陷，不在迁移期继续做视觉打磨。
