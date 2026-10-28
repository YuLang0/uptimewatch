import { describe, expect, it } from "vitest";
import {
  daysUntil,
  formatDuration,
  formatInterval,
  formatMs,
  formatPercent,
  formatRelative,
  hostOf,
  looksLikeSecretInUrl,
  monitorStatusView,
  uptimeLevel,
} from "./format";

describe("formatPercent", () => {
  it("관측값이 없으면 100% 가 아니라 '데이터 없음'", () => {
    expect(formatPercent(null)).toBe("데이터 없음");
    expect(formatPercent(undefined)).toBe("데이터 없음");
  });
  it("반올림으로 장애를 가리지 않도록 내림 처리", () => {
    expect(formatPercent(99.999)).toBe("99.99%");
    expect(formatPercent(99.9999, 3)).toBe("99.999%");
    expect(formatPercent(100)).toBe("100%");
    expect(formatPercent(0)).toBe("0.00%");
  });
});

describe("uptimeLevel", () => {
  it("구간별 등급", () => {
    expect(uptimeLevel(100)).toBe("up");
    expect(uptimeLevel(99.5)).toBe("up");
    expect(uptimeLevel(99.4)).toBe("warn");
    expect(uptimeLevel(95)).toBe("warn");
    expect(uptimeLevel(94.9)).toBe("down");
  });
  it("데이터가 없으면 정상(up)이 아닌 nodata", () => {
    expect(uptimeLevel(null)).toBe("nodata");
  });
});

describe("formatDuration / formatMs / formatInterval", () => {
  it("한국어 기간 표기", () => {
    expect(formatDuration(0)).toBe("0초");
    expect(formatDuration(45)).toBe("45초");
    expect(formatDuration(125)).toBe("2분 5초");
    expect(formatDuration(3600 + 120)).toBe("1시간 2분");
    expect(formatDuration(86400 * 2 + 3600 * 3 + 60)).toBe("2일 3시간");
    expect(formatDuration(null)).toBe("—");
  });
  it("응답 시간", () => {
    expect(formatMs(87.4)).toBe("87ms");
    expect(formatMs(1234)).toBe("1.23s");
    expect(formatMs(12_345)).toBe("12.3s");
    expect(formatMs(null)).toBe("—");
  });
  it("확인 주기", () => {
    expect(formatInterval(60)).toBe("1분");
    expect(formatInterval(3600)).toBe("1시간");
    expect(formatInterval(90)).toBe("90초");
  });
});

describe("formatRelative / daysUntil", () => {
  const now = Date.parse("2026-10-25T12:00:00Z");
  it("상대 시간", () => {
    expect(formatRelative("2026-10-25T11:59:58Z", now)).toBe("방금");
    expect(formatRelative("2026-10-25T11:59:00Z", now)).toBe("1분 전");
    expect(formatRelative("2026-10-25T09:00:00Z", now)).toBe("3시간 전");
    expect(formatRelative("2026-10-25T12:05:00Z", now)).toBe("5분 후");
    expect(formatRelative(null, now)).toBe("—");
  });
  it("인증서 남은 일수", () => {
    expect(daysUntil("2026-11-04T12:00:00Z", now)).toBe(10);
    expect(daysUntil("2026-10-24T12:00:00Z", now)).toBe(-1);
  });
});

describe("monitorStatusView", () => {
  it("연속 실패가 기준 미만이면 '불안정'", () => {
    expect(monitorStatusView("up", 1)).toEqual({ key: "degraded", label: "불안정" });
    expect(monitorStatusView("up", 0).label).toBe("정상");
    expect(monitorStatusView("down", 5).label).toBe("장애");
    expect(monitorStatusView("paused").label).toBe("일시 정지");
    expect(monitorStatusView("pending").label).toBe("측정 대기");
  });
});

describe("URL helpers", () => {
  it("호스트 추출", () => {
    expect(hostOf("https://example.com:8443/a?b=1")).toBe("example.com:8443");
    expect(hostOf("not a url")).toBe("not a url");
  });
  it("쿼리의 비밀정보 의심 파라미터 경고", () => {
    expect(looksLikeSecretInUrl("https://a.com/health?token=abc")).toBe(true);
    expect(looksLikeSecretInUrl("https://a.com/health?api_key=1")).toBe(true);
    expect(looksLikeSecretInUrl("https://a.com/health?region=kr")).toBe(false);
  });
});
