# experiments

本目录保存实验定义和结论，不保存采集运行产物。

历史实验中的 robots 规则、`Disallow` 和 `Crawl-delay` 记录只说明当时实现或站点事实，不代表当前策略。当前统一策略是机会式探测一次、只保留 `Sitemap:` 行，见 [`docs/22`](../docs/22-网址发现与分页策略.md) 和 [ADR 0013](../docs/adr/0013-robots只探测sitemap行.md)。

## 保留内容

- 各实验的 `README.md`：目的、范围、命令、结果摘要和边界。
- 规则、方案与配置：`*.yaml`、`*.yml`、`context.example.json`、`manifest.example.yaml`。
- 可执行代码：`*.py`、`*.js`、`*.css`、`*.html`、`package.json`、`pyproject.toml`、`uv.lock`。
- 测试和合成 fixture；需要长期保留的小型输入样本放在各自的 `samples/`。

## 不保留内容

采集任务产生的 CSV、结果 JSON、NDJSON、事件流、trace、截图、导出 zip、日志和运行期数据库不放仓库。它们统一放在仓库外的私有证据库：

- 本机默认：`C:\repos\ai-ecom-crawler-evidence`
- 路径与 `experiments/` 一一对应，例如 `experiments/d07/browser-mercerine/tasks/` 对应 `<evidence-root>/experiments/d07/browser-mercerine/tasks/`
- `meta.json` 记录来源仓库、分支和重写前提交；`MANIFEST.sha256` 记录逐文件校验值

换机器时用环境变量 `ECOM_EVIDENCE_ROOT` 指向本机证据库，不要把这些文件复制回仓库。

## 复跑

- 用 `--db` 和 `--out-root` 指向证据库或临时目录，例如 `"$env:ECOM_EVIDENCE_ROOT\experiments\d07\browser-mercerine\tasks"`。
- `experiments/build-agent/run_real_build.py` 的 `--evidence-dir` 也指向证据库。
- 仓库的忽略规则会拦截常见产物；只有明确需要的合成 fixture 才放在 `fixtures/` 下，并保持可提交。

## 目录索引

- `d01/`：D01 试点站点的方案包与构建记录。
- `d03/`～`d08/`：D03～D08 的切片实验、浏览器路径、虚拟列表和界面验收。
- `r04/`、`r06/`：旧流程对照和通用执行器原型；`r06/tests` 是可运行的契约与运行时测试。
- `framework-compare/`：框架对比的探针脚本、规则、样本和结论摘要；运行结果在证据库。
- `build-agent/`：构建 Agent 的纵向切片脚本、规则和说明；trace 与任务结果在证据库。
- `harness/`：构建 harness 的适配与依赖安装冒烟说明。
- `bennytex-full-2026-11-23/`：bennytex 全量目录实验的规则、构建记录和结论；CSV 与结果在证据库。
- `ui-workbench-drafts/`：工作台三窗格布局草稿（A–D），静态 HTML 原型与对比说明，不接后端。
