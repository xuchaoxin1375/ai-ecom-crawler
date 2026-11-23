import { createHashRouter, Navigate } from "react-router-dom";
import { AppShell } from "./AppShell";
import { NotFoundPage } from "./NotFoundPage";
import { BatchesPage } from "../features/batches/BatchesPage";
import { BatchDetailPage } from "../features/batches/BatchDetailPage";
import { SiteDetailPage } from "../features/sites/SiteDetailPage";

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
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
