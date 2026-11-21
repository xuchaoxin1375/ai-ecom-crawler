# 基准站 URL 分页证据：ecolaines.com（2026-11-21）

## 目的

验证基准站里的“滚动/点击加载更多，但地址栏同步更新页码”的情况。重点不是模拟滚动，而是确认**下一页是否可以直接用 URL 取得**；如果可以直接取得，就用 `page_param` 或 `next_link`，把浏览器交互降为可选。

## 站点行为

`https://www.ecolaines.com/` 是法国布料/毛线/手工站，分类页 `https://www.ecolaines.com/3-laine` 使用 PrestaShop 的 `kiwik infinite scroll` 模块。页面内联配置给出了：

```text
kiwik.infinitescroll.DEFAULT_PAGE_PARAMETER = "page";
kiwik.infinitescroll.LIST_SELECTOR = "#products";
kiwik.infinitescroll.ITEM_SELECTOR = "article";
kiwik.infinitescroll.LABEL_LOADMORE = "Charger plus de produits";
kiwik.infinitescroll.CURRENT_PAGE = 1;
```

分类页首屏返回 20 个商品；滚动到底部时模块通过 AJAX 追加下一批，并把地址栏更新为 `?page=2`。直接请求：

- `https://www.ecolaines.com/3-laine` → 第 1 页；
- `https://www.ecolaines.com/3-laine?page=2` → 第 2 页（标题带 `(2)`）；
- `https://www.ecolaines.com/3-laine?page=3` → 第 3 页（标题带 `(3)`）。

因此不需要点击或滚动也能遍历分页。

## 规则与结果

规则：`rule.yaml`，`page_param`、`param: page`、`max_pages: 2`、静态 fetcher（`default_engine: static`）。

任务 `ecolaines-url-001`：

| 项 | 结果 |
| --- | --- |
| 状态 | `FINISHED` / `COMPLETED` |
| 有效商品 | 20 / 20 |
| 排除 / 失败 | 0 / 0 |
| 浏览器 | 未启动（`access.browser_launched=false`） |
| 墙钟 | 约 36 秒（15:22:34–15:23:15，1 rps） |
| 分页 | 第 1 页 20 条，`next` 为 `?page=2`；达到 20 后停止 |
| 字段 | 名称 `h1[itemprop=name]`、价格/币种 meta、`og:image`、`#description`、canonical |

商品价格按站点 `product:price:amount` 取（示例 41.4167 EUR）；规则标为 `EXCLUSIVE`。这是页面当前口径，不是税务审计。

## 对照

同一类模式在两个公开练习页上的对照：

| 路径 | 引擎 | 结果 | 墙钟 |
| --- | --- | --- | --- |
| `scrapingcourse.com/infinite-url` + `?page=2` | static `page_param` | 15 / 15 | 约 31 秒 |
| `scrapingcourse.com/button-click` | browser `load_more` | 15 / 15 | 约 84 秒 |
| `scrapingcourse.com/infinite-scrolling` | browser `infinite_scroll` | 15 / 15 | 约 88 秒 |

这不是严格的同站同条件实验，但方向明确：URL 可直接取页时，优先 `page_param`/`next_link`；交互只在 URL 不可寻址、直接打开返回首屏/空壳、或内容依赖虚拟列表时才需要。浏览器推进结果会在 `advance` 统计里记录 `start_url`、`final_url`、`url_changes` 和 `urls`，便于发现可切换的页码模式。

## 复跑

```powershell
python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/ecolaines-url/rule.yaml `
  --db experiments/d07/ecolaines-url/tasks.db `
  --out-root experiments/d07/ecolaines-url/tasks `
  --task-id ecolaines-url-002 `
  --task-type product --max-products 20 --max-seconds 180 --max-attempts 2 --per-domain-rps 1
```

用新任务 ID，避免覆盖已有诊断。运行期 `tasks.db` 不入库。

## 边界

- 只看 `3-laine` 分类前 2 页、20 个商品；不是全站覆盖。
- 站点分页、DOM 和模块配置可能变化；复跑前先确认 `?page=2` 仍返回对应页。
- 价格是站点当前显示口径，未做税价、运费、市场或变体审计。
- 这是基准站的公开只读页面，未登录、未下单。

## 文件

- `rule.yaml`：`page_param` 规则。
- `tasks/ecolaines-url-001/`：20／20 证据。
- 相关对照：`experiments/d07/browser-listing/`。
