import { expect, test } from "@playwright/test";
import { MOCK, checkNow, createMonitorViaUi, registerViaUi, setMockMode, uniqueEmail } from "./helpers";

test.describe.configure({ mode: "serial" });

test.afterEach(async ({ request }) => {
  await setMockMode(request, "ok");
});

test("모니터 등록 → 정상 → 연속 실패로 장애 → 복구 → 알림 기록", async ({ page, request }) => {
  await setMockMode(request, "ok");
  await registerViaUi(page, uniqueEmail("flow"));
  await expect(page.getByText("아직 등록된 모니터가 없습니다")).toBeVisible();

  await createMonitorViaUi(page, { name: "결제 API", url: `${MOCK}/flaky`, failureThreshold: 2 });
  await expect(page.getByTestId("monitor-title")).toHaveText("결제 API");

  // 등록 직후 첫 검사 → 정상
  const badge = page.getByTestId("status-badge").first();
  await expect(async () => {
    await page.reload();
    await expect(badge).toHaveAttribute("data-status", "up", { timeout: 2000 });
  }).toPass({ timeout: 20_000 });

  // 1회 실패: 일시적 실패(불안정) — 장애로 판정하지 않음
  await setMockMode(request, "fail", 503);
  await checkNow(page);
  await expect(badge).toHaveAttribute("data-status", "degraded");
  await expect(page.getByText("기록된 장애가 없습니다")).toBeVisible();

  // 2회 연속 실패: 장애 판정
  await checkNow(page);
  await expect(badge).toHaveAttribute("data-status", "down");
  await expect(page.getByText("예상하지 않은 HTTP 상태 코드 503").first()).toBeVisible();
  await page.reload();
  const timeline = page.getByTestId("incident-timeline");
  await expect(timeline.getByTestId("incident-item").first()).toHaveAttribute("data-ongoing", "true");
  await expect(timeline).toContainText("진행 중");

  // 복구
  await setMockMode(request, "ok");
  await checkNow(page);
  await expect(badge).toHaveAttribute("data-status", "up");
  await page.reload();
  await expect(timeline.getByTestId("incident-item").first()).toHaveAttribute("data-ongoing", "false");
  await expect(timeline).toContainText("복구됨");

  // 검사 결과 표
  const table = page.getByTestId("checks-table");
  await expect(table).toContainText("실패 · 503");
  await expect(table).toContainText("정상 · 200");

  // 대시보드 알림: 장애 1회 + 복구 1회 (중복 없음)
  await page.goto("/notifications");
  const list = page.getByTestId("notification-list");
  await expect(list.locator('li[data-kind="down"]')).toHaveCount(1);
  await expect(list.locator('li[data-kind="up"]')).toHaveCount(1);
  await expect(list).toContainText("[장애] 결제 API");
  await expect(list).toContainText("[복구] 결제 API");

  // 장애 기록 페이지
  await page.goto("/incidents");
  await expect(page.getByTestId("incident-item")).toHaveCount(1);
  await expect(page.getByTestId("incident-item").first()).toContainText("결제 API");

  // 이메일 발송 기록: SMTP 미연동 → '미연동'으로 기록
  await page.goto("/notifications?tab=deliveries");
  await expect(page.getByTestId("delivery-table")).toContainText("미연동");
});

test("SSRF: 내부 주소는 등록할 수 없다", async ({ page }) => {
  await registerViaUi(page, uniqueEmail("ssrf"));
  for (const url of ["http://169.254.169.254/latest/meta-data/", "http://localhost:8080/", "http://10.0.0.1/", "http://user:pw@example.com/"]) {
    await createMonitorViaUi(page, { name: "내부", url });
    await expect(page.getByRole("alert").or(page.getByText(/사용자 이름·비밀번호/))).toBeVisible();
    await expect(page).toHaveURL(/\/monitors\/new$/);
  }
});

test("공개 상태 페이지: 선택한 정보만 노출, 관리자 페이지와 분리", async ({ page, browser, request }) => {
  await setMockMode(request, "ok");
  await registerViaUi(page, uniqueEmail("status"));
  await createMonitorViaUi(page, { name: "내부 관리용 이름", url: `${MOCK}/flaky?secret-path=1` });
  await expect(page.getByTestId("monitor-title")).toBeVisible();

  const slug = `acme-${Date.now()}`;
  await page.goto("/status-pages");
  await page.getByRole("button", { name: "새 상태 페이지" }).click();
  await page.getByLabel("제목").fill("ACME 서비스 상태");
  await page.locator("#sp-slug").fill(slug);
  await page.getByLabel("공개 페이지 게시").check();
  await page.getByLabel("최근 장애 이력 (30일)").check();
  await page.getByLabel("모니터 추가").selectOption({ label: "내부 관리용 이름" });
  await page.getByLabel("내부 관리용 이름 공개 이름").fill("웹사이트");
  await page.getByRole("button", { name: "저장", exact: true }).click();
  await expect(page.getByTestId("status-page-card")).toContainText("게시됨");

  // 로그인하지 않은 방문자
  const anon = await browser.newContext();
  const pub = await anon.newPage();
  await pub.goto(`/status/${slug}`);
  await expect(pub.getByTestId("public-title")).toHaveText("ACME 서비스 상태");
  await expect(pub.getByTestId("public-component")).toContainText("웹사이트");
  await expect(pub.getByTestId("overall-status")).toBeVisible();
  const html = await pub.content();
  expect(html).not.toContain("127.0.0.1");
  expect(html).not.toContain("secret-path");
  expect(html).not.toContain("내부 관리용 이름");
  // 공개 페이지에는 관리자 메뉴가 없다
  await expect(pub.getByRole("navigation", { name: "주 메뉴" })).toHaveCount(0);
  // 관리자 화면은 로그인 필요
  await pub.goto("/");
  await expect(pub).toHaveURL(/\/login$/);
  // 미게시/없는 페이지는 404 안내
  await pub.goto(`/status/${slug}-nope`);
  await expect(pub.getByText("상태 페이지를 찾을 수 없습니다")).toBeVisible();
  await anon.close();
});

test("사용자별 데이터 분리", async ({ page, browser }) => {
  await registerViaUi(page, uniqueEmail("owner"));
  await createMonitorViaUi(page, { name: "소유자 전용", url: `${MOCK}/ok` });
  await expect(page.getByTestId("monitor-title")).toBeVisible();
  const monitorUrl = page.url();

  const other = await browser.newContext();
  const p2 = await other.newPage();
  await registerViaUi(p2, uniqueEmail("intruder"));
  await expect(p2.getByText("아직 등록된 모니터가 없습니다")).toBeVisible();
  await p2.goto(monitorUrl);
  await expect(p2.getByText("모니터를 찾을 수 없습니다")).toBeVisible();
  await other.close();
});

test("알림 설정: 이메일 미연동 표시와 테스트 알림", async ({ page }) => {
  await registerViaUi(page, uniqueEmail("notify"));
  await page.goto("/notifications?tab=settings");
  await expect(page.getByTestId("email-channel")).toHaveAttribute("data-configured", "false");
  await expect(page.getByTestId("email-channel")).toContainText("미연동");
  await expect(page.getByTestId("email-channel")).toContainText("SMTP_HOST=");
  await page.getByRole("button", { name: "테스트 알림 보내기" }).click();
  await expect(page.getByTestId("test-result")).toContainText("대시보드 알림 생성됨");
  await expect(page.getByTestId("test-result")).toContainText("미연동");
  await page.goto("/notifications");
  await expect(page.getByTestId("notification-list")).toContainText("[테스트]");
});

test("다크 모드 전환이 유지된다", async ({ page }) => {
  await registerViaUi(page, uniqueEmail("theme"));
  const html = page.locator("html");
  const wasDark = await html.evaluate((el) => el.classList.contains("dark"));
  await page.getByRole("button", { name: wasDark ? "라이트 모드로 전환" : "다크 모드로 전환" }).first().click();
  await expect(html).toHaveClass(wasDark ? /^(?!.*dark)/ : /dark/);
  await page.reload();
  expect(await html.evaluate((el) => el.classList.contains("dark"))).toBe(!wasDark);
});
