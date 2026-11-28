**ai-ecom-crawler 仓库代理约定**

本仓库是公开电商采集的 monorepo：`docs/` 是业务与验收口径，`app/` 是生产应用，`experiments/` 是原型与证据。业务口径以 `docs/` 为唯一入口，当前状态以 [`docs/15-交接.md`](docs/15-交接.md) 为准；本文件只补充代理执行约定，不复制业务规则。

## 当前切片与并发协作

- 当前状态和下一步以 [`docs/15-交接.md`](docs/15-交接.md) 顶部和 `git status` 为准；开始修改前先读，不要只依赖历史段落。
- 同一仓库可能同时有多个 agent 或用户编辑；发现非本次改动先保留并说明，不用全量 `checkout`／`restore` 清掉，提交前区分本次与并行改动。

## 目录与许可边界

- 生产应用放在 `app/`（本仓库 monorepo）；`app/` 不进入 `scripts/export_docs.py` 的文档包。
- `docs/` 仍是业务口径与验收的唯一入口；`experiments/` 是实验与原型，不作为生产代码。
- 采集运行产物（CSV、结果 JSON、NDJSON、trace、截图、导出 zip、运行期数据库）不进版本控制；放仓库外私有证据库，`experiments/` 只保留规则、脚本、测试、README 和合成 fixture，见 [`experiments/README.md`](experiments/README.md)。
- 项目最终闭源，未授予开源复用许可；第三方依赖保留各自许可证。

## Skill 路由

- 架构、契约、存量体检：`swe-gov`；规格、任务、验收与证据：`ai-verified-delivery`；测试：`web-app-testing`；界面：`frontend-design`／`frontend-qa`；文档：`project-docs`。
- 采集领域：`product-crawl-workflow`、`resilient-browser-fetch`；只加载当前任务需要的入口，不复制 skill 正文。

## 用户视角的采集任务

- 用户要求对指定站点做采集任务时，默认以**人类操作员**身份走系统现有工作流：工作台或等价 API → 批次／任务创建 → 待接入 → 真实模型构建 → 验证／激活 → 正式采集 → 导出核验。不要以开发代理身份手写规则、直接改账本或另写采集脚本，替系统完成本应由产品流程完成的工作。
- 入口可用 WebUI 或 API；优先使用当前用户入口，并确认刷新后任务、构建和待接入状态可见、可恢复、可审计。交付说明记录任务／构建编号、模型与思考等级、规则版本、trace 或事件证据。
- 创建任务前默认只确认站点所属**国家**（如法国 FR）；语言、币种和市场按国家推断为默认值，不要求用户逐项填写，也不把三者当作必须严格区分的字段。核心校验是**预期语言与站点实际显示语言一致**。
- 站点或批次缺少国家时，先用 `question` 询问，选项包含“用户提供”和“访问站点判断并给出建议”。用户明确说“自动推进”“你自己判断”时，访问站点判断国家并说明依据，不再追问。
- 预期语言与实际语言不一致时，先判断是否为多语言站点：检查语言是否体现在 URL 路径、子域或查询参数中，优先使用与预期一致的语言入口。若站点确实不属于当前批次或分组，向用户说明页面语言、URL 和判断依据，并建议调整国家／分组或改用其他站点；不要静默修改分组或继续按错误语言采集。
- 系统流程走不通时，记录具体入口、步骤、错误和证据，先报告缺口；修复系统或代码是单独决定，未经确认不绕过产品流程制造成功。
- 操作员视角的验收场景和边界见 [docs/33](docs/33-用户工作流与前端信息架构.md#操作员视角的端到端验收)。

## 站点评估入口

- 评估站点前先查 [`docs/12-验收基准站点.md`](docs/12-验收基准站点.md) 和 [`experiments/framework-compare/probes/README.md`](experiments/framework-compare/probes/README.md)；已有结论先复用，不重复探测。
- 用户在 [`docs/12-验收基准站点.md`](docs/12-验收基准站点.md) 补充新站点后，直接归位到对应国家／品类并处理：去重、统一链接格式、更新日期；对新增入口各做一次首页可达性复核（直连优先，失败再经本机代理），把失效、跳转、挑战和路径修正写回名单或复核段，不删除历史失败记录；随后跑文档检查并提交，不反复确认站点来源或是否值得加入。
- 单站分诊按 `product-crawl-workflow` 的顺序：robots（只取 `Sitemap:` 行）→ sitemap → 首页/分类 → 1 个样页。挑战站先按项目预算；没有项目预算时默认不超过 5 次目标请求或 3 分钟，超出停止并记录出口、客户端、请求数和停止原因。
- robots.txt 统一策略：任何阶段都机会式抓取一次，只保留 `Sitemap:` 行；禁止直接读取完整 robots.txt 做分析，不解析 `Disallow`／`Allow`／`Crawl-delay`／UA 组，不保存全文、不据此放行或拒绝；404／403／超时等失败不阻塞。详见 [`docs/22`](docs/22-网址发现与分页策略.md) 和 [ADR 0013](docs/adr/0013-robots只探测sitemap行.md)。
- 挑战页处理按 `resilient-browser-fetch`：无头失败先 `--headful`；同一出口用户浏览器能开、自动化仍被拒时，优先 `chrome-late` 或 `cdp-attach`，不要先轮换代理或叠加引擎。
- `campsaver.com` 已知 PerimeterX：默认无头栈会被挑战；2026-11-19 复核中，有头 Chromium 直连首次 200 打开首页，随后同一出口转为 `PRESS & HOLD` 挑战。复核时优先有头/会话复用，不重复跑 headless 矩阵。

## 开发服务与预览地址

- 启动或更换开发服务后，主动在交付说明中给出完整可点击地址，不把地址只留在终端日志或后台输出里让用户自己找；默认入口 `http://127.0.0.1:8765/#/workbench`；批次只作为“新建批次”弹窗的批量创建动作，任务树用目录组织；批次列表、批次详情和站点详情页面已退役。
- 同一时间只保留一个面向用户的入口。端口固定使用 `8765`，启动、重启都沿用上次端口，不为了绕开占用而换端口；端口被占用时先停掉旧实例，再在原端口重启。确需换端口时先说明原因并对齐；旧地址失效时明确说明新地址和旧地址状态，不让用户继续看旧页面。
- 开发期用 `python scripts/serve_dev.py status`、`start`、`restart`、`stop` 管理 8765；不要为面向用户的面板直接另起一个端口。临时验证实例必须登记端口并在交付前停止，用 `status --scan` 或 `prune` 复核遗留实例。
- 前端改动优先用 Vite `5175` 的 HMR（代理默认指向 8765）；构建产物用 `npm run build` 后刷新 8765。只有后端代码、启动参数或启动时缺少 `dist` 导致前端未挂载时才 `restart`，不要把前端改动当作重启理由。
- 有前端构建产物时 `/` 直接返回面板；服务启动后才构建 `frontend/dist` 时需要重启服务。验收说明写清端口、入口和启动命令，截图或证据附当前地址。
- 只改 `app/frontend/`；旧 Vue 和旧原生控制台已删除，不再保留回退入口。
- 端口或入口变化后同步更新 `app/README.md`、交接页和本次交付说明；不要把测试端口当作长期地址。

## 记录与交付

- 新增或复核站点后，把日期、实际出口、客户端、请求数、结论写回对应 probe 的 `probe.json` / `README.md`，或 `docs/12` 的初筛表；不要只留在会话里。
- 技术选型是开写前的硬门：前端、后端及每个进入生产路径的层都要有决策记录；不知道哪个更好时也要按已知信息给出推荐、成功机会、开发效率、可维护性、可扩展性、风险和复审条件，不得开工后即兴选择。Proposed 只用于实验或验证原型，进入 `app/` 生产路径须 Accepted 或登记 Provisional 例外；逐层状态见 `docs/21` 的“技术选型覆盖”。
- 文档改动后运行 `python scripts/export_docs.py`，再用 `python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip` 复核；纯 Markdown 改动至少检查相对链接。
- 改动或退役用户路径、命令、测试分组或验收范围时，交付前按 [交付门](docs/21-开工前检查清单.md#交付门) 反查旧名称和旧覆盖声明，并同步受影响的现行文档。
- 新增或移动 ADR／文档后先纳入 git，再跑 `check_docs_links.py --require-tracked`；未跟踪文件会让本地导出通过、CI 断链。
- 不提交 `dist/`、密钥、Cookie、浏览器 profile、整页原文或运行期任务数据库（`tasks.db` 等）；需要证据时保留任务结果、CSV、事件摘要或可重跑命令。

## 仓库校验

- 文档：`python scripts/check_docs_links.py --require-tracked`；`python scripts/check_examples.py`；`python scripts/export_docs.py`；`python scripts/export_docs.py --check dist/ai-ecom-crawler-docs.zip`。`--require-tracked` 要求链接目标已被 git 跟踪，避免工作区有未入库文件时本地通过、CI 断链。
- 运行时原型：`python -m uv run --project experiments/framework-compare/scrapling --with "pyyaml==6.0.3" --with "jsonschema>=4.23" python -m unittest discover -s experiments/r06/tests -v`。
- Schema 测试不得默认跳过；缺 `jsonschema` 时先补依赖再跑，带 skip 的结果不算完整通过。
- 行尾：以 `.gitattributes` 和 `.editorconfig` 为准；`.sh`／`.bash` 必须 LF，`.bat`／`.cmd` 必须 CRLF。出现 `CRLF will be replaced by LF` 时先看 `git ls-files --eol`，按 [`docs/30`](docs/30-经验教训.md) 处理；不要用 `core.autocrlf`／`core.safecrlf=false` 静音。
- 真实站点验证仍按预算和证据要求手工执行，不纳入默认校验。

## App 校验

- 后端：日常从[后端测试分组](docs/23-测试策略.md#后端测试怎么跑)选 `quick` 或受影响分组；合并前运行不带筛选的 `all`。静态检查 `python -m uv run --project app --extra dev --frozen ruff check app`。
- 前端：`cd app/frontend` 后运行 `npm run lint`、`npm run typecheck`、`npm test`、`npm run format:check`、`npm run build`；首次或依赖变化后先 `npm install`。
- 细节见[应用环境与测试](app/README.md#环境与测试)；缺 Chromium 时按该页安装，跳过不计通过。持续集成(Continuous Integration, CI)仍由[应用工作流](.github/workflows/app.yml)运行完整发现。
