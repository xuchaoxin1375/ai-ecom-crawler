import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const env =
  (globalThis as { process?: { env?: Record<string, string | undefined> } }).process
    ?.env ?? {};
const API_TARGET = env.ECOM_API_TARGET || "http://127.0.0.1:8765";

export default defineConfig({
  base: "/",
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    host: "127.0.0.1",
    port: 5175,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        headers: {
          // The backend enforces Origin == Host for writes. Keep both on the
          // API origin while the UI runs on the Vite dev origin.
          Origin: API_TARGET,
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.ts",
  },
});
