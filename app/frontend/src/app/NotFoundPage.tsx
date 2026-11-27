import { Link } from "react-router-dom";

export function NotFoundPage() {
  return (
    <div className="rounded-panel border border-line bg-surface px-6 py-12">
      <p className="text-sm font-semibold text-ink">页面不存在</p>
      <p className="mt-1 text-sm text-ink-3">
        当前版本覆盖批次列表、批次详情和站点详情。请从批次列表继续操作。
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
