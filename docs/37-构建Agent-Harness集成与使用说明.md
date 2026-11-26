---
title: 构建 Agent Harness 集成与使用说明
document_type: technical-guide
status: provisional
updated: 2026-11-26
---

## 目的与范围

本文说明 `app/` 当前如何把构建 Agent 接入批次工作流，以及使用时需要知道的边界、配置和排障入口。它描述**当前实现**，不替代[构建 Agent Harness 契约](adr/0005-构建Agent与Harness契约.md)、[构建 Harness 选型与集成方式](adr/0006-构建Harness选型与集成方式.md)和[构建环境与依赖基线](20-构建环境与依赖基线.md)中的决策。

适用对象是维护构建服务、调整 harness 配置或排查构建失败的人。普通采集任务的运行期没有 LLM，也不读取本文的 skills／MCP。

## 当前集成形态

```text
批次站点 → BuildManager → BuildService → OpenCodeHttpAdapter
        → opencode serve（回环 HTTP/SSE）→ 模型 + 工具
        → 工作区 out/plan/rule.yaml
        → 主机预检／有界验证 → candidate 规则安装
```

| 组件 | 当前职责 |
| --- | --- |
| `BuildManager` | 准备构建记录、工作区输入、模型／代理／预算；调用服务；验证并安装规则 |
| `BuildService` | 一次只持有一个活动构建；事件泵；权限请求；暂停／取消；依赖桥 |
| `HarnessAdapter` | 构建服务与具体 harness 的边界；当前实现是 `OpenCodeHttpAdapter` |
| `OpenCodeServer`／`OpenCodeClient` | 启动和回收 `opencode serve`；随机回环端口；Basic Auth；HTTP/SSE |
| 工作区 | `input/`、`work/`、`out/`、`logs/`、`control/`；`work/` 是 Agent 的当前目录 |
| 主机验证 | 选择器预检、隔离账本跑有界任务、域名／市场／币种／内容审计 |

当前参考版本：OpenCode 2.3.2 冒烟通过，适配器 `opencode-http/0.1`，传输 HTTP + SSE；模型默认 `opencode-go/deepseek-v4.1-flash`，`variant=high`。这些版本和模型是参考默认，不是运行期依赖；升级 OpenCode 后先跑 `experiments/harness/opencode_smoke.py`。

## 工作区与输入输出

每次构建一个独立目录：`<out-root>/builds/<build_id>/`。

- `input/build-brief.md`：站点、范围、市场、预算、代理、输出契约和 robots 信息。
- `input/reference-rule.yaml`：通用规则示例；修复时还有 `existing-rule.yaml` 和 `repair-context.json`。
- `input/build-task.json`：机器可读目标、预算、权限规则和 skills 清单。
- `work/AGENTS.md`：构建工作区规则，自动作为项目指令加载。
- `out/plan/rule.yaml`、`out/evidence/build-notes.md`：Agent 的交付物。
- `out/result.json`、`out/session.ndjson`、`out/trace.json`／`trace.md`：结果、事件和复盘材料。
- `logs/`、`control/`：宿主日志、暂停标志和依赖请求；Agent 不需要读写。

`input/` 对 Agent 只读；`out/`、`work/` 可写。Agent 不能写 `logs/`、`control/` 或 skills 目录。

## Skills、MCP 与网络工具

### Skills

构建会话共享宿主 skills，只读，不复制。当前发现根：

- `ECOM_BUILD_SKILLS_DIR`（显式覆盖或补充）
- `~/.config/opencode/skills`
- `~/.claude/skills`
- `~/.agents/skills`

`build-task.json` 的 `skills` 字段记录 `roots` 和每个 `SKILL.md` 的 `id`／`sha256`，便于复盘“这次构建看到了哪些技能”。技能通过 OpenCode 的 skill 工具加载；技能内的 `references/`、`scripts/` 可以读取，但 skills 根不可写。

当前常用的技能包括 `product-crawl-workflow`、`resilient-browser-fetch`、`browser-automation`、`network-access`、`htmlmini`、`scrapling-official` 等。它们和宿主安装的版本共用；换机器或改技能目录会改变构建可用上下文，需要把 manifest 当作构建输入的一部分。

`product-crawl-workflow` 中“先查项目已有站点结论与探针记录”的步骤不进入构建默认流程：构建只使用本次 `input/`、`out/`、`work/` 和声明的样例 URL。若要让构建复用历史站点结论，应把筛选后的证据复制到 `input/docs/` 或写进 brief，而不是放开整个仓库。

### 符号链接

当前不需要符号链接：OpenCode 已经发现全局 skills，session permissions 只额外放开了 skills 根的只读访问。需要把构建限制在“工作区内路径”时，可考虑：

- Windows 目录联接：`mklink /J <workspace>\work\.opencode\skills <host-skills-root>`；目录联接通常不要求管理员权限。
- 符号链接：需要开发者模式或相应权限；跨盘、权限和清理行为要单独验证。
- 只读副本或 `ECOM_BUILD_SKILLS_DIR` 指向固定的受管目录；适合需要固定版本、可复现构建的场景。

OpenCode 的项目技能优先级高于全局技能。使用联接／符号链接时，项目侧的 `.opencode/skills` 可能遮蔽同名全局技能；先验证 ID、description 和 `references/` 是否都能读到，再用于正式构建。不要链接整个用户主目录或配置根目录。

### MCP

当前允许 `browse` 和 `htmlmini` 两个 MCP 工具，其他 MCP 默认被 `*_*` 权限规则拒绝。

- `browse` 驱动宿主真实浏览器，可能带已有登录态、扩展和标签页；使用范围、留存和清理按操作者约定。
- `htmlmini` 可以提取 URL，也可以读取本地 HTML 文件；它不替代工作区文件权限，使用时应只指向公开页面或本次输入。
- 新增 MCP 前，先更新 `default_permissions()` 的 allowlist、测试和本文，不要只改 OpenCode 全局配置。
- MCP 工具动作名是 `<server>_<tool>`；`*` 规则会一并匹配，新增服务时先检查是否被 catch-all 拒绝。

### 网络

`webfetch` 和 `websearch` 默认允许，Patchright 也可用。构建 brief 仍优先目标 origin 和路径前缀；网络技能可以使用自己的正常端点，但请求应保持在 brief 的预算内，并把结果当作不可信内容。

登录、付费和个人数据提交不在默认自动化范围；挑战页、验证码、浏览器指纹和会话风控按 [ADR 0022](adr/0022-挑战页处理边界.md) 和[合规检查清单](17-合规检查清单.md)处理，具体边界由项目方逐站确认。项目合规检查清单仍是独立文档。

## 权限与会话控制

`default_permissions()` 生成 session 级规则，`OpenCodeHttpAdapter` 在创建 session 时传入。核心规则：

| 动作 | 当前策略 |
| --- | --- |
| `skill` | 全部允许（宿主 skills 只读共享） |
| `browse_*`／`htmlmini_*` | 允许；其他 MCP 工具和资源动作由 `*_*` 拒绝 |
| `question`／`subagent` | 拒绝；构建是无人值守的 |
| `read` | 允许；工作区外由 `external_directory` 收紧 |
| `edit`／`write` | `work/`、`out/` 可写；`input/`、`logs/`、`control/`、skills 根拒绝 |
| `shell` | 允许；`git push`、`sudo` 拒绝 |
| `webfetch`／`websearch` | 允许 |
| `external_directory` | 只放开 `input/`、`out/` 和各 skills 根；其他宿主路径拒绝 |

`pause-gate` 插件在权限 hook 中把动作提升为 `ask` 并扣住请求；恢复时回复 `once`。它不暂停模型推理，已启动的工具可能跑完。取消走 `interrupt`，拒绝 pending 权限并回收 session／server；迟到事件按构建 ID 拒收。

**权限规则的生效位置（2026-11-24 复核）**：OpenCode 的会话权限在 agent 规则之后评估，最后匹配的规则生效。`BuildManager` 创建每个构建任务时写入 `default_permissions(workspace, skill_roots)`，并可通过 `extra_permissions` 在其后追加 `ask`／`deny`；`OpenCodeHttpAdapter(permissions=...)` 只在任务没有自带权限时作为回退。2026-11-24 的审批走查把 `ask` 设在 adapter 上，但 `BuildManager` 随后用默认 `allow` 写入任务，覆盖了它，所以模型调用 `shell` 时没有出现权限请求；这是宿主侧权限入口用错，不是 OpenCode 没有触发。需要真实 `ask` 时，在 `BuildManager(extra_permissions=[...])` 或 `create_app(..., build_extra_permissions=[...])` 传入，并确认规则位于默认规则之后。

`request_dependency` 工具把依赖请求写到 `control/dependencies/`，宿主侧 `DependencyBridge` 按基线／allowlist 自动安装，未知包或系统级包走一次性审批。直接 `pip install`／`npm install` 到全局环境不属于允许范围。构建详情现在显示待审批依赖的包名、版本、manager、scope 和原因，不只显示请求 ID。

**依赖策略接线决策（2026-11-24）**：v1 生产默认保持 `DependencyPolicy.empty()`，不在宿主环境自动安装包；批准未知依赖仍会返回 `no installer is configured`，由操作者手工安装。需要自动安装时，显式设置 `ECOM_BUILD_PYTHON` 指向专用 build venv，并用 `ECOM_BUILD_DEPENDENCY_ALLOWLIST=name==version,...` 限定可自动安装的包；两者都配置后 `BuildManager` 才接入 pip／uv 安装器和安装后验证。构建详情返回 `dependency_installer_configured`，便于界面区分“可批准安装”和“只能手工处理”。不把宿主 Python 或全局环境作为安装目标。

`shell` 仍以宿主用户权限运行，文件权限规则不能阻止它读取宿主文件；这是当前 guardrail 的已知边界，不是安全沙箱。需要强隔离时使用专用用户、容器或独立设备。

## 事件、trace 与验证

构建会话使用独立状态：`QUEUED`、`CREATED`、`RUNNING`、`PAUSING`、`PAUSED`、`CANCELLING`、`CANCELLED`、`FINISHED`。它不映射为采集任务状态；`QUEUED` 只表示请求已持久化、等待全局单运行槽位，尚未创建 Harness 会话。

事件写入 `out/session.ndjson`；trace 写入 `out/trace.json`／`trace.md`，包含工具调用、命令／路径摘要、截断输出、可见消息、tokens／费用、主机验证和修复轮次。生产默认不保存 reasoning；开发期设置 `ECOM_BUILD_DEV_TRACE=1` 时，默认实时展示思考并写入 trace。需要单独控制时用 `ECOM_BUILD_CAPTURE_REASONING=1` 开启实时思考、`ECOM_BUILD_PERSIST_REASONING=1` 允许 trace 落盘；显式开关优先于 `ECOM_BUILD_DEV_TRACE`，构建请求的 `capture_reasoning` 仍可按单次覆盖。

主机验证在 Agent 结束后执行：

- 先静态编译规则中的 CSS 选择器，避免联网后才发现不支持的选择器。
- 在隔离账本和输出目录跑一次有界 product 任务。
- 检查域名、市场、币种、至少一个有效商品和描述内容审计。
- 验证失败默认把精确错误和失败样例回给同一会话修复一轮；`ECOM_BUILD_MAX_REPAIR_ROUNDS` 控制轮次，`ECOM_BUILD_REPAIR_SECONDS` 控制额外时间。
- 通过后规则以 `candidate` 安装；`verified` 仍需独立环境复跑和人工签字，Agent 不能自升。

## 使用方式

启动本地服务：

```powershell
$data = "C:\path\to\evidence\workbench"
python -m uv run --project app ecom-crawler serve `
  --db "$data\tasks.db" --out-root "$data\out" --rules-dir "$data\rules" --port 8765
```

常用环境变量：

| 变量 | 作用 |
| --- | --- |
| `ECOM_BUILD_MODEL_PROVIDER` | 模型 provider，默认 `opencode-go` |
| `ECOM_BUILD_MODEL_ID` | 模型 ID，默认 `deepseek-v4.1-flash` |
| `ECOM_BUILD_MODEL_POOL` | 启动时默认模型池和默认档位；页面配置优先，页面恢复后回到该值 |
| `ECOM_BUILD_MODEL_VARIANT` | 思考等级，默认 `high` |
| `ECOM_BUILD_PROXY` | 构建默认出口；主机验证沿用 |
| `ECOM_FETCH_PROXY` | 运行期静态／浏览器 fetcher 出口 |
| `ECOM_BUILD_SKILLS_DIR` | 额外或固定的 skills 根 |
| `ECOM_BUILD_PYTHON` | 专用 build venv 的 Python；未设置时不安装依赖 |
| `ECOM_BUILD_DEPENDENCY_ALLOWLIST` | 逗号分隔的 `name==version`；仅在 `ECOM_BUILD_PYTHON` 设置后生效 |
| `ECOM_BUILD_DEV_TRACE` | `1` 时开发期默认实时展示思考并写入 trace；生产不设 |
| `ECOM_BUILD_CAPTURE_REASONING` | `1` 时捕获实时 reasoning；显式值优先于 `ECOM_BUILD_DEV_TRACE` |
| `ECOM_BUILD_PERSIST_REASONING` | `1` 时允许 reasoning 写入 trace；显式值优先于 `ECOM_BUILD_DEV_TRACE` |
| `ECOM_BUILD_MAX_REPAIR_ROUNDS` | 自动修复轮次 |
| `ECOM_BUILD_REPAIR_SECONDS` | 每轮修复额外时间 |
| `ECOM_BUILD_VALIDATION_SECONDS` | 主机验证基础时长，默认 120 秒 |
| `ECOM_BUILD_BROWSER_VALIDATION_SECONDS` | 浏览器规则的主机验证时长下限，默认 600 秒；实际取基础时长与它的较大值 |
| `ECOM_BUILD_MAX_PRODUCTS` | 主机验证商品样本数默认值，默认 6；单次构建请求可覆盖 |

站点构建请求的 `catalog_scope` 支持 `sample`、`target` 和 `full`：

- `sample`：入口页有界样本，默认。
- `target`：`catalog_products` 指定执行目标（例如 10），要求 `scope.max_products` 和发现来源覆盖该目标；主机验证仍只用 `max_products` 样本。Shopify 可用 `product_source` 覆盖目标。
- `full`：全站目录，要求 listing／sitemap／html_index／public_json 来源（或 Shopify `product_source`），并自动把 `scope.max_products` 提升到目录目标。

主机验证的 `max_products` 和秒数会写入构建验证记录；规则使用浏览器时，验证秒数自动提升到 `ECOM_BUILD_BROWSER_VALIDATION_SECONDS`，避免 120 秒只验完 1 件。`stealth` 引擎同样按浏览器规则计时。

### 挑战站与 stealth 引擎

- `fetch.default_engine` 支持 `static`、`browser`、`stealth`、`http_json`。`browser` 是 Patchright 渲染，不求解挑战；`stealth` 使用 Scrapling `StealthySession` 和 `solve_cloudflare`，用于 Cloudflare 类挑战挡住静态与 Patchright 的站点。
- `stealth` 复用 `fetch.browser` 的页面选项：`timeout_ms` 实际至少 240 秒，`challenge_wait_ms` 实际至少 180 秒；`profile_name` 会加 `stealth-` 前缀。一个任务复用一个会话和 profile，任务结束或租约接管时清理。
- 构建简报会给出宿主 Python 和 `resilient-browser-fetch` 的 Scrapling 探针命令。构建 Agent 只有在静态和 Patchright 都被挑战挡住、且 stealth 样本返回真实商品内容时才写 `default_engine: stealth`；stealth 仍被挡时记录 `ACCESS` 并停止。
- `stealth` 不支持 `load_more`／`infinite_scroll`；挑战站优先用 sitemap／listing 的 URL 分页。sitemap 是索引时用 `sitemap_patterns` 选中商品子图，并给足 `max_sitemaps`。
- 挑战站的目标构建应把入口页或 listing 放在 `discovery.sources` 第一位，sitemap 后置；只声明 sitemap 会让第一个请求落在文档 URL 上，冷启动挑战可能耗尽 600 秒验证预算。构建简报已给出 listing-first 示例。
- 构建 Agent 在规划发现前必须加载 `product-crawl-workflow`，挑战探测前必须加载 `resilient-browser-fetch`；`build-notes.md` 记录实际加载的 skill 和应用到的发现／字段／挑战规则。构建简报不再只写“available, use relevant ones”。
- 主机验证拒绝重复样本：≥3 个商品样本的名称或主图全部相同即失败，避免 review widget／organisation JSON-LD 造成的假通过。运行期 `json_ld_product()` 在多个 Product 块中优先 `offers`，其次 `sku`／`mpn`／`gtin`，最后 `name`。
- 构建还要留视觉证据：至少一个代表性商品页截图、一张本地商品图、`out/evidence/visual/baseline.json` 和 `compare.md`。截图和商品图优先走同一已放行浏览器会话；静态图片请求被挡时保存渲染后的元素截图并标记 `rendered`。模型不能看图时在基线里标记待人工复核，不能写成已核对。当前是软要求，缺失时记录警告和原因，不直接判构建失败；主机验证结束后会检查这些文件，把缺失写入 `validation.visual_evidence` 和站点备注。格式见[采集视觉证据与待办](44-采集视觉证据与待办.md)。
- 真实 partsfornissans 探测的冷启动约 157–341 秒、同会话后续约 5–11 秒；premierangling 冷启动约 337 秒，人工点击约 101 秒。冷启动波动大，600 秒验证预算不是固定成本。引擎设计见 [ADR 0021](adr/0021-stealth挑战引擎.md)，处理边界见 [ADR 0022](adr/0022-挑战页处理边界.md)。

入口：`http://127.0.0.1:8765/next/#/batches`。站点详情可以启动构建、查看时间线、暂停／恢复／取消、处理权限和依赖请求。同一时间只允许一个构建运行；其他站点提交后进入 `QUEUED` 队列，构建列表／详情显示排队位置并支持取消排队。重启会保留排队项；运行中的会话标为 `FINISHED/interrupted` 并保留，用户可在构建详情继续。

### 构建模型池

**受控试点范围**：沿用 React、FastAPI 和 SQLite 构建账本，不增加并行槽位、模型网关或成本调度。省略模型选项时先看固定默认模型：设置后新构建和修复使用该模型；未设置时按模型池轮转。也可为单次构建指定模型和思考等级。分配单位是一次入队的站点规则构建或修复，不是商品、采集任务或自动修复轮次。锁定后的模型随构建记录保留，重启或继续会话不重新分派。本期不自动换供应商、不做自动故障转移。

- **验收**：两个模型连续接收的新均衡请求交替分配；固定默认模型时连续新构建都使用该模型，切回轮询后按原游标分配；手动请求不移动轮转顺序；固定模型最近探测失败仍使用，轮询会跳过失败档位；最近失败的默认档位不参与轮转，若全部失败则明确拒绝入队。未探测的模型仍可分配，但不标为可用。
- **探测**：只由用户点击发起，可在加入活动池前对任意可用聊天模型发起；每次发送一个有界的合成文本请求，不含构建提示、规则或站点信息。显示最近结果、时间和耗时；不进行后台监控。连通性通过不等于构建能力、可用额度或工具调用已验证。
- **取舍与回退**：按既有单调度进程的入队顺序轮转，不追求 token、成本或完成时间均衡。多进程调度、健康历史、自动故障转移另行评估。清除模型池配置后恢复原单模型默认；已入队项不改派。固定默认模型由页面设置；未设置时才轮转。
- **模型来源**：可用模型由 OpenCode 运行时读取 `/api/model`（短生命周期 `opencode serve`，轮询到快照稳定；失败回退 `opencode models --standalone` 的 ID 列表）。名称、思考档位、上下文／输出限制、工具和输入模态都来自 OpenCode；`CATALOG` 只作回退和覆盖。`commandcode/deepseek/deepseek-v4.1-flash` 开放 `low`／`high`／`max`，凭据由 OpenCode 的 commandcode 集成解析，页面不保存 Key；`low`／`max` 尚未实测。

#### 可用模型发现

`GET /api/builds/models/available` 启动短生命周期 `opencode serve`，读取 `/api/model` 并等待快照稳定，结果缓存 60 秒；`?refresh=1` 强制刷新。读取失败时回退到 `opencode models --standalone` 的 ID 列表，并把对应模型标为缺少元数据。发现过程不发送模型请求、不读取或展示密钥，返回名称、档位、上下文／输出限制、工具和输入模态。

- **来源目录、活动池、分配方式分开**：页面默认分页展示可用模型，可搜索、按供应商／元数据状态筛选，也可按“未加入／已在模型池”回看活动池；已加入的模型保留在列表中并标记状态。活动池是实际构建使用的子集，分配方式显式选择轮询或固定默认。
- **数量与档位**：模型可能很多，默认显示第一页（每页 20 个），可切换每页 10／20／50 条，提供上一页／下一页、页码和“跳至”页码输入；搜索或筛选变更回到第 1 页。元数据包含思考档位、上下文／输出限制、工具和输入模态；只有 OpenCode 未返回元数据的模型才允许自由填写档位并标为缺少元数据。
- **加入前测试**：`POST /api/builds/models/check` 接受任意合法模型引用，不要求模型已在活动池。可用列表的“测试可用性”在加入前发送一次有界的合成文本请求（输出上限 256 token）；已知 `max_tokens`／`max_completion_tokens` 时按已知字段发送，未知时先试 `max_tokens`，遇到 400／422 再试另一种。同一时间只允许一个探测。可见文本、输出 token 或 reasoning token 任一有活动即视为连通，避免推理模型把预算用在推理时被误报为无输出。结果按完整引用保存在内存，加入并保存后仍匹配的结果保留。
- **失败回退**：发现失败时保留已保存的活动池和默认模型，显示错误并保留手动引用入口，不清空配置。
- **生效边界**：刷新只更新可用列表；OpenCode 供应商配置由下一次构建读取，不需要重启采集服务。页面保存模型池/默认模型对新构建热生效；只有应用代码或环境变量变更需要重启。

#### 模型配置页

入口：`http://127.0.0.1:8765/next/#/models`，侧栏“模型配置”。页面支持从 OpenCode 读取模型元数据（分页、搜索、供应商／元数据状态／模型池归属筛选）、在加入前测试可用性、维护活动池、显式选择轮询或固定默认模型、调整默认思考等级、保存、恢复环境变量配置和按模型／档位测试可用性。

- **默认模型**：分配方式为“轮询全部模型”时不固定；选择“固定默认模型”后，新构建和修复始终使用活动池中的该模型。也可在活动池行内或可用模型的“已在模型池”条目上直接点“设为默认”，会自动切换到固定默认。默认值必须是活动池中的完整引用且档位一致。固定模型即使最近探测失败也不会自动换模型；轮询会跳过标记失败的档位。
- **来源与优先级**：页面配置保存在账本 `app_settings` 的 `build_model_pool` 和 `build_model_default` 键，优先于 `ECOM_BUILD_MODEL_POOL`；点击“恢复环境变量配置”删除页面设置，回到服务启动时的环境值。两者都为空时使用单一默认模型；环境值只定义轮转名单，不定义固定默认模型。
- **生效范围**：保存后新入队的构建和修复立即使用新池和固定选择；已排队和运行中的构建保留入队时锁定的模型。保存不做构建重启。
- **校验**：引用格式为 `provider/model#variant`；同一模型只能出现一次，最多 16 个；已知模型的默认档位必须在可选范围内；默认模型必须在活动池中。未知模型允许保存但标为未验证。非法保存不改变当前池或已保存值。
- **只读**：`serve --read-only` 或 `ECOM_BUILD_DISABLED=1` 时页面只读，写接口返回 403 或 409。启动时若页面设置损坏，服务记录警告并回退到环境值；默认模型损坏时忽略并回到轮询。
- **接口**：`GET /api/builds/config` 返回模型、`default_model`、来源、可编辑状态和已知模型目录；`GET /api/builds/models/available` 返回 OpenCode 可见模型；`PUT /api/builds/config/models` 保存 `{"refs": [...], "default_ref": "provider/model#variant"}`，`default_ref` 为空表示轮询；`DELETE /api/builds/config/models` 恢复环境值并清除固定默认。
- **探测状态**：只保存在内存，按完整引用记录；可在加入前测试，加入并保存后仍匹配的结果保留，重启后恢复为未探测。测试会产生一次有界的真实模型请求，可能产生少量调用费用；页面不做自动巡检。

决策和优先级见 [ADR 0016](adr/0016-模型池配置页与持久化.md)。页面只管理模型引用和档位，不保存供应商 API Key。构建和探测均由 OpenCode 自行解析凭据，可使用 OpenCode 已保存的供应商账号，或在用户级 `opencode.jsonc` 的 `providers.<id>.settings.apiKey` 用 `{file:...}` 引用仓库外的密钥文件。也支持 OpenCode 子进程自身已有的环境变量；共享后台服务专属的变量不会被独立进程自动继承。不要把明文密钥放进仓库或配置示例。

启动前在采集服务进程环境中设置默认模型池。该变量只定义**轮转名单和默认思考等级**，不存密钥；固定默认模型只在页面配置。页面保存后以页面配置为准。

```powershell
$env:ECOM_BUILD_MODEL_POOL = 'opencode-go/deepseek-v4.1-flash#high,yjwd-gpt-enterprise/gpt-6.1-terra#medium'
```

用上文的启动命令重启采集服务，然后打开模型配置页或站点详情的「启动方案构建」／「重新验证／修复规则」。模型池为空时构建弹窗会提示默认模型和模型配置入口。`GET /api/builds/config` 可只读核对模型池、`default_model`、来源和本进程最近探测结果。在「默认模型」选择具体模型即固定，选择“轮询全部模型”则按池轮转；保存后只影响新构建。选择模型和档位后即可点「测试可用性」，加入前和加入后都可测试；它使用临时 OpenCode 会话发送有界合成消息，不触发构建，不传站点数据或工具。探测走 OpenCode，不要求采集服务另存一份 Key；探测时长包含启动、调用和清理。探测插件未就绪时不会调用模型，界面会提示原因。CommandCode DeepSeek V4.1 Flash 也可直接加入并测试，`low`／`max` 档位尚未实测。其他已在 OpenCode 接入的模型会直接显示名称、档位、上下文和模态，可在加入前测试；只有 OpenCode 未返回元数据时才需要手动填写档位。

如果 YJWD 只对共享 OpenCode 服务可见，可在用户级 OpenCode 配置已有的 YJWD 供应商条目中补 `settings.apiKey`，不覆盖同一 `settings` 下的 `baseURL`。示例引用由操作者管理、仅本人可读的仓库外密钥文件：

```jsonc
{
  "providers": {
    "yjwd-gpt-enterprise": {
      "settings": { "apiKey": "{file:~/.secrets/yjwd-gpt-enterprise.key}" }
    }
  }
}
```

先确认独立 OpenCode 目录识别模型和指定档位，再启用双模型池。回环夹具已验证 OpenCode 2.4.1 能解析该类引用，发出带正确档位和有界输出上限的探测请求；模拟上游 503 时仅发出一次请求并返回 503。该结果不代表新探测路径已对真实供应商复验。

## 跨重启恢复

- 服务重启或正常停止时，已创建会话的活跃构建不再删除会话，而是记 `FINISHED` / `outcome=interrupted`，同时释放站点和全局构建槽位；`QUEUED` 继续调度。
- 构建详情点“继续构建会话”时，适配器按 `session_id` 从 OpenCode 持久化存储重载会话，拒绝上一轮遗留的权限请求，再发送用户的继续指令；工作区缺失或会话已删除时返回 `BUILD_SESSION_UNAVAILABLE`，不伪造会话。
- Agent 已结束但主机还没完成验证／安装时（`out/result.json` 为 `FINISHED/succeeded` 或构建停在 `VALIDATING`），启动对账会用工作区重建本地会话并重跑主机验证，不调用模型，也不自动开启新的修复轮次。
- 恢复依赖同一台机器的 OpenCode 数据目录、同一构建工作区和相同 OpenCode 版本；这些条件不满足时不保证可恢复。未知在途工具按失败处理，不当作成功。

## 注意事项与已知限制

- **OpenCode HTTP API 仍是 experimental**。升级前锁定版本，升级后跑无模型 smoke、权限探针和一次有界真实构建。
- **OpenCode 数据目录没有按构建强制隔离**。同一台机器上的全局配置、会话数据和 provider 配置仍共享；不要把它当多租户隔离。
- **全局 `AGENTS.md` 仍会加载**。`work/AGENTS.md` 明确以构建工作区规则为准；出现冲突时不要静默采用全局规则。
- **skills 是宿主环境的一部分**。构建可复现性取决于 skills 版本和目录；正式构建前记录 manifest，需要固定版本时使用 `ECOM_BUILD_SKILLS_DIR` 或只读副本。
- **`browse` 和 `htmlmini` 扩大可见面**。前者可能带真实登录态，后者可读本地 HTML；只用它们访问公开页面或本次输入，不要把它们当文件隔离。
- **`shell` 是最大边界缺口**。它能绕过 read／edit 规则；`grep`／`glob` 的路径检查也是尽力而为。需要强隔离时使用专用用户、容器或独立设备，不能只靠 prompt。
- **模型调用有费用**。一次构建可能持续数分钟；先用小预算和单站验证，再放大。
- **出口与市场必须一致**。浏览器样本、静态请求和主机验证走不同出口时，币种／促销价可能不同；换出口视为新的市场上下文。
- **robots 只取 Sitemap 行**。不要读整份 robots、不解析 `Disallow`／`Crawl-delay`，也不要把它当停止信号。
- **一次只支持一个运行中的构建**。不同站点会进入 FIFO 队列，但没有优先级；并发构建、完整多轮会话 UI 和自然规则缺陷连续多轮仍未完成；构建详情已提供权限／依赖审批页面，真实模型两轮修复已用注入主机验证失败走查；依赖审批已用真实模型和临时 venv 安装走查，权限请求未被 OpenCode 实际触发，生产安装器仍未接线；跨重启会接管并保留会话，但需要用户显式继续，恢复依赖本机 OpenCode 数据目录。
- **跨平台差异**。Windows 的进程树回收、浏览器 profile 锁、目录联接和路径大小写需要单独验证；WSL 只验证过 fake server／适配器和部分安装路径。

## 排障入口

| 现象 | 先查 |
| --- | --- |
| `opencode` 找不到 | `OPENCODE_BIN`、PATH、OpenCode 版本 |
| session 创建失败或 404 | OpenCode 版本、适配器端点、server 日志 |
| skill 没有出现在列表 | skills 根、`SKILL.md`、description、`skill` 权限、项目同名技能遮蔽 |
| MCP 工具不可用 | `mcp.servers` 配置、`disabled`、`*_*` 权限、server 状态 |
| 权限被拒绝 | `external_directory`、`edit` 目标、skills 根、`git push`／`sudo` |
| 构建卡住 | 暂停标志、pending 权限、模型超时、`question` 被拒绝后的重试 |
| 验证失败 | 选择器预检、市场／币种、失败样例、`out/trace.md` |
| 依赖请求无响应 | `DependencyBridge`、审批状态、构建是否暂停／取消 |
| 符号链接／联接不生效 | Windows 权限、OpenCode 项目技能优先级、目标路径是否可读 |
| 第二个构建被拒 | 已有活动构建；先等待、暂停或取消 |

## 验证状态

### 2026-11-23 本次验证

- 构建 `build-6d3cbafe1188`（`familidoo.fr`，`catalog_scope=sample`，`max_products=3`，`max_seconds=600`）：`FINISHED`／`succeeded`，约 334 秒，34 次工具调用，0 轮自动修复；主机验证 6 条有效、0 失败；规则 `familidoo-fr-build@2026.11.23-1` 以 `candidate` 安装，站点 `readiness=ready`。
- 直接 harness smoke：模型加载 `product-crawl-workflow` 并引用其首标题；`htmlmini_extract_url` 成功返回 `Example Domain`；`browse` MCP 成功打开 `https://example.com` 并返回标题。两组 smoke 均未使用 shell。
- 说明：完整构建主要使用 `webfetch` 和 `shell`，没有强制调用 skill／MCP；skill、`htmlmini` 和 `browse` 由单独 smoke 验证可用。

- 适配器、权限、暂停门、依赖桥和构建工作区有单元测试；`app/tests/test_builds.py`、`test_harness.py`、`test_service.py`、`test_dependency_bridge.py` 覆盖主要路径。
- 真实 `opencode serve` 无模型 smoke 通过：session、事件、权限请求、关闭和 server 回收。
- 真实模型构建已在 `familidoo.fr`、`sixmoondesigns.com` 等站点完成工具调用、自然完成、主机验证和 candidate 安装；证据在 `experiments/build-agent/`。
- 未完成：完整会话 UI、自然规则缺陷连续多轮、生产依赖安装器接线、权限请求的真实触发核查、安全沙箱和跨物理设备复现。

## 参考

- [构建 Agent Harness 契约](adr/0005-构建Agent与Harness契约.md)
- [构建 Harness 选型与集成方式](adr/0006-构建Harness选型与集成方式.md)
- [构建环境与依赖基线](20-构建环境与依赖基线.md)
- `experiments/harness/README.md`
- `experiments/build-agent/README.md`
- `app/src/ecom_crawler/builds.py`、`app/src/ecom_crawler/harness/`
