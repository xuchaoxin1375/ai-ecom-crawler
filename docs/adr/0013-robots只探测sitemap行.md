---
title: robots 只探测 Sitemap 行
document_type: adr
status: accepted
updated: 2026-11-26
---

## 状态与适用范围

**Accepted**（2026-11-23）。本 ADR 取代此前“分析阶段不读整份、生产／构建阶段另行确认”的分用途口径，统一适用于分诊、构建、修复、验证、发现、执行和框架实验等所有阶段。

本 ADR 不改变访问控制、服务条款和当地法律边界；robots 不是访问授权。登录、付费、401／403 等明确拒绝仍按原边界处理，不自动绕过；挑战页和验证码按 [ADR 0022](0022-挑战页处理边界.md) 有界尝试，仍被拒绝就停止。

## 背景

旧口径分成两套：

- 分析阶段禁止读整份 `robots.txt`，只保留 `Sitemap:` 行，不按 robots 拦截。
- 构建预检完整解析 `robots.txt`，disallow 或不可读直接 409；执行器保存全文并按 `can_fetch` 拦截；构建 prompt 要求 agent 读规则并在 disallow 时停止。

这带来三个问题：

- 同一项目里同一份文件有两套相反语义，文档、代码和 agent 行为容易漂移。
- 构建 agent 可能把整份 `robots.txt` 拉进上下文，浪费 token 和时间，偏离“写采集规则”的目标。
- 解析 `Disallow`、`Allow`、`Crawl-delay` 和 UA 组并不产生采集规则所需的发现信息；真正有用的是 `Sitemap:` 声明。

## 决策

所有阶段统一执行以下策略：

- **机会式探测**：对入口同源执行一次 `GET <scheme>://<host>/robots.txt`。每次 discovery、构建、修复、验证和执行都可以尝试；不要求预先声明。
- **失败不阻塞**：404、403、429、5xx、超时、TLS／传输错误、非文本响应都只记录状态和原因，继续常规发现或构建，不中止任务。
- **只保留 Sitemap 行**：仅按行匹配大小写不敏感的 `Sitemap:`，去掉值、去重、最多保留 20 条；相对值按入口同源解析为绝对 URL。
- **其他内容立即丢弃**：不解析、不保存、不写日志、不进入 prompt／trace／任务结果，不据此放行或拒绝请求。
- **不解析规则**：不读取 `User-agent` 组、`Disallow`、`Allow`、`Crawl-delay`，也不按 robots 调整速率。请求速率使用固定保守值（默认并发 1、间隔不少于 1000ms，或规则包更保守的值）。
- **不是停止信号**：robots 内容不得作为构建失败、任务失败或 URL 排除原因；旧的 `robots_disallowed` 排除不再产生。
- **兼容字段忽略**：`fetch.robots`、`sitemap.robots`、`discovery.robots_sitemap` 保留读取兼容，但运行时不再据此决定是否探测；所有 sitemap 来源都会并入本次探测到的 Sitemap URL。
- **Agent 不直接读全文**：host 在构建前完成探测，把 Sitemap URL 注入 brief；构建／修复 agent 不得 `cat`、`Get-Content` 或 `curl` 完整 robots。确需补探时只能使用只输出 `Sitemap:` 行的过滤命令。

## 实施

- 共享解析在 `app/src/ecom_crawler/robots.py`：`robots_url_for()` 和 `extract_sitemaps()`；原型侧在 `experiments/r06/runtime/robots.py`。
- 构建预检 `builds.py` 的 `_probe_robots()` 只返回状态说明和 Sitemap URL，不再返回 allow／deny，也不再抛 409。
- 执行器 `executor/runner.py` 不再保存 `robots.txt`，改为写 `diagnostics/robots_sitemaps.txt`；`task-result.json` 的 `access` 记录 `robots_status`、`robots_sitemaps`、`robots_note` 和 `robots_policy=sitemap_line_only`。
- 发现运行时 `runtime/runner.py` 在任务开始时总是探测一次；sitemap 来源自动并入 Sitemap URL，非 sitemap 来源只把结果写入 `access` 和事件，不自动扩大发现范围。
- 事件使用 `robots_sitemaps_probed`（成功，记录状态和数量）和 `robots_probe_failed`（失败，记录状态或错误），不记录正文。
- 构建 prompt 和 `work/AGENTS.md` 明确“host 已探测、只给 Sitemap URL、不要读全文、不要分析其他规则”。

## 后果

- 构建 agent 不再因 robots 规则消耗上下文或中止构建，规则编写更快。
- 运行时少一次全文落盘和规则解析；robots 只作为发现辅助。
- 失去基于 `Disallow`／`Crawl-delay` 的自动门禁。这是有意的取舍；ToS、法律和访问控制仍由人工与运行时边界独立处理。
- 旧证据中的 `Crawl-delay`、`Disallow` 和 robots 规则摘要只作历史事实，不再代表当前策略。

## 验证与证据

- `app/tests/test_builds.py`：robots 探测提取 Sitemap、disallow 不阻止构建、brief 不含“停止”指令。
- `app/tests/test_control_flow.py`：robots 404 不影响任务。
- `experiments/r06/tests/test_runtime.py`：robots disallow 不阻断发现、只保留 Sitemap 行、未显式开启也会使用 Sitemap 来源。
- 文档同步：`docs/22`、`AGENTS.md`、`docs/17`、`docs/19` 和构建相关说明。

## 替代方案

- **完整解析并拦截**：保留旧构建／执行器门禁。会让项目继续维护两套语义，并可能把全文送进 agent 上下文。
- **只在 sitemap 来源显式开启时探测**：请求更少，但 agent 仍要判断是否开启，且容易漏掉站点已有的 Sitemap 声明。
- **完全不请求 robots**：最省请求，但会丢掉站点主动公布的 Sitemap 入口；不符合“总是尝试并检查 Sitemap 项”的目标。
