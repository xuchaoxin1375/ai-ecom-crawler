# campsaver.com — S6 挑战站方案包

D01 S6 单站试点。站点：`https://www.campsaver.com/`，市场 US／`en-US`／USD，范围 30 个商品页或 10 分钟；挑战阶段先 5 次目标请求／3 分钟。

本包是 **hybrid**：挑战页抓取用 `resilient-browser-fetch` 的有头晚接入（`chrome-late`），提取用 `run.py` 离线解析已保存 HTML。抓取不当场重跑；已保存页不重复请求。

## 组成

| 路径 | 内容 |
| --- | --- |
| `manifest.yaml` | 方案入口，满足 `docs/08` 必需字段（`status: verified`） |
| `run.py` | 离线提取入口；读 `batch.json` 与已保存 HTML，产出 9 列 CSV |
| `fetch.md` | 挑战页抓取路径：有头晚接入、3–5 标签/批、早读 |
| `category-summary.json` | 分类页总数／卡片数／批大小／目标请求数 |
| `category-product-urls.txt` | 分类页前 30 个商品 URL（按页面顺序） |
| `valid.csv` | 最近一次运行的有效商品，`docs/02` 的 9 列业务字段 |
| `task-result.json` | `docs/09` 的状态、计数、覆盖、质量例外和运行记录 |
| `run-summary.json` | 逐商品审计汇总 |
| `diagnostics/<label>/` | 逐商品审计、排除／失败／待处理清单、批次摘要、分类摘要、运行元数据 |
| `tests/test_contract.py` | JSON-LD（含 strict=False）、价格、描述、breadcrumb、变体、9 列 CSV 单测（不联网） |
| `tools/validate_output.py` | 离线校验 CSV 与任务结果（不联网） |

## 提取运行

```powershell
python experiments/d01/campsaver/run.py `
  --batch-dir /path/to/campsaver-batch-001 `
  --batch-dir /path/to/campsaver-batch-002 `
  --order-file experiments/d01/campsaver/category-product-urls.txt `
  --out-dir experiments/d01/campsaver --label d01-run-001
```

每个 `--batch-dir` 需包含 `batch.json` 和保存的 HTML。默认 `category-summary.json` 提供 144 的分母；运行期不调用 LLM、不启动浏览器、不发网络请求。

校验已发布结果：

```powershell
python experiments/d01/campsaver/tools/validate_output.py `
  --dir experiments/d01/campsaver --expected-products 30
```

抓取路径见 [fetch.md](fetch.md)。

## 本次 S6 试点（`d01-run-005`）

- 1 个商品页字段样本 + 1 个分类页 + 30 个商品页；目标请求 32 次；30／30 有效，0 排除，0 失败。
- 价格 24.89–549.95 USD；30 个描述全部 `complete`；品牌 4 个（Big Agnes、Exped、NEMO Equipment、Therm-a-Rest）。
- 22 个商品有 differential 变体属性（长度／宽度／重量／尺寸／Condition 等，带 `uom`）；8 个无差异选项。
- 6 个商品至少一个 BackOrder offer；24 个全 InStock。
- 覆盖：分类页标题 144 个商品，处理 30 个；`PARTIAL`，不写成全站覆盖。
- 1 页（Therm-a-Rest Luxury Map）JSON-LD 评论正文含未转义换行，`json.loads(..., strict=False)` 才能解析；已加测试。
- 提取最终为 `d01-run-005`；`d01-run-003`／`d01-run-004` 是批次路径可移植化的中间修复，`d01-run-005` 已不含本机绝对路径。

## 方案要点

- **挑战页**：默认无头栈全部停在 PerimeterX 风格挑战；有头晚接入可放行。不要重复 headless 矩阵，不模拟按压、不轮换代理绕过验证。
- **批大小**：默认 3–5 个标签/批；pilot 实际为 3／10／10／7，10 标签批偏大，作为限制保留。
- **早读**：商品页的 Product JSON-LD 服务端渲染；标题变成真实标题、Product JSON-LD 出现即读，不等图片／广告／`networkidle`。
- **价格**：Product JSON-LD `offers[*].price` 取最小正价；InStock 与 BackOrder 都保留；变体不拆行。
- **属性**：`application/json` 的 `variantSelector` 只取 `is_differential=true` 的选项，值带 `uom`；不是所有规格都塞进 `attributes`。
- **描述**：Product JSON-LD description，HTML 白名单清洗；JSON-LD 缺失时用 DOM 描述并记 `fallback`。
- **分类**：最后一个非 Home 面包屑；分类页包含 pad accessories 与品牌子分类。
- **站点边界**：不登录、不加购、不结算、不访问账户／搜索／比较；挑战阶段 5 次目标请求／3 分钟，之后 30 页／10 分钟。

## 边界与限制

- 只取 Sleeping Pads 分类第 1 页的 30 个商品（标题称 144 个）；不是分类全量或全站覆盖。
- 抓取依赖 `resilient-browser-fetch` 的 chrome-late 工具和系统 Chrome；提取本身离线、无浏览器。
- pilot 的 10 标签批超出推荐值；默认配置已改为 3–5。
- 原始 HTML 只在临时目录，未提交仓库；证据是 `valid.csv`、逐商品审计、批次摘要和分类摘要。
- 价格、库存和 BackOrder 日期是抓取时快照；站点结构和风控会变化。
