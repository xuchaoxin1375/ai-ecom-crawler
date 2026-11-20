# campsaver 抓取路径（chrome-late）

本方案是 hybrid：抓取用 `resilient-browser-fetch` 的有头晚接入，提取用 `run.py` 离线解析。S6 的挑战页默认无头栈不可采，不要重复 headless 矩阵。

## 前置

- Windows 或带图形会话的 Linux（本 pilot 为 Windows）。
- 系统 Chrome/Chromium/Edge。
- `resilient-browser-fetch` 的 `scripts/resilient_fetch.py`、`scripts/example_late_batch.py`。
- Scrapling venv 或带 `playwright`/`patchright` 的 Python 环境。

## 挑战阶段（≤5 次目标请求／3 分钟）

先取 1 个商品页做字段样本，再取分类页；不要先跑 sitemap 或搜索页。

```powershell
$py = 'experiments/framework-compare/scrapling/.venv/Scripts/python.exe'
$skill = '/path/to/resilient-browser-fetch/scripts'

& $py -X utf8 "$skill\resilient_fetch.py" `
  --url 'https://www.campsaver.com/thermarest-neoair-xtherm-nxt-max-sleeping-pad.html' `
  --out "$env:TEMP\campsaver-sample.html" `
  --engine chrome-late --expect-text 'NeoAir' `
  --settle-ms 3000 --render-timeout-ms 8000 --timeout-ms 90000 --wall-timeout-ms 180000 `
  --profile-dir "$env:TEMP\campsaver-profile" --verbose

& $py -X utf8 "$skill\resilient_fetch.py" `
  --url 'https://www.campsaver.com/sleeping-pads.html' `
  --out "$env:TEMP\campsaver-category.html" `
  --engine chrome-late --expect-text 'Sleeping Pads' `
  --settle-ms 3000 --render-timeout-ms 8000 --timeout-ms 90000 --wall-timeout-ms 180000 `
  --profile-dir "$env:TEMP\campsaver-profile" --verbose
```

分类页商品链接：`div.gtmProduct a.grid__link`；页面标题给出 144 个商品，第一页 72 张卡片，取前 30 个。

## 商品页批次（30 页／10 分钟）

**默认每批 3–5 个标签**，不要一次开 10 个以上。每批之间冷却约 2 秒。晚接入脚本会先让挑战自然跑完，再接入读取；不要模拟按压、不要轮换代理绕过验证。

```powershell
& $py -X utf8 "$skill\example_late_batch.py" `
  --url 'https://www.campsaver.com/big-agnes-twistercane-bio-foam-sleeping-pad.html' `
  --url 'https://www.campsaver.com/big-agnes-twistercane-bio-foam-hiking-seat.html' `
  --url 'https://www.campsaver.com/nemo-equipment-tensor-extreme-conditions-sleeping-pad.html' `
  --url 'https://www.campsaver.com/big-agnes-rapide-sl-insulated-tent-tapered-floor-pad.html' `
  --out-dir "$env:TEMP\campsaver-batch-001" `
  --allow-direct --settle-ms 3000 --render-timeout-ms 8000 --timeout-ms 120000
```

重复上面命令，每批 4 个 URL，直到 30 个商品页。`batch.json` 的 `state` 必须是 `content`；`challenge`／`blocked` 的页不进入有效集。

## 早读与提取

- 商品页的 Product JSON-LD 是服务端渲染的，挑战放行后即可读取；不需要等图片、广告、视频或 `networkidle`。
- 本 pilot 的 `example_late_batch.py` 仍会等标题变化和 DOM 稳定；自定义早读器可以在 `document.querySelector('script[type="application/ld+json"]')` 出现 Product 后立即读 `page.content()`。
- 提取只读 Product JSON-LD 与 breadcrumb；描述、价格、品牌、图都来自 JSON-LD。
- JSON-LD 可能含未转义换行（评论正文），用 `json.loads(raw, strict=False)`；`strict=True` 会整块失败。
- 价格取 `offers[*].price` 的最小正价；InStock 与 BackOrder 都保留；变体不拆行，`attributes` 只列 differential 选项并带 `uom`。

## 已知边界

- pilot 实际用了 3／10／10／7 个标签的批次；10 标签批偏大，只作为已发生的证据，不作为推荐。
- 30／144 是分类页第 1 页样本，不是全站或分类全量。
- 商品页包含 pad accessories 与品牌子分类；`category` 取最后一个非 Home 面包屑。
- 价格、库存和 BackOrder 日期是抓取时快照；未登录、未加购、未结算。
