# 框架对比实验目录

本目录对应[框架对比实验](../../docs/13-框架对比实验.md)的 v1 执行准备，位于分支 `exp/framework-compare`，不合并回 `main`；业务口径仍以 `docs/01`～`09` 为准。

## 当前状态

- 共享任务规格与评分表：已建立。
- 三个框架的独立环境：已建立并完成导入与浏览器启动验证。
- 站点范围、执行顺序与运行：第 1、2 轮（`javaestate.com`、`skatepro.es`）三臂已执行；`sixmoondesigns.com`、`campsaver.com` 只完成补充探针，见 [`probes/`](probes/README.md)，未做正式 D01 轮次。
- 合同变更：2026-11-19 起 `docs/02` 的最终业务CSV为9列；本目录已完成的运行按当时的22列合同记录，保留为旧合同证据，不追溯改写。

## 版本记录

| 项 | 版本／来源 |
| --- | --- |
| Python | 3.13.13（本机 uv 发现） |
| uv | 0.13.9 |
| Scrapling | 0.5.1，`[fetchers]`；curl-cffi 0.17.0、playwright 1.65.2、patchright 1.64.4 |
| Crawlee for Python | 1.11.2，`[playwright,parsel]` |
| Scrapy | 2.20.0 |
| Chromium | 159.0.8154.6（Playwright chromium-1255，含 headless shell） |
| PyPI 源 | `https://mirrors.ustc.edu.cn/pypi/simple` |
| 浏览器源 | `https://cdn.npmmirror.com/binaries/playwright` |

浏览器安装在用户级 `ms-playwright` 缓存，三个环境共用；`scrapling install-deps` 未执行（Windows 不需要）。以上只证明依赖可导入、浏览器可启动，不代表站点可采。

## 目录约定

| 路径 | 用途 |
| --- | --- |
| `shared/` | 任务规格、评分表、站点清单；只放规格，不放任何框架实现 |
| `scrapling/` | Scrapling 独立环境与实现 |
| `crawlee/` | Crawlee for Python 独立环境与实现 |
| `scrapy/` | Scrapy 独立环境与实现 |
| `probes/` | 有界补充探针：公开 JSON 与挑战页；不替代正式轮次 |
| `results/` | 原始指标、日志摘要和结果表；不保存整页原文 |

每个框架目录使用独立虚拟环境和锁文件，不共享实现代码；禁止把某个框架的选择器或脚本复制到另一个目录。

## 环境

Python 由 uv 管理。国内网络可用镜像加速：

```powershell
$env:UV_DEFAULT_INDEX = 'https://mirrors.ustc.edu.cn/pypi/simple'
python -m uv sync --project experiments/framework-compare/scrapling
```

`uv` 未在 PATH 时用 `python -m uv`。浏览器和其他运行时依赖按实际站点需要另行安装，安装前记录版本与来源。

环境在三个框架子目录的 `.venv` 下；用 `check_environment.py --list-envs --project-root .` 或 `inventory.py --project .` 可以发现，使用时也可直接指定 `experiments/framework-compare/<framework>/.venv/Scripts/python.exe`，不要另建同名环境。

## 执行顺序

按 `13` 的随机化要求，开跑前在 `results/order.md` 固定顺序并记录随机种子；同一站点尽量在同一时间窗内完成。所有框架使用同一时间上限、商品页上限、模型和提示词。

## 结果与证据

原始日志、指标和失败记录写入 `results/`，不写业务正文；实验结束后只把结果报告合入 `main`，失败实现归档或删除。

补充探针的代码、CSV 和 JSON 审计在 [`probes/`](probes/README.md)，只记录有界验证，不计入正式轮次。
