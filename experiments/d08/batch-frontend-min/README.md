# 批次工作台最小端到端路径（2026-11-23）

## 目的与边界

验证 ADR 0009 选定的 Vue 3 + TypeScript + Vite 能够接入现有 FastAPI 服务：构建、`/batch/` 静态托管、真实 `/api/health`／`/api/tasks`、hash 路由和 Vitest。当前页面只是技术最小路径，不是最终批次工作台；批次／站点对象、导入匹配和批次详情尚未实现。

## 证据

- `app/frontend/`：Vue 源码、Vite 配置、组件测试和 `package-lock.json`。
- `batch-minimal-path.png`：1280×900 真实服务状态和任务列表。
- `evidence.json`：健康状态、真实任务行、`/batch/` 托管、hash 路由和控制台错误检查。
- 构建：`npm run build` 通过；组件测试：`npm test` 通过（1 个用例）。
- 外部依赖警告：本机 Node 24.14.1 对 `nopt@10`／`abbrev@5` 提示 EBADENGINE（要求 24.15+），构建和测试仍通过；打包前建议升级 Node。

## 复跑

```powershell
cd app/frontend
npm install
npm run build
npm test

# 另开一个 shell，用已有账本启动 no-worker 服务
app\.venv\Scripts\python.exe -m ecom_crawler serve `
  --db /path/to/tasks.db --out-root /path/to/tasks `
  --rules-dir experiments/d03/familidoo --no-worker --port 8776

app\.venv\Scripts\python.exe experiments/d08/batch-frontend-min/check_path.py `
  --base http://127.0.0.1:8776
```

## 限制

- 最小路径不证明批次功能；真实批次 E2E 见 `docs/25`／`26`／`33` 的实现验收。
- `app/frontend/dist/` 不提交；FastAPI 在存在构建产物时挂载 `/batch/`，缺失时该路径 404。
- 组件测试使用 mock 的 API 响应，只验证渲染；真实 API 连通由本页脚本文档中的 Playwright 冒烟验证。
