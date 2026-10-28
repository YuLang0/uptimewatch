import type { MonitorStatus } from "../api/types";

const NO_DATA = "데이터 없음";

export function formatPercent(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return NO_DATA;
  if (value >= 100) return "100%";
  // 99.999 를 100% 로 반올림해 장애를 가리지 않도록 내림 처리
  const factor = 10 ** digits;
  return `${(Math.floor(value * factor) / factor).toFixed(digits)}%`;
}

export function formatMs(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value >= 10_000) return `${(value / 1000).toFixed(1)}s`;
  if (value >= 1000) return `${(value / 1000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  let s = Math.max(0, Math.floor(seconds));
  const d = Math.floor(s / 86400);
  s -= d * 86400;
  const h = Math.floor(s / 3600);
  s -= h * 3600;
  const m = Math.floor(s / 60);
  s -= m * 60;
  const parts: string[] = [];
  if (d) parts.push(`${d}일`);
  if (h) parts.push(`${h}시간`);
  if (m && !d) parts.push(`${m}분`);
  if (!d && !h && (s || parts.length === 0)) parts.push(`${s}초`);
  return parts.join(" ");
}

export function formatInterval(seconds: number): string {
  if (seconds % 3600 === 0) return `${seconds / 3600}시간`;
  if (seconds % 60 === 0) return `${seconds / 60}분`;
  return `${seconds}초`;
}

export function formatRelative(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "—";
  const diff = Math.round((now - new Date(iso).getTime()) / 1000);
  const future = diff < 0;
  const abs = Math.abs(diff);
  let text: string;
  if (abs < 10) return future ? "곧" : "방금";
  if (abs < 60) text = `${abs}초`;
  else if (abs < 3600) text = `${Math.floor(abs / 60)}분`;
  else if (abs < 86400) text = `${Math.floor(abs / 3600)}시간`;
  else text = `${Math.floor(abs / 86400)}일`;
  return future ? `${text} 후` : `${text} 전`;
}

const dateTimeFmt = new Intl.DateTimeFormat("ko-KR", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hour12: false,
});
const shortFmt = new Intl.DateTimeFormat("ko-KR", {
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

export function formatDateTime(iso: string | null | undefined): string {
  return iso ? dateTimeFmt.format(new Date(iso)) : "—";
}

export function formatShort(iso: string | null | undefined): string {
  return iso ? shortFmt.format(new Date(iso)) : "—";
}

export function formatDate(isoDate: string): string {
  const [y, m, d] = isoDate.split("-").map(Number);
  return `${y}년 ${m}월 ${d}일`;
}

export type Level = "up" | "warn" | "down" | "nodata";

/** 가동률 → 상태 등급. 데이터가 없으면 'nodata' (정상으로 표시하지 않음). */
export function uptimeLevel(pct: number | null | undefined): Level {
  if (pct === null || pct === undefined) return "nodata";
  if (pct >= 99.5) return "up";
  if (pct >= 95) return "warn";
  return "down";
}

export const levelLabel: Record<Level, string> = {
  up: "정상",
  warn: "일부 장애",
  down: "장애",
  nodata: "데이터 없음",
};

export interface StatusView {
  key: "up" | "down" | "paused" | "pending" | "degraded";
  label: string;
}

export function monitorStatusView(status: MonitorStatus, consecutiveFailures = 0): StatusView {
  if (status === "down") return { key: "down", label: "장애" };
  if (status === "paused") return { key: "paused", label: "일시 정지" };
  if (consecutiveFailures > 0) return { key: "degraded", label: "불안정" };
  if (status === "up") return { key: "up", label: "정상" };
  return { key: "pending", label: "측정 대기" };
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

export const errorTypeLabel: Record<string, string> = {
  timeout: "타임아웃",
  dns: "DNS 오류",
  connection: "연결 오류",
  tls: "TLS 오류",
  status: "상태 코드 불일치",
  blocked: "보안 정책 차단",
  redirect: "리다이렉트 오류",
  protocol: "프로토콜 오류",
  internal: "측정 불가",
};

export function daysUntil(iso: string | null | undefined, now: number = Date.now()): number | null {
  if (!iso) return null;
  return Math.floor((new Date(iso).getTime() - now) / 86_400_000);
}

/** URL 쿼리에 비밀정보로 보이는 파라미터가 있는지 경고용으로 검사 */
export function looksLikeSecretInUrl(url: string): boolean {
  try {
    const u = new URL(url);
    return [...u.searchParams.keys()].some((k) =>
      /(token|secret|password|passwd|pwd|api[_-]?key|apikey|auth|sig|signature|session|credential)/i.test(k),
    );
  } catch {
    return false;
  }
}
