import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/browser",
  timeout: 90000,
  expect: { timeout: 15000 },
  retries: 0,
  workers: 1,
  reporter: "line",
  use: { baseURL: "http://127.0.0.1:8765", headless: true },
  webServer: {
    command: "python -m uvicorn seating_optimizer.api.app:app --host 127.0.0.1 --port 8765",
    url: "http://127.0.0.1:8765/healthz",
    reuseExistingServer: false,
    timeout: 60000
  }
});
