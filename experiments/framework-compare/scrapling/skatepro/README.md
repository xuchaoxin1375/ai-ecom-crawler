# skatepro.es — Scrapling 方案包

预注册框架对比实验（`docs/13`）第 2 轮、S2 站点（`docs/14`）的 Scrapling 实现。
站点：`https://www.skatepro.es/`，市场 ES／`es-ES`／EUR，单站上限 30 个商品页或 10 分钟。

## 组成

| 路径 | 内容 |
| --- | --- |
| `manifest.yaml` | 方案入口，满足 `docs/08` 必需字段（`status: candidate`） |
| `run.py` | 程序入口（`runtime.entrypoint`） |
| `skatepro_scraper/` | HTTP、发现、提取、规范化、导出与运行器 |
| `valid.csv` | 最近一次运行的有效商品，`docs/02` 的 9 列业务字段 |
| `task-result.json` | `docs/09` 的任务结果（state/outcome/stop_reason/counts/coverage/quality_exceptions） |
| `run-summary.json` | 请求、状态码、逐商品审计的汇总 |
| `diagnostics/<label>/` | 按 label 归档的运行证据：事件流、排除／失败／待处理清单、逐商品审计、robots 快照（新运行请换 label，复用会覆盖） |
| `tools/validate_output.py` | 本地校验 CSV 与任务结果契约（不联网） |
| `tests/test_contract.py` | 价格／清洗／选项／CSV／计数不变量单测（不联网） |
| `run-log.md` | 运行记录：命令、时间、复用范围、错误与修复任务 |

## 运行

```bash
python -m uv run --project experiments/framework-compare/scrapling \
  python experiments/framework-compare/scrapling/skatepro/run.py \
  --out-dir experiments/framework-compare/scrapling/skatepro --label run-002
```

默认值：`--max-products 30 --max-seconds 600 --delay 10 --max-attempts 3 --timeout 45`。
运行期不调用任何 LLM，也不需要密钥、Cookie 或浏览器。

## 方案要点

- 发现：入口页主菜单 `c<id>.htm` 分类 → 分类页 `a.product_card` 商品卡（`?page=N` 兜底翻页）→ 按路径去重；`sitemap.xml` 只用于站点级分母。
- 获取：`scrapling.FetcherSession`（curl_cffi，静态 HTML），单会话复用、并发 1、**端到端 10s** 间隔，符合 robots 公布的 `Crawl-delay: 10`。
- 价格：页面内嵌 `PHP2JS` 变体数据 `price_number` 取最低有限正价；`JSON-LD`（`Product`／`ProductGroup`）提供同报价 `priceCurrency` 与回退价格。
- 正文：`#product_description` 正文 + `#product_specifications` 规格表重建为 `<table>`，白名单清洗；`JSON-LD` 描述只作摘要回退；交叉销售、厂家联系方式、评价不进入正文。
- 排除：零价／无价、币种不一致、robots 禁止、无名称；访问与提取失败单列，不混入有效集。

## 边界

- 不登录、不下单、不绕过访问控制；不请求 `*/catalog`、`/adminshop`、`/static`、`*/wishlist`。
- 只覆盖入口主菜单前三个分类构成的发现前沿，30 页是预算而不是全站结论。
- 站点因出口 IP 提示“发货到美国”，页面报价仍为 EUR，`JSON-LD` 的配送／退货政策指向 ES；未设置国家 Cookie，未做汇率换算。
