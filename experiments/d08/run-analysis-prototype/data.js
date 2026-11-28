// Mock data for the run-analysis prototype.
// Product buckets are aggregated from the real run web-62d05ef69afc
// (05,003 processed / 04,924 valid / 79 failed). Request telemetry is
// intentionally absent: the first version reads only task events and results.

const processed = [
  64, 111, 110, 108, 108, 115, 113, 110, 108, 115, 115, 116, 106, 112, 121, 119,
  112, 111, 114, 91, 105, 109, 110, 103, 105, 105, 108, 109, 109, 105, 108, 107,
  109, 105, 107, 106, 108, 113, 111, 108, 110, 110, 107, 107, 109, 104, 27,
];

const valid = [
  63, 111, 110, 108, 104, 114, 112, 110, 108, 115, 113, 115, 106, 110, 120, 118,
  112, 110, 113, 83, 104, 107, 109, 102, 104, 103, 105, 109, 105, 100, 108, 105,
  107, 105, 107, 105, 99, 112, 109, 108, 99, 107, 107, 105, 107, 104, 27,
];

const failed = [
  1, 0, 0, 0, 4, 1, 1, 0, 0, 0, 2, 1, 0, 2, 1, 1, 0, 1, 1, 8, 1, 2, 1, 1, 1,
  2, 3, 0, 4, 5, 0, 2, 2, 0, 0, 1, 9, 1, 2, 0, 11, 3, 0, 2, 2, 0, 0,
];

const excluded = processed.map(() => 0);

const runningProcessed = processed.slice(0, 32).map((value, index) => {
  const wobble = index % 5 === 0 ? 2 : index % 3 === 0 ? 1 : 0;
  return Math.max(18, Math.round(value * 0.36 + wobble));
});

const runningFailed = runningProcessed.map((_, index) => {
  if (index === 19) return 2;
  if (index === 24) return 1;
  if (index === 29) return 2;
  return index % 11 === 0 ? 1 : 0;
});

const runningValid = runningProcessed.map((value, index) =>
  Math.max(0, value - runningFailed[index]),
);

const failureReasons = [
  {
    code: "validation_error",
    label: "商品数据校验失败",
    failureClass: "permanent",
    count: 78,
    share: 0.9873,
    sampleUrl: "https://www.bubutissus.fr/produit/ref-1042",
  },
  {
    code: "http_404",
    label: "页面不存在",
    failureClass: "permanent",
    count: 1,
    share: 0.0127,
    sampleUrl: "https://www.bubutissus.fr/produit/ref-8891",
  },
];

const baseTask = {
  taskId: "web-62d05ef69afc",
  site: "bubutissus.fr",
  taskType: "product",
  rule: "2026.11.27-1",
  plan: "bubutissus-fr--7994b273fe690121-build",
  market: "FR",
  outcome: "PARTIAL",
};

const finished = {
  ...baseTask,
  state: "FINISHED",
  outcomeLabel: "部分完成",
  start: "2026-11-26T22:07:00Z",
  end: "2026-11-26T22:53:15Z",
  observedAt: "2026-11-26T22:53:15Z",
  runSeconds: 2766,
  processed,
  valid,
  failed,
  excluded,
  counts: {
    discovered: 5011,
    candidates: 5003,
    processed: 5003,
    valid: 4924,
    failed: 79,
    excluded: 0,
    pending: 0,
  },
  coverage: { status: "PARTIAL", label: "声明来源内 100%" },
  budget: {
    maxProducts: null,
    maxSeconds: null,
    maxUrls: null,
    usedProducts: 5003,
    usedSeconds: 2766,
    usedUrls: 5011,
  },
  failureReasons,
  failureClasses: { permanent: 79, transient: 0, blocked: 0 },
  dataQuality: {
    level: "full",
    label: "任务事件 + 终态结果",
    note: "本次运行的事件和终态结果完整，失败原因可到 item 级。",
  },
  diagnostics: [
    {
      tone: "warning",
      title: "失败集中在商品数据校验",
      detail: "79 个失败中 78 个为 validation_error，1 个为 HTTP 404；不是请求层失败。",
      action: "查看失败项",
    },
  ],
};

const running = {
  ...baseTask,
  state: "RUNNING",
  start: "2026-11-26T22:07:00Z",
  end: null,
  observedAt: "2026-11-26T22:39:18Z",
  runSeconds: 1938,
  processed: runningProcessed,
  valid: runningValid,
  failed: runningFailed,
  excluded: runningProcessed.map(() => 0),
  counts: {
    discovered: 5601,
    candidates: 5593,
    processed: 1236,
    valid: 1214,
    failed: 22,
    excluded: 0,
    pending: 4357,
  },
  coverage: { status: "PARTIAL", label: "声明来源内 22.1%" },
  budget: {
    maxProducts: null,
    maxSeconds: 3600,
    maxUrls: null,
    usedProducts: 1236,
    usedSeconds: 1938,
    usedUrls: 5601,
  },
  failureReasons: [
    {
      code: "validation_error",
      label: "商品数据校验失败",
      failureClass: "permanent",
      count: 21,
      share: 0.9545,
      sampleUrl: "https://www.bubutissus.fr/produit/ref-2120",
    },
    {
      code: "http_404",
      label: "页面不存在",
      failureClass: "permanent",
      count: 1,
      share: 0.0455,
      sampleUrl: "https://www.bubutissus.fr/produit/ref-8891",
    },
  ],
  failureClasses: { permanent: 22, transient: 0, blocked: 0 },
  dataQuality: {
    level: "live",
    label: "任务事件实时聚合",
    note: "运行中按事件增量聚合；失败原因可能随后续事件补齐。",
  },
  diagnostics: [
    {
      tone: "info",
      title: "最近 5 分钟仍在稳定产出",
      detail: "最近 5 个闭合时间桶共处理 196 件，平均约 39 件/分钟；待采 4,357 件。",
      action: "查看运行明细",
    },
  ],
};

const legacy = {
  ...finished,
  dataQuality: {
    level: "legacy",
    label: "旧运行 · 仅任务事件",
    note: "旧版本运行只有任务事件和终态结果；失败原因可能只保留到失败类别。",
  },
  diagnostics: [
    {
      tone: "warning",
      title: "失败集中在商品数据校验",
      detail: "79 个失败均记录为永久失败；旧运行没有请求状态和延迟，失败原因可能只保留到类别。",
      action: "查看失败项",
    },
  ],
};

const queued = {
  ...baseTask,
  state: "QUEUED",
  start: null,
  end: null,
  observedAt: "2026-11-26T22:07:00Z",
  runSeconds: 0,
  processed: [],
  valid: [],
  failed: [],
  excluded: [],
  counts: {
    discovered: 0,
    candidates: 0,
    processed: 0,
    valid: 0,
    failed: 0,
    excluded: 0,
    pending: 0,
  },
  coverage: { status: "UNKNOWN", label: "尚未开始" },
  budget: {
    maxProducts: null,
    maxSeconds: null,
    maxUrls: null,
    usedProducts: 0,
    usedSeconds: 0,
    usedUrls: 0,
  },
  failureReasons: [],
  failureClasses: { permanent: 0, transient: 0, blocked: 0 },
  dataQuality: {
    level: "empty",
    label: "尚无数据",
    note: "运行尚未开始。",
  },
  diagnostics: [],
};

export const runs = { finished, running, legacy, queued };
