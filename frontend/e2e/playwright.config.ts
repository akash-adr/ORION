import { defineConfig } from "@playwright/test";

/**
 * The demo-flow test drives the real UI against a running backend. Start the frontend as a production build:
 *   npm run build && npx next start -p 3100
 * and the backend on :8000, either `uvicorn backend.api.main:app --port 8000` or `python -m backend.api.devserver --port 8000`.
 * It uses the system Chrome, so no browser download is needed.
 */
export default defineConfig({
  testDir: ".",
  timeout: 240_000,
  expect: { timeout: 20_000 },
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE ?? "http://localhost:3100",
    channel: "chrome",
    viewport: { width: 1440, height: 900 },
    launchOptions: { args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] },
  },
});
