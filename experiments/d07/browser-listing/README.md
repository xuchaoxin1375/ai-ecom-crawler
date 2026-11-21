# 浏览器交互推进证据：load_more 与 infinite_scroll（2026-11-21）

## 目的

验证 `app` 运行时的浏览器 adapter 能在列表页执行两种有界推进：

- `load_more`：点击一个“加载更多”按钮，等条目增加后继续发现；
- `infinite_scroll`：滚动页面底部，等条目追加后继续发现。

两个任务都只取前 15 个商品，超出部分不抓；它们证明交互和字段路径，不是全站覆盖。

## 站点与规则

- 站点：`scrapingcourse.com` 的公开练习页，未登录、未下单。
- `rule.yaml`：`load_more`，`#load-more-btn`，点击 1 次，`settle_ms: 2000`；初始 12 张商品卡，点击后追加 10 张。
- `rule-scroll.yaml`：`infinite_scroll`，`mode: scroll`，滚动 2 次，`settle_ms: 2000`；页面用 IntersectionObserver 在底部追加商品。
- 商品页是 WooCommerce，字段从 Product JSON-LD 取；价格是页面显示的 USD 金额。
- 商品链接在无 `www` 域，canonical 在 `www` 域，规则同时允许两个 origin。

## 结果

| 任务 | 推进 | 交互后条目数 | 有效商品 | 墙钟 | 停止 |
| --- | --- | --- | --- | --- | --- |
| `browser-listing-006` | `load_more`，1 次点击 | 24 | 15／15 | 75 秒（15:27:16–15:28:31） | `MAX_STEPS` |
| `browser-listing-007` | `infinite_scroll`，2 次滚动 | 36 | 15／15 | 77 秒（15:28:38–15:29:55） | `MAX_STEPS` |
| `browser-listing-005` | 静态 `page_param`（`?page=2`） | 第 1 页 12 + 第 2 页 | 15／15 | 31 秒（15:16:41–15:17:12） | 达到商品上限 |

前两个任务都是 `FINISHED` / `COMPLETED`，0 排除、0 失败；`products.csv` 均为 9 列，`task-result.json` 里的浏览器 PID 和 profile 已在任务结束后回收。`browser-listing-005` 没有启动浏览器。

列表项结果保留了推进统计，`url_changes` 是给规则作者的信号：

```json
{"type": "load_more", "steps": 1, "items": 24, "stop": "MAX_STEPS", "start_url": "https://.../button-click", "final_url": "https://.../button-click", "url_changes": 0, "urls": []}
{"type": "infinite_scroll", "steps": 2, "items": 36, "stop": "MAX_STEPS", "start_url": "https://.../infinite-scrolling", "final_url": "https://.../infinite-scrolling", "url_changes": 0, "urls": []}
```

这两个页面的 URL 不随交互更新，所以必须点击／滚动；同站的 `infinite-url` 变体则会更新 `?page=N`，直接 URL 取页可由 `page_param` 完成（见 `rule-url.yaml` 和 `browser-listing-005`）。如果 `url_changes > 0`，先验证直接打开是否能取对应页；能取就用 `page_param`／`next_link`。`experiments/d07/ecolaines-url/` 是基准站上的实际对照（无限滚动 + `?page=N`，静态 `page_param` 20／20、约 36 秒、无浏览器）。

`browser-listing-001`／`002`／`003`／`004` 是 schema 或 URL 统计更新前的同规则复跑，行为一致；保留作历史样本。当前证据是 `005`／`006`／`007`。

## 复跑

```powershell
python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/browser-listing/rule.yaml `
  --db experiments/d07/browser-listing/tasks.db `
  --out-root experiments/d07/browser-listing/tasks `
  --task-id browser-listing-008 `
  --task-type product --max-products 15 --max-seconds 240 --max-attempts 2 --per-domain-rps 1

python -m uv run --project app ecom-crawler run `
  --rule experiments/d07/browser-listing/rule-scroll.yaml `
  --db experiments/d07/browser-listing/tasks.db `
  --out-root experiments/d07/browser-listing/tasks `
  --task-id browser-listing-009 `
  --task-type product --max-products 15 --max-seconds 240 --max-attempts 2 --per-domain-rps 1
```

用新任务 ID，避免覆盖已有诊断。运行期 `tasks.db` 和 `browser-profile` 不入库。

## 边界

- 这是公开练习站，不是生产店铺；只有首页列表的有界样本。
- 只支持“追加型”列表：最终 DOM 保留前面条目。虚拟列表只保留最后一批，不能用该实现直接采全量。
- `max_clicks`／`max_scrolls`、`settle_ms` 和 `no_new_stop` 都只是上限与停止信号，不保证站点一定还有更多数据。
- 滚动默认是 window 或指定容器的 `scrollTop`；`mode: wheel` 可用鼠标滚轮，但复杂内部滚动容器仍需单独验证。
- 商品价格按页面显示值取，未做税费、运费或市场价审计。

## 文件

- `rule.yaml`：load_more 规则。
- `rule-scroll.yaml`：infinite_scroll 规则。
- `rule-url.yaml`：同站 `infinite-url` 的静态 `page_param` 对照。
- `tasks/browser-listing-006/`、`tasks/browser-listing-007/`：当前交互证据。
- `tasks/browser-listing-005/`：URL 分页静态对照。
- `tasks/browser-listing-001/`～`004/`：历史样本。
