import { createHashRouter, Navigate } from "react-router-dom";
import { AppShell } from "./AppShell";
import { NotFoundPage } from "./NotFoundPage";
import { BatchesPage } from "../features/batches/BatchesPage";
import { BatchDetailPage } from "../features/batches/BatchDetailPage";

export const router = createHashRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/batches" replace /> },
      { path: "batches", element: <BatchesPage /> },
      { path: "batches/:batchId", element: <BatchDetailPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
