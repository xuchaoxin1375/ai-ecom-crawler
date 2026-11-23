# 旧版前端（Vue，已弃用）

## 状态

本目录是旧版 Vue 3 工作台，**已弃用**。默认入口已经切到新前端 `app/frontend-v2/`（`/next/`）；这里只保留继续导入、站点详情、任务列表／详情、SSE 和构建等尚未迁移的功能。旧版页面顶部和内容区都会显示“旧版已弃用”提示，并提供返回新版工作台的入口。

不要再在这里扩展视觉或新页面；新功能一律进入 `frontend-v2/`，完成功能对等后删除本应用。

## 开发

```powershell
cd app/frontend
npm install
npm run dev
```

Vite 开发服务在 `http://127.0.0.1:5174/batch/`，`/api` 代理到 `http://127.0.0.1:8775`。新版开发服务默认在 `http://127.0.0.1:5175/next/`。

## 构建与测试

```powershell
npm run build
npm test
```

构建产物在 `app/frontend/dist/`，不提交；FastAPI 在存在 `index.html` 时把它挂到 `/batch/`。生产运行：

```powershell
python -m uv run --project app ecom-crawler serve --db /path/to/tasks.db --out-root /path/to/tasks --rules-dir /path/to/rules --port 8765
```

根路径会跳到新版 `/next/`；直接打开 `http://127.0.0.1:8765/batch/` 仍可进入旧版，但会看到弃用提示。

## 边界

- 旧版只修阻断缺陷，不做视觉打磨，不新增功能。
- 任务状态、计数、API、SSE 和账本仍与新前端共用。
- 旧版退役时间取决于继续导入、站点、任务、SSE 和构建迁移到 v2 的进度。
