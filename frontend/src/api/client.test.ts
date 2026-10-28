import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, errorMessage, setCsrfToken } from "./client";

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue(
    new Response(body === undefined ? null : JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fn);
  return fn;
}

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken(null);
  document.cookie = "uw_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT";
});

describe("api client", () => {
  it("변경 요청에 CSRF 헤더를 붙이고 GET 에는 붙이지 않는다", async () => {
    setCsrfToken("tok-123");
    const fetchFn = mockFetch(200, { ok: true });
    await api("/api/monitors", { method: "POST", body: { a: 1 } });
    expect(fetchFn.mock.calls[0][1].headers["X-CSRF-Token"]).toBe("tok-123");
    expect(fetchFn.mock.calls[0][1].credentials).toBe("same-origin");
    await api("/api/monitors");
    expect(fetchFn.mock.calls[1][1].headers["X-CSRF-Token"]).toBeUndefined();
  });

  it("메모리 토큰이 없으면 쿠키 값을 사용", async () => {
    document.cookie = "uw_csrf=from-cookie";
    const fetchFn = mockFetch(200, {});
    await api("/api/x", { method: "DELETE" });
    expect(fetchFn.mock.calls[0][1].headers["X-CSRF-Token"]).toBe("from-cookie");
  });

  it("서버 오류 메시지를 ApiError 로 전달", async () => {
    mockFetch(422, { detail: "확인 주기는 60초 이상이어야 합니다." });
    await expect(api("/api/monitors", { method: "POST", body: {} })).rejects.toMatchObject({
      status: 422,
      detail: "확인 주기는 60초 이상이어야 합니다.",
    });
  });

  it("204 응답은 undefined", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    expect(await api("/api/monitors/1", { method: "DELETE" })).toBeUndefined();
  });

  it("네트워크 오류는 한국어 메시지", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = await api("/api/x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(errorMessage(err)).toMatch(/서버에 연결할 수 없습니다/);
  });
});
