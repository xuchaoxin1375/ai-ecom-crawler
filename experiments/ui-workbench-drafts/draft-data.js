/* 工作台草稿 · 示例数据与共用渲染工具
   数据为原型示例，字段命名参考 app/frontend-v2/src/lib/api.ts。 */
(function () {
  const sites = {
    "bennytex.com": {
      key: "bennytex.com",
      domain: "bennytex.com",
      batchId: "b-bennytex",
      state: "RUNNING",
      taskId: "web-62d05ef69afc",
      rule: "2026.11.26-2",
      processed: 1284,
      total: 2333,
      valid: 1201,
      failed: 4,
      pending: 1045,
      inFlight: 8,
      speed: "3.4 件/秒",
      elapsed: "00:42:18",
      updated: "08:42:16",
      note: "产品描述多选项卡有选择地采集",
      logs: [
        ["08:41:38", "INFO", "开始任务 web-62d05ef69afc，入口 https://www.bennytex.com/fr/"],
        ["08:41:39", "INFO", "入口页 200，发现 24 个分类链接"],
        ["08:41:41", "INFO", "分类 /fr/mercerie：第 1 页解析到 24 个商品候选"],
        ["08:41:43", "INFO", "商品 /fr/mercerie/lin-... 解析成功（名称、价格、币种、主图、描述）"],
        ["08:41:45", "INFO", "写入 12 件商品，累计 1,172"],
        ["08:41:48", "WARN", "429 Too Many Requests，bennytex.com 冷却 2.0s（Retry-After: 2）"],
        ["08:41:50", "INFO", "恢复请求，域名 RPS 3.4"],
        ["08:41:52", "INFO", "分类 /fr/mercerie：第 2 页解析到 24 个商品候选"],
        ["08:41:55", "ERROR", "永久失败：价格缺失（/fr/mercerie/old-...），不重试"],
        ["08:41:58", "INFO", "商品描述 268 字符，达到阈值 180"],
        ["08:42:01", "INFO", "写入 12 件商品，累计 1,196"],
        ["08:42:03", "WARN", "429 Too Many Requests，bennytex.com 冷却 1.6s（Retry-After: 2）"],
        ["08:42:05", "INFO", "恢复请求，域名 RPS 3.2"],
        ["08:42:08", "INFO", "分类 /fr/mercerie：第 3 页解析到 24 个商品候选"],
        ["08:42:10", "INFO", "进度 1,284 / 2,333（55.1%），有效 1,201，失败 4，队列 1,045"],
        ["08:42:11", "INFO", "校验：价格 1,201 / 币种 1,201 / 主图 1,199"],
      ],
    },
    "mercerie-stole.com": {
      key: "mercerie-stole.com",
      domain: "mercerie-stole.com",
      batchId: "b-bennytex",
      state: "RUNNING",
      taskId: "web-18c2a47d9e01",
      rule: "2026.11.26-2",
      processed: 622,
      total: 1450,
      valid: 601,
      failed: 2,
      pending: 828,
      inFlight: 5,
      speed: "2.6 件/秒",
      elapsed: "00:18:44",
      updated: "08:42:16",
      note: "sitemap 直采，描述阈值 180",
      logs: [
        ["08:41:20", "INFO", "开始任务 web-18c2a47d9e01，入口 https://www.mercerie-stole.com/"],
        ["08:41:22", "INFO", "入口页 200，sitemap 提供 1,450 个商品 URL"],
        ["08:41:26", "INFO", "发现 1,450 个商品候选，开始按 RPS 3 采集"],
        ["08:41:39", "INFO", "商品 /produit/... 解析成功（名称、价格、EUR、主图）"],
        ["08:41:44", "INFO", "写入 10 件商品，累计 540"],
        ["08:41:58", "WARN", "描述 96 字符，低于阈值 180，保留部分描述"],
        ["08:42:02", "INFO", "写入 10 件商品，累计 601"],
        ["08:42:11", "ERROR", "永久失败：主图 404（.../old.jpg）"],
        ["08:42:16", "INFO", "进度 622 / 1,450（42.9%），有效 601，失败 2，队列 828"],
      ],
    },
    "ecolaines.fr": {
      key: "ecolaines.fr",
      domain: "ecolaines.fr",
      batchId: "b-20260107",
      state: "RUNNING",
      taskId: "web-9d1f3c8b7a22",
      rule: "2026.11.26-4",
      processed: 316,
      total: 860,
      valid: 301,
      failed: 2,
      pending: 544,
      inFlight: 3,
      speed: "1.9 件/秒",
      elapsed: "00:09:12",
      updated: "08:42:14",
      note: "JSON-LD 价格回退",
      logs: [
        ["08:41:31", "INFO", "开始任务 web-9d1f3c8b7a22，入口 https://www.ecolaines.fr/"],
        ["08:41:32", "INFO", "分类 /collections/ecolaines 解析到 18 个商品候选"],
        ["08:41:35", "INFO", "商品 /products/... 解析成功"],
        ["08:41:37", "WARN", "价格缺失，尝试 JSON-LD 回退"],
        ["08:41:38", "INFO", "JSON-LD 回退成功，价格 12.90 EUR"],
        ["08:41:41", "INFO", "写入 6 件商品，累计 310"],
        ["08:41:52", "INFO", "进度 316 / 860（36.7%），有效 301，失败 2，队列 544"],
      ],
    },
    "gasparde.fr": {
      key: "gasparde.fr",
      domain: "gasparde.fr",
      batchId: "b-bennytex",
      state: "PAUSED",
      taskId: "web-5ca824167a16",
      rule: "2026.11.24-4",
      processed: 4,
      total: 980,
      valid: 4,
      failed: 0,
      pending: 976,
      inFlight: 0,
      speed: "—",
      elapsed: "00:00:10",
      updated: "08:31:21",
      note: "sitemap 上限与站点 429 待复核",
      logs: [
        ["08:31:10", "INFO", "开始任务 web-5ca824167a16，入口 https://www.gasparde.fr/"],
        ["08:31:12", "INFO", "入口页 200，发现 6 个分类链接"],
        ["08:31:18", "INFO", "写入 4 件商品，累计 4"],
        ["08:31:20", "INFO", "用户请求暂停，当前商品处理完成后停止"],
        ["08:31:21", "INFO", "任务已暂停；恢复后从队列继续"],
      ],
    },
    "bubutissus.fr": {
      key: "bubutissus.fr",
      domain: "bubutissus.fr",
      batchId: "b-bennytex",
      state: "FINISHED",
      outcome: "PARTIAL",
      taskId: "web-62d05ef69afc",
      rule: "2026.11.27-1",
      processed: 5003,
      total: 5003,
      valid: 4924,
      failed: 79,
      pending: 0,
      inFlight: 0,
      speed: "1.8 件/秒",
      elapsed: "46:06",
      updated: "08:12:44",
      note: "4,999 个 sitemap URL 100% 尝试",
      logs: [
        ["08:00:01", "INFO", "开始任务 web-62d05ef69afc，入口 https://www.bubutissus.fr/"],
        ["08:00:03", "INFO", "sitemap 提供 4,999 个商品 URL"],
        ["08:00:05", "INFO", "发现 5,003 个商品候选，开始按 RPS 4 / 并发 4 采集"],
        ["08:21:16", "WARN", "描述 112 字符，低于阈值 180，保留部分描述"],
        ["08:38:42", "INFO", "已处理 4,500 件，有效 4,431，失败 69"],
        ["08:46:07", "INFO", "任务结束：PARTIAL / BUDGET_EXHAUSTED"],
        ["08:46:07", "INFO", "处理 5,003 件，有效 4,924，永久失败 79，0 个 429 事件"],
      ],
    },
    "tissus.net": {
      key: "tissus.net",
      domain: "tissus.net",
      batchId: "b-bennytex",
      state: "QUEUED",
      taskId: "web-7f3b9c2d10aa",
      rule: "2026.11.26-2",
      processed: 0,
      total: 1200,
      valid: 0,
      failed: 0,
      pending: 1200,
      inFlight: 0,
      speed: "—",
      elapsed: "—",
      updated: "08:42:00",
      note: "尚未做速率样本",
      logs: [
        ["08:42:00", "INFO", "任务已入队（web-7f3b9c2d10aa），等待采集槽位"],
        ["08:42:00", "INFO", "当前并发 2 / 2 已占用：bennytex.com、mercerie-stole.com"],
      ],
    },
    "tissusdurenard.fr": {
      key: "tissusdurenard.fr",
      domain: "tissusdurenard.fr",
      batchId: "b-bennytex",
      state: "FINISHED",
      outcome: "FAILED",
      taskId: "web-3b8e5a1f0c44",
      rule: "2026.11.26-2",
      processed: 0,
      total: 640,
      valid: 0,
      failed: 0,
      pending: 640,
      inFlight: 0,
      speed: "—",
      elapsed: "00:00:03",
      updated: "08:15:05",
      note: "入口 403，待补齐访问路径",
      logs: [
        ["08:15:02", "INFO", "开始任务 web-3b8e5a1f0c44，入口 https://www.tissusdurenard.fr/"],
        ["08:15:04", "ERROR", "入口页返回 403（ACCESS_DENIED）"],
        ["08:15:04", "INFO", "按规则停止：站点拒绝访问"],
        ["08:15:05", "INFO", "任务结束：FAILED / ACCESS_DENIED，0 件有效商品"],
      ],
    },
    "tisseo.fr": {
      key: "tisseo.fr",
      domain: "tisseo.fr",
      batchId: "b-bennytex",
      state: "READY",
      taskId: null,
      rule: "2026.11.26-2",
      processed: 0,
      total: 0,
      valid: 0,
      failed: 0,
      pending: 0,
      inFlight: 0,
      speed: "—",
      elapsed: "—",
      updated: "08:30:00",
      note: "规则已激活，尚未启动",
      logs: [],
    },
    "lylianne.com": {
      key: "lylianne.com",
      domain: "lylianne.com",
      batchId: "b-bennytex",
      state: "READY",
      taskId: null,
      rule: "2026.11.26-2",
      processed: 0,
      total: 0,
      valid: 0,
      failed: 0,
      pending: 0,
      inFlight: 0,
      speed: "—",
      elapsed: "—",
      updated: "08:30:00",
      note: "规则已激活，尚未启动",
      logs: [],
    },
    "zephyrtissus.fr": {
      key: "zephyrtissus.fr",
      domain: "zephyrtissus.fr",
      batchId: "b-20260107",
      state: "QUEUED",
      taskId: "web-2c7d9e4a11bb",
      rule: "2026.11.26-4",
      processed: 0,
      total: 420,
      valid: 0,
      failed: 0,
      pending: 420,
      inFlight: 0,
      speed: "—",
      elapsed: "—",
      updated: "08:42:00",
      note: "等待采集槽位",
      logs: [
        ["08:42:00", "INFO", "任务已入队（web-2c7d9e4a11bb），等待采集槽位"],
      ],
    },
    "espacesoiture.fr": {
      key: "espacesoiture.fr",
      domain: "espacesoiture.fr",
      batchId: "b-20260107",
      state: "FINISHED",
      outcome: "COMPLETED",
      taskId: "web-4a1c8b2e9d33",
      rule: "2026.11.26-4",
      processed: 2824,
      total: 2824,
      valid: 2790,
      failed: 34,
      pending: 0,
      inFlight: 0,
      speed: "2.2 件/秒",
      elapsed: "21:18",
      updated: "07:58:20",
      note: "目录 12 页，全部完成",
      logs: [
        ["07:36:59", "INFO", "开始任务 web-4a1c8b2e9d33，入口 https://www.espacesoiture.fr/"],
        ["07:58:20", "INFO", "任务结束：COMPLETED / NATURAL_END，有效 2,790，失败 34"],
      ],
    },
    "madeintissus.fr": {
      key: "madeintissus.fr",
      domain: "madeintissus.fr",
      batchId: "b-20260107",
      state: "FINISHED",
      outcome: "COMPLETED",
      taskId: "web-8e2f6a3c5b77",
      rule: "2026.11.26-4",
      processed: 1902,
      total: 1902,
      valid: 1902,
      failed: 0,
      pending: 0,
      inFlight: 0,
      speed: "2.0 件/秒",
      elapsed: "15:48",
      updated: "07:52:41",
      note: "0 失败，描述全部达标",
      logs: [
        ["07:36:53", "INFO", "开始任务 web-8e2f6a3c5b77，入口 https://www.madeintissus.fr/"],
        ["07:52:41", "INFO", "任务结束：COMPLETED / NATURAL_END，有效 1,902，0 失败"],
      ],
    },
    "premierangling.com": {
      key: "premierangling.com",
      domain: "premierangling.com",
      batchId: "b-premier",
      state: "FINISHED",
      outcome: "COMPLETED",
      taskId: "web-3eca29772041",
      rule: "2026.11.26-1",
      processed: 10,
      total: 10,
      valid: 10,
      failed: 0,
      pending: 0,
      inFlight: 0,
      speed: "0.2 件/秒",
      elapsed: "00:51",
      updated: "07:30:18",
      note: "10/10，名称、价格、币种与主图正确",
      logs: [
        ["07:29:27", "INFO", "开始任务 web-3eca29772041，入口 https://www.premierangling.com/"],
        ["07:30:18", "INFO", "任务结束：COMPLETED / NATURAL_END，有效 10，0 失败"],
      ],
    },
    "partsfornissans.com": {
      key: "partsfornissans.com",
      domain: "partsfornissans.com",
      batchId: "b-parts",
      state: "FINISHED",
      outcome: "PARTIAL",
      taskId: "web-7caf7a123279",
      rule: "2026.11.26-1",
      processed: 10,
      total: 10,
      valid: 9,
      failed: 1,
      pending: 0,
      inFlight: 0,
      speed: "0.3 件/秒",
      elapsed: "10:12",
      updated: "06:58:04",
      note: "stealth 冷启动较慢，1 件永久失败",
      logs: [
        ["06:47:52", "INFO", "开始任务 web-7caf7a123279，入口 https://www.partsfornissans.com/"],
        ["06:58:04", "INFO", "任务结束：PARTIAL / NATURAL_END，有效 9，失败 1"],
      ],
    },
    "babybubblestore.com": {
      key: "babybubblestore.com",
      domain: "babybubblestore.com",
      batchId: "b-baby",
      state: "FINISHED",
      outcome: "COMPLETED",
      taskId: "web-03bd380bf2f4",
      rule: "2026.11.26-1",
      processed: 10,
      total: 10,
      valid: 10,
      failed: 0,
      pending: 0,
      inFlight: 0,
      speed: "0.4 件/秒",
      elapsed: "00:28",
      updated: "06:40:12",
      note: "shopify_json 直采，未抓商品页",
      logs: [
        ["06:39:44", "INFO", "开始任务 web-03bd380bf2f4，入口 https://www.babybubblestore.com/"],
        ["06:39:45", "INFO", "/products.json 200，枚举 250 个商品"],
        ["06:40:12", "INFO", "任务结束：COMPLETED / NATURAL_END，有效 10，0 失败"],
      ],
    },
    "stragier.com": {
      key: "stragier.com",
      domain: "stragier.com",
      batchId: "b-stragier",
      state: "FINISHED",
      outcome: "COMPLETED",
      taskId: "web-6b4d2f8a1c99",
      rule: "2026.11.25-2",
      processed: 10,
      total: 10,
      valid: 10,
      failed: 0,
      pending: 0,
      inFlight: 0,
      speed: "0.2 件/秒",
      elapsed: "01:02",
      updated: "06:20:55",
      note: "PASSED，1 轮修复后通过",
      logs: [
        ["06:19:53", "INFO", "开始任务 web-6b4d2f8a1c99，入口 https://www.stragier.com/"],
        ["06:20:55", "INFO", "任务结束：COMPLETED / NATURAL_END，有效 10，0 失败"],
      ],
    },
  };

  const batches = [
    {
      id: "b-bennytex",
      name: "bennytex 全量",
      folderId: "f-fr-textile",
      country: "FR",
      category: "纺织",
      siteKeys: [
        "bennytex.com",
        "mercerie-stole.com",
        "gasparde.fr",
        "bubutissus.fr",
        "tissus.net",
        "tissusdurenard.fr",
        "tisseo.fr",
        "lylianne.com",
      ],
      running: 2,
      queued: 1,
      finished: 1,
      failed: 1,
      ready: 3,
      valid: 6125,
    },
    {
      id: "b-20260107",
      name: "20260107",
      folderId: "f-fr-textile",
      country: "FR",
      category: "纺织",
      siteKeys: [
        "ecolaines.fr",
        "zephyrtissus.fr",
        "espacesoiture.fr",
        "madeintissus.fr",
      ],
      running: 1,
      queued: 1,
      finished: 2,
      failed: 0,
      ready: 0,
      valid: 4993,
    },
    {
      id: "b-bubutissus",
      name: "bubutissus 全量",
      folderId: "f-fr-textile",
      country: "FR",
      category: "纺织",
      siteKeys: ["bubutissus.fr"],
      running: 0,
      queued: 0,
      finished: 1,
      failed: 0,
      ready: 0,
      valid: 4924,
    },
    {
      id: "b-premier",
      name: "premierangling 试点",
      folderId: "f-uk-tackle",
      country: "GB",
      category: "钓具",
      siteKeys: ["premierangling.com"],
      running: 0,
      queued: 0,
      finished: 1,
      failed: 0,
      ready: 0,
      valid: 10,
    },
    {
      id: "b-parts",
      name: "partsfornissans 全量",
      folderId: "f-uk-tackle",
      country: "US",
      category: "汽车配件",
      siteKeys: ["partsfornissans.com"],
      running: 0,
      queued: 0,
      finished: 1,
      failed: 0,
      ready: 0,
      valid: 9,
    },
    {
      id: "b-baby",
      name: "babybubblestore 试点",
      folderId: null,
      country: "FR",
      category: "婴童",
      siteKeys: ["babybubblestore.com"],
      running: 0,
      queued: 0,
      finished: 1,
      failed: 0,
      ready: 0,
      valid: 10,
    },
    {
      id: "b-stragier",
      name: "stragier 试点",
      folderId: null,
      country: "FR",
      category: "纺织",
      siteKeys: ["stragier.com"],
      running: 0,
      queued: 0,
      finished: 1,
      failed: 0,
      ready: 0,
      valid: 10,
    },
  ];

  const folders = [
    {
      id: "f-fr-textile",
      name: "法国 / 纺织",
      batchIds: ["b-bennytex", "b-20260107", "b-bubutissus"],
    },
    {
      id: "f-uk-tackle",
      name: "英国 / 钓具",
      batchIds: ["b-premier", "b-parts"],
    },
  ];

  const stateLabels = {
    RUNNING: "运行中",
    QUEUED: "排队中",
    PAUSED: "已暂停",
    FINISHED: "已完成",
    CANCELLED: "已取消",
    FAILED: "失败",
    READY: "未开始",
  };

  function fmt(value) {
    return Number(value || 0).toLocaleString("en-US");
  }

  function pct(site) {
    if (!site.total) return 0;
    return Math.min(100, Math.round((site.processed / site.total) * 1000) / 10);
  }

  function stateMeta(site) {
    let label = stateLabels[site.state] || site.state;
    let tone = "neutral";
    if (site.state === "RUNNING") tone = "info";
    else if (site.state === "QUEUED" || site.state === "PAUSED") tone = "warning";
    else if (site.state === "READY") tone = "neutral";
    else if (site.state === "CANCELLED") tone = "neutral";
    else if (site.state === "FINISHED") {
      if (site.outcome === "PARTIAL") {
        label = "部分完成";
        tone = "warning";
      } else if (site.outcome === "FAILED") {
        label = "失败";
        tone = "danger";
      } else if (site.outcome === "CANCELLED") {
        label = "已取消";
        tone = "neutral";
      } else {
        label = "已完成";
        tone = "success";
      }
    } else if (site.state === "FAILED") {
      tone = "danger";
    }
    return { label, tone };
  }

  function progressTone(site) {
    if (site.state === "RUNNING") return "";
    if (site.state === "PAUSED" || site.state === "QUEUED") return "warning";
    if (site.state === "CANCELLED") return "warning";
    if (site.state === "FINISHED") {
      if (site.outcome === "PARTIAL") return "warning";
      if (site.outcome === "FAILED") return "danger";
      if (site.outcome === "CANCELLED") return "warning";
      return "success";
    }
    if (site.state === "FAILED") return "danger";
    return "";
  }

  function badge(site) {
    const meta = stateMeta(site);
    return `<span class="badge ${meta.tone}"><span class="dot"></span>${meta.label}</span>`;
  }

  function progressBar(site, live) {
    const percent = pct(site);
    return `<div class="progress-cell">
      <div class="progress ${progressTone(site)}" role="img" aria-label="进度 ${percent}%"><span style="width:${percent}%"${live ? ' data-live-bar="' + site.key + '"' : ""}></span></div>
      <div class="progress-meta">
        <span><b data-live-processed="${site.key}">${fmt(site.processed)}</b> / ${fmt(site.total)}</span>
        <span data-live-percent="${site.key}">${percent}%</span>
      </div>
    </div>`;
  }

  function rowLogKey(site) {
    return site.key;
  }

  function timeNow() {
    return new Date().toLocaleTimeString("zh-CN", { hour12: false });
  }

  function logLine(entry) {
    const [time, level, message] = entry;
    const cls = level === "ERROR" ? "error" : level === "WARN" ? "warn" : "";
    const levelCls = level.toLowerCase();
    return `<div class="log-line ${cls}"><span class="log-time">${time}</span><span class="log-level ${levelCls}">${level}</span><span class="log-msg">${message}</span></div>`;
  }

  function renderLog(container, site, limit) {
    if (!container) return;
    if (!site) {
      container.innerHTML =
        '<div class="log-empty"><svg class="icon lg"><use href="#i-terminal"/></svg><span>选择一个站点或任务查看运行日志</span></div>';
      return;
    }
    const entries = site.logs || [];
    if (!entries.length) {
      container.innerHTML =
        '<div class="log-empty"><svg class="icon lg"><use href="#i-terminal"/></svg><span>该站点尚无任务，启动后可在这里查看运行日志</span></div>';
      return;
    }
    const list = limit ? entries.slice(-limit) : entries;
    container.innerHTML = list.map(logLine).join("");
    container.scrollTop = container.scrollHeight;
  }

  function appendLog(container, entry) {
    if (!container) return;
    const empty = container.querySelector(".log-empty");
    if (empty) empty.remove();
    container.insertAdjacentHTML("beforeend", logLine(entry));
    container.scrollTop = container.scrollHeight;
  }

  function batchById(id) {
    return batches.find((batch) => batch.id === id);
  }

  function sitesOfBatch(batchId) {
    const batch = batchById(batchId);
    return batch ? batch.siteKeys.map((key) => sites[key]) : [];
  }

  function batchTotals(batch) {
    const list = batch.siteKeys.map((key) => sites[key]);
    return {
      running: list.filter((site) => site.state === "RUNNING").length,
      queued: list.filter((site) => site.state === "QUEUED").length,
      paused: list.filter((site) => site.state === "PAUSED").length,
      finished: list.filter((site) => site.state === "FINISHED").length,
      failed: list.filter((site) => site.outcome === "FAILED").length,
      ready: list.filter((site) => site.state === "READY").length,
      valid: list.reduce((sum, site) => sum + site.valid, 0),
      processed: list.reduce((sum, site) => sum + site.processed, 0),
      total: list.reduce((sum, site) => sum + site.total, 0),
    };
  }

  window.MOCK = {
    sites,
    batches,
    folders,
    stateLabels,
    batchTotals,
    sitesOfBatch,
    batchById,
  };
  window.UI = {
    fmt,
    pct,
    stateMeta,
    progressTone,
    badge,
    progressBar,
    renderLog,
    appendLog,
    logLine,
    timeNow,
    rowLogKey,
  };
})();
