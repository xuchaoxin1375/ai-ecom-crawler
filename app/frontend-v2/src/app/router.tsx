import { createHashRouter, Navigate } from "react-router-dom";
import { AppShell } from "./AppShell";
import { NotFoundPage } from "./NotFoundPage";
import { BatchesPage } from "../features/batches/BatchesPage";
import { BatchDetailPage } from "../features/batches/BatchDetailPage";
import { SiteDetailPage } from "../features/sites/SiteDetailPage";
import { TasksPage } from "../features/tasks/TasksPage";
import { TaskDetailPage } from "../features/tasks/TaskDetailPage";
import { BuildsPage } from "../features/builds/BuildsPage";
import { BuildDetailPage } from "../features/builds/BuildDetailPage";

export const router = createHashRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/batches" replace /> },
      { path: "batches", element: <BatchesPage /> },
      { path: "batches/:batchId", element: <BatchDetailPage /> },
      {
        path: "batches/:batchId/sites/:siteKey",
        element: <SiteDetailPage />,
      },
      { path: "tasks", element: <TasksPage /> },
      { path: "tasks/:taskId", element: <TaskDetailPage /> },
      { path: "builds", element: <BuildsPage /> },
      { path: "builds/:buildId", element: <BuildDetailPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
