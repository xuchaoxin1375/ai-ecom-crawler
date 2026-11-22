# 批次工作台前端（技术最小路径）

## 目的与边界

按 [ADR 0009](../../docs/adr/0009-批次工作台前端技术栈.md) 验证批次工作台的 Vue 3 + TypeScript + Vite 技术路径：构建、hash 路由、真实 FastAPI API 连通、`/batch` 静态托管和一条组件测试。当前页面只展示服务状态和真实任务列表，**不是最终批次列表**；批次／站点对象、导入匹配和批次详情尚未实现。

## 开发

```powershell
cd app/frontend
npm install
npm run dev
```

Vite 开发服务在 `http://127.0.0.1:5174/batch/`，`/api` 代理到 `http://127.0.0.1:8775`。先启动本地 `serve`（或真实预览）再打开页面。

## 构建与测试

```powershell
npm run build
npm test
```

构建产物在 `app/frontend/dist/`，不提交；FastAPI 在存在 `index.html` 时把它挂到 `/batch/`。生产运行：

```powershell
python -m uv run --project app ecom-crawler serve --db /path/to/tasks.db --out-root /path/to/tasks --rules-dir /path/to/rules --port 8765
```

打开 `http://127.0.0.1:8765/batch/`。

## 验证状态

- 最小路径只验证技术集成，不代表批次功能完成；批次阶段 1 的实现和真实批次 E2E 见 `docs/25`／`26`／`33`。
- 不使用 mock 数据作为功能验收；组件测试只验证渲染和接口调用。
