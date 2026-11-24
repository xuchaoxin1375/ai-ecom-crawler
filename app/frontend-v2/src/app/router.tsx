import { lazy, Suspense, type ComponentType } from "react";
import { createHashRouter, Link, Navigate } from "react-router-dom";
import { AppShell } from "./AppShell";
import { NotFoundPage } from "./NotFoundPage";
import { BatchesPage } from "../features/batches/BatchesPage";
import { Button } from "../components/ui/Button";
import { ErrorNotice } from "../components/ui/ErrorNotice";

function RouteLoading() {
  return (
    <p className="py-6 text-sm text-ink-2" role="status">
      正在加载页面…
    </p>
  );
}

function lazyPage(load: () => Promise<{ default: ComponentType }>) {
  const Page = lazy(load);
  return (
    <Suspense fallback={<RouteLoading />}>
      <Page />
    </Suspense>
  );
}

function RouteError() {
  return (
    <main className="mx-auto max-w-xl space-y-4 px-4 py-6">
      <ErrorNotice
        title="页面无法打开"
        message="请重新加载，或返回批次列表继续操作。"
        onRetry={() => window.location.reload()}
      />
      <Button asChild>
        <Link to="/batches">返回批次列表</Link>
      </Button>
    </main>
  );
}

export const router = createHashRouter([
  {
    path: "/",
    element: <AppShell />,
    ErrorBoundary: RouteError,
    children: [
      { index: true, element: <Navigate to="/batches" replace /> },
      { path: "batches", element: <BatchesPage /> },
      {
        path: "batches/:batchId",
        element: lazyPage(() =>
          import("../features/batches/BatchDetailPage").then(({ BatchDetailPage }) => ({
            default: BatchDetailPage,
          })),
        ),
      },
      {
        path: "batches/:batchId/sites/:siteKey",
        element: lazyPage(() =>
          import("../features/sites/SiteDetailPage").then(({ SiteDetailPage }) => ({
            default: SiteDetailPage,
          })),
        ),
      },
      {
        path: "tasks",
        element: lazyPage(() =>
          import("../features/tasks/TasksPage").then(({ TasksPage }) => ({
            default: TasksPage,
          })),
        ),
      },
      {
        path: "tasks/:taskId",
        element: lazyPage(() =>
          import("../features/tasks/TaskDetailPage").then(({ TaskDetailPage }) => ({
            default: TaskDetailPage,
          })),
        ),
      },
      {
        path: "builds",
        element: lazyPage(() =>
          import("../features/builds/BuildsPage").then(({ BuildsPage }) => ({
            default: BuildsPage,
          })),
        ),
      },
      {
        path: "builds/:buildId",
        element: lazyPage(() =>
          import("../features/builds/BuildDetailPage").then(({ BuildDetailPage }) => ({
            default: BuildDetailPage,
          })),
        ),
      },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
