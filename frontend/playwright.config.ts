import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  retries: 0,
  use: { baseURL: "http://127.0.0.1:18091", locale: "zh-CN" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "cd .. && uv run python scripts/e2e_server.py --port 18091",
    url: "http://127.0.0.1:18091/api/health",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
