import { defineConfig, devices } from "@playwright/test";

/**
 * E2E: 모의 대상 서버 + API + 작업자 + 프론트엔드(빌드본)를 띄우고 실제 브라우저로 검증합니다.
 * 외부 사이트에는 요청하지 않습니다.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL: "http://127.0.0.1:14173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    locale: "ko-KR",
    timezoneId: "Asia/Seoul",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /mobile\.spec\.ts/ },
    { name: "mobile", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: [
    {
      command: "cd ../backend && .venv/bin/python -m tests.mock_server 18080",
      url: "http://127.0.0.1:18080/ok",
      reuseExistingServer: false,
    },
    {
      command: "bash e2e/start-backend.sh",
      url: "http://127.0.0.1:18000/api/health",
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: "npx vite build && npx vite preview --host 127.0.0.1 --port 14173 --strictPort",
      url: "http://127.0.0.1:14173",
      timeout: 120_000,
      env: { VITE_API_PROXY: "http://127.0.0.1:18000" },
      reuseExistingServer: false,
    },
  ],
});
