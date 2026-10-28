import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const MOCK = "http://127.0.0.1:18080";

export function uniqueEmail(prefix: string): string {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

export async function setMockMode(request: APIRequestContext, mode: "ok" | "fail" | "slow", status = 500) {
  const res = await request.get(`${MOCK}/control?mode=${mode}&status=${status}`);
  expect(res.ok()).toBeTruthy();
}

export async function registerViaUi(page: Page, email: string, password = "e2e-password-1") {
  await page.goto("/register");
  await page.getByLabel("이메일").fill(email);
  await page.getByLabel("비밀번호").fill(password);
  await page.getByRole("button", { name: "가입하기" }).click();
  await expect(page.getByRole("heading", { name: "모니터링 현황" })).toBeVisible();
}

export async function createMonitorViaUi(page: Page, opts: { name: string; url: string; failureThreshold?: number }) {
  await page.goto("/monitors/new");
  await page.getByLabel("이름").fill(opts.name);
  await page.getByLabel("URL").fill(opts.url);
  await page.getByRole("radio", { name: "1분" }).click();
  await page.getByLabel("타임아웃(초)").fill("5");
  if (opts.failureThreshold) await page.getByLabel("연속 실패 기준").fill(String(opts.failureThreshold));
  await page.getByRole("button", { name: "모니터 추가" }).click();
}

/** '지금 검사'를 누르고 결과가 반영될 때까지 기다립니다. */
export async function checkNow(page: Page) {
  const button = page.getByRole("button", { name: "지금 검사" });
  await expect(button).toBeEnabled();
  await page.waitForTimeout(1100); // 수동 검사 빈도 제한(E2E 1초)
  await button.click();
  await expect(button).toHaveAttribute("data-waiting", "true");
  await expect(button).toHaveAttribute("data-waiting", "false");
  await expect(button).toBeEnabled();
}
