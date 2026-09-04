import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: "http://127.0.0.1:5176", headless: true },
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5176",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
