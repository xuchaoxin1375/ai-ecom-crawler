import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="rounded-panel border border-line bg-surface px-6 py-12">
      <p className="text-sm font-semibold text-ink">页面不存在</p>
      <p className="mt-1 text-sm text-ink-3">
        当前 v2 试点覆盖批次列表和批次详情，其他页面仍由旧版工作台处理。
      </p>
      <Link
        className="mt-4 inline-flex h-9 items-center rounded-control bg-accent px-4 text-sm font-medium text-white hover:bg-accent-hover"
        to="/batches"
      >
        返回批次列表
      </Link>
    </div>
  );
}
