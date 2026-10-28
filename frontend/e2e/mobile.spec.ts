import { expect, test } from "@playwright/test";
import { MOCK, createMonitorViaUi, registerViaUi, uniqueEmail } from "./helpers";

test("모바일: 하단 탭 메뉴와 가로 스크롤 없는 레이아웃", async ({ page }) => {
  await registerViaUi(page, uniqueEmail("mobile"));
  const mobileNav = page.getByRole("navigation", { name: "모바일 메뉴" });
  await expect(mobileNav).toBeVisible();
  await expect(page.getByRole("navigation", { name: "주 메뉴" })).toBeHidden();

  await createMonitorViaUi(page, { name: "모바일 확인", url: `${MOCK}/ok` });
  await expect(page.getByTestId("monitor-title")).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);

  await mobileNav.getByRole("link", { name: "대시보드" }).click();
  await expect(page.getByTestId("monitor-card")).toHaveCount(1);
  const overflowDash = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflowDash).toBeLessThanOrEqual(1);
});
