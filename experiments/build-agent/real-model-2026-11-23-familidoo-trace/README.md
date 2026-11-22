# 构建 Agent 真实站点验证

- 时间：2026-11-22T20:00:57Z
- 站点：`https://www.familidoo.fr/fr/`
- 批次：`b-0b0356e90383`，状态 `DRAFT`
- 构建：`build-d8a95003d2d4`，状态 `FINISHED`，结果 `failed`
- 模型：`{"id": "deepseek-v4.1-flash", "providerID": "opencode-go", "variant": "high"}`
- 出口：`直连`
- 规则：`null`（主机验证未通过，未安装）
- 任务：`-`，状态 `-`，结果 `-`
- 主机验证：0 条有效、3 条失败；`PlanError: invalid CSS selector 'nav.breadcrumb_nav a:not(:first-of-type)'`
- 构建 trace：23 次工具调用、10 条可见消息、17 段 reasoning（本地工作区保留，本目录默认剥离）
- tokens：输入 99,549／输出 5,718／推理 5,888

本目录保留构建摘要、trace（默认不含 reasoning）、工具调用/消息、会话事件和站点详情截图 `ui-build-failed-1280.png`、`ui-build-output-1280.png`（模型输出展开，reasoning 收起）；不保存原始 OpenCode 导出、整页 HTML 或完整文件内容。单次运行不等于全站或长期稳定性结论。

> 2026-11-23 补充：该失败已被构建期静态预检覆盖；`nav.breadcrumb_nav a:not(:first-of-type)` 现在会在联网验证前报出，并默认触发同一会话的自动修复 1 轮。本目录保留原始失败证据，不作为当前行为描述。
