# D01 S6 campsaver.com — chrome-late 挑战站试点

## 范围与环境

- 站点：`https://www.campsaver.com/`，S6，US／en-US／USD。
- 范围：`/sleeping-pads.html` 分类页第 1 页，标题为 `TOP 144 Sleeping Pads Products in 2026`；取前 30 个商品页。
- 访问边界：不登录、不加购、不结算、不访问账户／搜索／比较；挑战阶段 5 次目标请求／3 分钟，之后 30 页／10 分钟。
- 框架：`resilient-browser-fetch` 的 `chrome-late`（系统 Chrome，有头晚接入）；提取用 Scrapling venv 的 Python + lxml，离线运行。
- 环境：Windows，Python 3.13.13；直连（`HTTPS_PROXY`／`HTTP_PROXY` 未设置，`NO_PROXY` 已设置）；系统 Chrome。

## 挑战阶段（≤5 次目标请求／3 分钟）

既有证据：默认无头栈（curl、Scrapling StealthyFetcher、Playwright Chromium）都停在 PerimeterX 风格挑战；有头 Playwright 首次能打开首页，随后同出口转为 `PRESS & HOLD`。本轮不重复 headless 矩阵。

| 请求 | 客户端 | 结果 |
| --- | --- | --- |
| 1. 商品字段样本 `thermarest-neoair-xtherm-nxt-max-sleeping-pad.html` | `chrome-late`，直连，持久 profile | 200，741,535 B，`NeoAir` 断言命中；Product JSON-LD 有 2 个 offer |
| 2. 分类页 `sleeping-pads.html` | 同上 | 200，1,109,242 B；标题 144 个商品，第一页 72 张卡片 |
| 3–5. 3 个商品页批量验证 | `example_late_batch.py`，一次启动 3 标签 | 3／3 `content` |

## 商品页批次（30 页）

| 批次 | 标签数 | 结果 |
| --- | ---: | --- |
| `s6-batch-test` | 3 | 3／3 content |
| `s6-batch-002` | 10 | 10／10 content |
| `s6-batch-003` | 10 | 10／10 content |
| `s6-batch-004` | 7 | 7／7 content |

合计 30 个商品页，全部 `content`；加上分类页与字段样本，共 32 次目标请求。

**批大小偏差**：pilot 实际用了 3／10／10／7 个标签；10 标签批偏大，容易增加资源消耗和限流风险。按最新要求，方案默认改为 3–5 个标签/批，并以“真实标题 + Product JSON-LD 出现”为就绪条件，不等图片／广告／networkidle。该偏差作为限制保留，不作为推荐做法。

## 失败与修复

- 1 页（Therm-a-Rest Luxury Map）的 Product JSON-LD 评论正文含未转义换行，`json.loads(..., strict=True)` 报 `Invalid control character`，整块被跳过；改用 `json.loads(..., strict=False)` 后解析成功。已加单测。
- 首次提取的 `attributes` 只写数值、没写单位（如 `Length#72`）；改为带 `uom`（`Length#72 in|78 in`）后重跑。
- 2 个商品页在嵌入 JSON 中显示 `Condition: Open Box, Dealer DMO` 与 `New`，但 JSON-LD 的 `itemCondition` 全部是 `NewCondition`；产品级最低价可能来自 open-box offer，方案保留 `Condition` 属性并记录这一限制。
- 批次路径可移植化：`d01-run-003` 把 `file` 改成 basename 后读不到原文件，0 行；`d01-run-004` 修复读取但 `run-meta.json` 仍含本机绝对路径；`d01-run-005` 同时保留读取用 `source_file`、输出只写文件名／批次名，最终发布。`d01-run-001`～`004` 的诊断只把本机临时路径替换为 `<batch-dir>`，业务字段未改。

## 结果

- 有效 **30**／排除 **0**／失败 **0**；最终提取 `d01-run-005`。
- 价格：24.89–549.95 USD；币种 30／30 USD。
- 品牌：Big Agnes 9、Exped 9、NEMO Equipment 6、Therm-a-Rest 6；无缺品牌。
- 描述：30／30 `complete`，384–3,486 字符；全部来自 Product JSON-LD，HTML 白名单清洗。
- 属性：22 个商品有 differential 变体选项，带长度／宽度／重量／尺寸／Condition 等；8 个无可区分选项。
- 库存：24 个全 InStock；6 个至少一个 BackOrder offer；InStock 与 BackOrder 都保留。
- 分类：Big Agnes Base Camping Pads 8、Exped Sleeping Pads 8、Nemo Base Camping Pads 4、Thermarest Backpacking Pads 3 等；分类页含 pad accessories。
- 覆盖：分类页标题 144 个商品，处理 30 个；`PARTIAL`，不写成全站覆盖。
- `quality_exceptions`：0；必需字段、描述、分类、品牌都齐全。

## 输出校验

```powershell
python experiments/d01/campsaver/tools/validate_output.py `
  --dir experiments/d01/campsaver --expected-products 30
```

结果：`{"rows": 30, "problems": []}`。

## 证据位置

- `valid.csv`、`task-result.json`、`run-summary.json`：`d01-run-005` 发布结果。
- `diagnostics/d01-run-002/`：带 uom 的首次有效提取。
- `diagnostics/d01-run-003/`：批次路径 basename 修复失败的 0 行证据。
- `diagnostics/d01-run-004/`：读取修复但 run-meta 仍含绝对路径。
- `diagnostics/d01-run-005/`：最终逐商品审计、排除／失败清单、批次摘要、分类摘要；不含本机绝对路径。
- `category-product-urls.txt`、`category-summary.json`：分类页前 30 个 URL 与 144 分母。
- `tests/`、`tools/validate_output.py`：离线测试与结果校验。
- 原始 HTML 在临时目录，未提交；可用 `fetch.md` 的路径重建。

## 限制

- 只取 Sleeping Pads 分类第 1 页的 30 个商品（标题称 144 个）；不是分类全量或全站覆盖。
- 抓取依赖 `resilient-browser-fetch` 的 chrome-late 工具和系统 Chrome；提取本身离线。
- pilot 的 10 标签批超出推荐值；默认配置已改为 3–5。
- 变体不拆行；产品级价格是最低公开 offer，未把价格映射到具体 Condition／尺寸。
- 商品页包含 pad accessories 与品牌子分类；分类取最后一个非 Home 面包屑。
- 价格、库存和 BackOrder 日期是抓取时快照；站点结构和风控会变化。
- 单页 chrome-late 约 32.2s、分类页约 32.0s；批量抓取的总墙钟未单独计时，不能据此报全量吞吐。
