import { ShieldAlert } from "lucide-react";
import type { BuildStatus } from "../../lib/api";
import { Button } from "../../components/ui/Button";
import { ErrorNotice } from "../../components/ui/ErrorNotice";
import { permissionItems } from "./build";

interface BuildApprovalsProps {
  build: BuildStatus | null;
  busy: string;
  error?: string;
  onReplyDependency: (requestId: string, decision: "once" | "reject") => void;
  onReplyPermission: (
    requestId: string,
    decision: "once" | "always" | "reject",
  ) => void;
}

export function BuildApprovals({
  build,
  busy,
  error = "",
  onReplyDependency,
  onReplyPermission,
}: BuildApprovalsProps) {
  const dependencies = build?.pending_dependencies ?? [];
  const permissions = permissionItems(build);
  if (!build || (dependencies.length === 0 && permissions.length === 0)) return null;

  const dependencyDetails = new Map(
    (build.pending_dependency_requests ?? []).map((item) => [item.request_id, item]),
  );
  const dependencyInstallerConfigured = build.dependency_installer_configured !== false;

  return (
    <section
      aria-label="构建等待审批"
      className="rounded-panel border border-warning/30 bg-warning-soft px-4 py-4 sm:px-5"
    >
      <div className="flex items-start gap-2.5">
        <ShieldAlert
          className="mt-0.5 shrink-0 text-warning"
          size={16}
          aria-hidden="true"
        />
        <div className="min-w-0">
          <h2 className="text-[15px] leading-6 font-semibold text-warning">
            构建等待审批
          </h2>
          <p className="mt-0.5 text-xs leading-5 text-ink-2">
            构建已暂停在需要人工确认的步骤；处理后会继续同一会话。
          </p>
        </div>
      </div>

      {error ? (
        <div className="mt-3">
          <ErrorNotice title="审批提交失败" message={error} compact />
        </div>
      ) : null}

      <div className="mt-3 space-y-2">
        {dependencies.map((requestId) => {
          const detail = dependencyDetails.get(requestId);
          return (
            <div
              key={requestId}
              className="flex flex-wrap items-center gap-2 rounded-control border border-warning/25 bg-surface px-3 py-2 text-xs"
            >
              <span className="font-medium text-ink">
                {detail?.package ? `依赖 ${detail.package}` : "依赖安装"}
              </span>
              {detail?.version ? (
                <code className="font-mono text-[11px]">@{detail.version}</code>
              ) : null}
              {detail?.reason ? (
                <span className="text-ink-3">{detail.reason}</span>
              ) : null}
              {!dependencyInstallerConfigured ? (
                <span className="basis-full text-[11px] leading-5 text-warning">
                  当前服务未配置依赖安装器；请操作者手工安装。
                </span>
              ) : null}
              <Button
                size="sm"
                disabled={Boolean(busy) || !dependencyInstallerConfigured}
                onClick={() => onReplyDependency(requestId, "once")}
              >
                批准
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={Boolean(busy)}
                onClick={() => onReplyDependency(requestId, "reject")}
              >
                拒绝
              </Button>
            </div>
          );
        })}

        {permissions.map((request) => (
          <div
            key={String(request.id)}
            className="flex flex-wrap items-center gap-2 rounded-control border border-warning/25 bg-surface px-3 py-2 text-xs"
          >
            <code className="font-mono text-[11px]">
              {String(request.action || "permission")}
            </code>
            {request.resources ? (
              <span className="text-ink-3">
                {Array.isArray(request.resources)
                  ? request.resources.join("、")
                  : String(request.resources)}
              </span>
            ) : null}
            <Button
              size="sm"
              disabled={Boolean(busy)}
              onClick={() => onReplyPermission(String(request.id), "once")}
            >
              允许一次
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={Boolean(busy)}
              onClick={() => onReplyPermission(String(request.id), "reject")}
            >
              拒绝
            </Button>
          </div>
        ))}
      </div>
    </section>
  );
}
