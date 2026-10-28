import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { StatusBadge, publicStatusView } from "./Status";
import { UptimeBars } from "./UptimeBars";
import { DEFAULT_MONITOR, MonitorForm, validateMonitor } from "./MonitorForm";
import { IncidentTimeline } from "./IncidentTimeline";
import { MemoryRouter } from "react-router-dom";
import type { Incident } from "../api/types";

describe("StatusBadge", () => {
  it("색상만이 아닌 텍스트 라벨로 상태를 표시", () => {
    render(<StatusBadge status="down" consecutiveFailures={3} />);
    const badge = screen.getByTestId("status-badge");
    expect(badge).toHaveTextContent("장애");
    expect(badge).toHaveAttribute("data-status", "down");
  });
  it("기준 미만 실패는 불안정", () => {
    render(<StatusBadge status="up" consecutiveFailures={1} />);
    expect(screen.getByTestId("status-badge")).toHaveTextContent("불안정");
  });
  it("공개 페이지 상태 라벨", () => {
    expect(publicStatusView("up").label).toBe("정상 운영");
    expect(publicStatusView("unknown").label).toBe("확인 중");
  });
});

describe("UptimeBars", () => {
  const days = [
    { date: "2026-10-23", uptime_pct: null, incidents: 0, up: 0, down: 0, unknown: 0 },
    { date: "2026-10-24", uptime_pct: 97.5, incidents: 1, up: 39, down: 1, unknown: 0 },
    { date: "2026-10-25", uptime_pct: 100, incidents: 0, up: 100, down: 0, unknown: 2 },
  ];

  it("데이터 없는 날은 정상(녹색)으로 칠하지 않는다", () => {
    render(<UptimeBars days={days} />);
    const items = screen.getAllByRole("listitem");
    expect(items.map((i) => i.dataset.level)).toEqual(["nodata", "warn", "up"]);
    expect(items[0]).toHaveAccessibleName(/데이터 없음/);
    expect(items[1]).toHaveAccessibleName(/가동률 97.50%, 장애 1건/);
  });

  it("포커스 시 상세 툴팁을 보여준다(키보드 접근)", () => {
    render(<UptimeBars days={days} />);
    fireEvent.focus(screen.getAllByRole("listitem")[2]);
    const tip = screen.getByRole("tooltip");
    expect(tip).toHaveTextContent("100%");
    expect(tip).toHaveTextContent("측정 불가 2");
  });
});

describe("MonitorForm", () => {
  it("클라이언트 검증 규칙", () => {
    const errs = validateMonitor({ ...DEFAULT_MONITOR, name: " ", url: "ftp://x", interval_seconds: 30, timeout_seconds: 40 });
    expect(Object.keys(errs).sort()).toEqual(["interval_seconds", "name", "timeout_seconds", "url"]);
    expect(validateMonitor({ ...DEFAULT_MONITOR, name: "a", url: "https://user:pw@a.com" }).url).toMatch(/비밀번호/);
    expect(validateMonitor({ ...DEFAULT_MONITOR, name: "a", url: "https://a.com", expected_status: "200-299,301" })).toEqual({});
  });

  it("오류가 있으면 제출하지 않고 메시지를 보여준다", async () => {
    const onSubmit = vi.fn();
    render(<MonitorForm initial={DEFAULT_MONITOR} onSubmit={onSubmit} onCancel={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "모니터 추가" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByText("이름을 입력하세요.")).toBeInTheDocument();
  });

  it("올바른 값이면 정리된 값으로 제출", async () => {
    const onSubmit = vi.fn();
    render(<MonitorForm initial={DEFAULT_MONITOR} onSubmit={onSubmit} onCancel={() => {}} />);
    await userEvent.type(screen.getByLabelText("이름"), "  메인 사이트 ");
    const url = screen.getByLabelText("URL");
    await userEvent.clear(url);
    await userEvent.type(url, "https://example.com/health");
    await userEvent.click(screen.getByRole("radio", { name: "1분" }));
    await userEvent.click(screen.getByRole("button", { name: "모니터 추가" }));
    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ name: "메인 사이트", url: "https://example.com/health", interval_seconds: 60 }),
    );
  });

  it("쿼리에 토큰이 있으면 경고", async () => {
    render(<MonitorForm initial={{ ...DEFAULT_MONITOR, url: "https://a.com/?token=1" }} onSubmit={() => {}} onCancel={() => {}} />);
    expect(screen.getByText(/토큰·비밀번호로 보이는 값/)).toBeInTheDocument();
  });
});

describe("IncidentTimeline", () => {
  const base: Incident = {
    id: 1,
    monitor_id: 1,
    monitor_name: "API",
    started_at: "2026-10-25T01:00:00Z",
    detected_at: "2026-10-25T01:02:00Z",
    resolved_at: "2026-10-25T01:12:30Z",
    duration_seconds: 750,
    ongoing_seconds: null,
    cause_type: "timeout",
    cause_message: "10초 안에 응답이 없습니다 (타임아웃).",
    failed_checks: 4,
  };
  it("진행 중/복구됨과 지속 시간을 표시", () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <IncidentTimeline incidents={[{ ...base, id: 2, resolved_at: null, duration_seconds: null, ongoing_seconds: 300 }, base]} showMonitor />
      </MemoryRouter>,
    );
    const items = screen.getAllByTestId("incident-item");
    expect(items[0]).toHaveTextContent("진행 중");
    expect(items[0]).toHaveTextContent("5분 경과");
    expect(items[1]).toHaveTextContent("복구됨");
    expect(items[1]).toHaveTextContent("지속 12분 30초");
  });
  it("장애가 없으면 안내 문구", () => {
    render(<IncidentTimeline incidents={[]} />);
    expect(screen.getByText("기록된 장애가 없습니다")).toBeInTheDocument();
  });
});
