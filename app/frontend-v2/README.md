# 前端 v2（默认入口）

本目录是 v2 前端：React 19 + TypeScript + Vite + Tailwind CSS v4，覆盖应用外壳、批次列表、新建批次弹窗、批次详情、继续导入、站点详情和站点级构建。它已是默认入口：FastAPI 根路径 307 到 `/next/`，v2 构建挂载在 `/next/`；旧 Vue 仍在 `/batch/`，标注“已弃用”，只承接未迁移功能。

## 范围

- 桌面端：1280 主规格、1440 检查宽屏；768／390／320、移动抽屉和触屏适配后置。
- 已实现：应用外壳、服务状态、批次列表、筛选、指标条、状态徽标、站点就绪分段条、空／加载／错误状态；批次列表页内的“新建批次”弹窗（解析预览、保存草稿、保存并启动）；批次详情（工作票头、状态带、下一步、站点清单、启动弹窗（全量采集、复跑已完成／已取消站点）、继续导入弹窗、暂停、归档／恢复、取消确认和 ZIP 导出入口）；站点详情（工作票头、任务／覆盖／质量指标条、当前任务控制、结果预览与大图弹窗、质量异常、CSV 预览、任务明细、构建面板与构建／修复弹窗、站点事实、导出和技术详情）。构建时间线通过 `/api/builds/{id}/events` SSE 实时追加，思考块默认展开，工具调用显示状态和入参／输出，新内容自动跟随；实时思考需服务端 `ECOM_BUILD_CAPTURE_REASONING=1`，默认不写入 trace（`ECOM_BUILD_PERSIST_REASONING=0`）。构建启动前 host 机会式探测 robots.txt，只把 `Sitemap:` URL 注入 brief，失败不阻塞，不读整份、不按 disallow 拦截；构建 workspace 写入 `work/AGENTS.md`，固定 brief／参考规则的阅读顺序和“不要读 robots 全文”的规则。全量采集不额外设服务层商品数或时长上限，保留重试次数、进程／适配器安全超时和 sample 存档 20 页。
- 未实现：任务列表／详情、SSE、站点任务历史和完整描述全文弹窗；任务详情当前跳转旧版 `/batch/`。导出 ZIP 的下载内容尚未核对。
- 链接策略：批次行“查看”进入 v2 批次详情；批次详情的站点行进入 v2 站点详情；站点详情里的任务 ID 和“任务详情（旧版）”进入旧版任务页；新建批次、继续导入、站点采集启动、构建启动／修复和取消确认都在 v2 弹窗完成，不跳页；保存、启动、导入或构建后留在当前页并刷新数据。

## 启动

```powershell
cd app/frontend-v2
npm install
npm run dev
```

前端地址是 `http://127.0.0.1:5175/next/#/batches`，批次详情按 `http://127.0.0.1:5175/next/#/batches/<batch_id>` 访问，站点详情按 `http://127.0.0.1:5175/next/#/batches/<batch_id>/sites/<site_key>` 访问，新建批次弹窗可用 `http://127.0.0.1:5175/next/#/batches?new=1` 直接打开。FastAPI 启动后根路径 `http://127.0.0.1:8775/` 会跳到 `/next/`；旧版在 `/batch/`。Vite 把 `/api`、`/batch` 和 `/legacy` 代理到 `http://127.0.0.1:8775`；写请求会按后端要求把代理后的 `Host`／`Origin` 对齐到 API 源，需要另开一个 shell 启动本地服务：

```powershell
app\.venv\Scripts\python.exe -m ecom_crawler serve `
  --db /path/to/tasks.db --out-root /path/to/tasks `
  --rules-dir /path/to/rules --host 127.0.0.1 --port 8775
```

如果服务端口不同，修改 `vite.config.ts` 的代理目标。要在构建时间线里看到实时思考，启动服务前设置 `ECOM_BUILD_CAPTURE_REASONING=1`；需要把思考写入 trace 时再设 `ECOM_BUILD_PERSIST_REASONING=1`，默认不写。

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

- FastAPI 根路径 307 到 `/next/`；`/next/` 返回 v2 构建，`/batch/` 返回旧版构建；旧版显示“旧版界面已弃用”横幅和顶部标识，“前往新版工作台”指向 `/next/`；v2 侧栏把旧功能标为“（旧版）”和“（弃用）”。
- 全量启动通过浏览器请求拦截核对：启动请求的 `limits` 为 `{max_urls:null, max_products:null, max_seconds:null, max_attempts:2}`，不再发送 8000／3000／14400；`archive_mode=sample`、`archive_sample_limit=20`。后端 `test_web`／`test_execution` 25 个和 `test_batches` 14 个用例通过，覆盖 `Limits` 空值、`build_task` 持久化、无上限运行器哨兵、继续导入写入、单站点启动和构建 SSE 快照／结束。
- `lint`、`typecheck`、`test`（20 个用例）、`build`、`format:check` 通过；首屏 JS 约 172 KB gzip，Vite 仍提示单 chunk 超过 500 KB。
- 本地临时账本 10+ 个批次（合成站点列表，仅用于布局和状态走查，未入库）：1280／1440 无页面级横向溢出；列表筛选“草稿”后 4 行，搜索“德国”后 1 行；筛选写入 URL。
- 加载骨架、空态、读取失败、重试、刷新和“包含归档”状态已走查；错误态不再显示“还没有批次”。
- 新建批次弹窗：`?new=1` 可打开并聚焦名称；空名称校验聚焦首错；预览 2 可采／1 待接入／1 无效；保存草稿后关闭弹窗、留在列表、刷新并显示提示；保存并启动受理 1 个站点；Esc 可关闭。
- 批次详情：5 个站点、2 可采／1 待接入／2 无效／重复；状态带筛选写入 `?site=needs` 并收窄到 1 行；搜索与筛选组合；启动弹窗默认聚焦“取消”，Esc 可关闭；归档确认后状态变化，再恢复；已完成批次显示 6 个有效商品和“批次已完成”的下一步，页头“复跑站点”打开预勾选复跑的启动弹窗。
- 继续导入弹窗：打开聚焦站点输入；提交携带 `sites_text`；报告展示可采／待接入／重复／无效计数和问题条目；脏输入关闭有确认；导入后站点清单刷新，弹窗可继续追加。
- 站点详情：`b-18c91ba286eb` 的可采站点显示“站点可采，尚未启动”、规则修复面板和“回批次启动”；待接入站点显示“还没有可用规则包”，构建弹窗默认聚焦“取消”，全量目录请求体为 `catalog_scope=full`、`catalog_products=3000`、`max_seconds=900`、`archive_mode=sample`、`repair_rounds=1`；修复弹窗请求体为 `mode=repair` 并携带修复原因。已完成站点 `b-8b26f1326b07` 显示 6 张有效商品卡、6 行 CSV、质量异常 0 和“采集完成”，商品卡可打开大图弹窗。
- 任务控制经路由拦截核对：运行中显示“暂停任务”，暂停后显示“继续任务”，取消走确认弹窗；暂停、继续、取消三个请求均发出并显示“已受理”。
- 构建时间线经本地 SSE 模拟核对：思考文本随帧增长、工具卡片从“运行中”变为“完成”并显示入参／输出、助手文本按时间穿插、新内容自动跟随；流结束后状态从“实时”变为“已结束”；页面 axe 0 violations、0 incomplete，1280／1440 无页面级横向溢出。预览服务以 `ECOM_BUILD_CAPTURE_REASONING=1`、`ECOM_BUILD_PERSIST_REASONING=0` 重启，构建弹窗默认勾选“实时思考”，请求体携带 `capture_reasoning=true`。
- 真实构建 `build-b350864915c5`（`bennytex.com`，`opencode-go/deepseek-v4.1-flash` variant high）：SSE 收到实时 reasoning 增量、工具卡片和助手文本，约 273 秒后结束；目标站是 Squarespace parking page／private，`robots.txt` disallow all，主机验证无有效商品，构建失败。实时思考链路可用；成功构建和规则安装待另选站点。
- axe 批次列表、批次详情、站点详情（可采／待接入／已完成）主页面均 0 violations、0 incomplete；启动／归档／继续导入／构建／商品预览弹窗 0 violations、2 incomplete（Radix 焦点守卫与遮罩背景的对比度无法自动判定，已人工查看）；新建批次弹窗 0 violations、2 incomplete（同类原因，已人工查看）；控制台和页面错误 0。
- 列表批次行“查看”进入 v2 批次详情，页内“返回批次列表”保留列表查询串；批次详情的站点行进入 v2 站点详情；桌面端表头在页面滚动时吸附（1280 下滚动到页底验证表头停在 56px）。
- 未执行：成功构建与真实规则安装、权限审批、真实任务暂停／继续／取消、导出 ZIP 下载内容、任务列表／详情、SSE、站点任务历史和完整描述全文弹窗；真实批次 `b-586052683409` 对照；完整视觉评审；768／390／320、移动抽屉、触屏、跨浏览器和读屏；旧版退役、回退演练和生产环境实际部署验证。

截图和临时账本按根目录 `AGENTS.md` 放在仓库外，不提交。

## 设计依据

- [前端设计系统与 v2 视觉方向](../../docs/35-前端设计系统与视觉方向.md)
- [ADR 0012：前端 v2 技术栈与设计系统](../../docs/adr/0012-前端v2技术栈与设计系统.md)

## 边界

- v2 已是默认入口，但整体仍按 **Provisional** 管理；任务、SSE 和站点任务历史迁移完成后才退役旧版。
- 截图、运行期数据库和其他运行产物不提交到仓库；按根目录 `AGENTS.md` 和 `experiments/README.md` 的约定放到仓库外证据库。
- 旧 Vue 应用已弃用，只修阻断缺陷，不再扩展视觉或新页面。
