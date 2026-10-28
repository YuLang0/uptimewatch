import { Link } from "react-router-dom";
import clsx from "clsx";
import { useResponseTimes } from "../api/hooks";
import type { Monitor } from "../api/types";
import { formatInterval, formatMs, formatPercent, formatRelative, hostOf, monitorStatusView, uptimeLevel } from "../lib/format";
import { StatusBadge, StatusDot } from "./Status";

const stripColor = { up: "bg-up", warn: "bg-warn", down: "bg-down", nodata: "bg-nodata" } as const;

/** 최근 24시간을 1시간 단위 24칸으로 요약한 상태 띠 */
function HourStrip({ monitorId }: { monitorId: number }) {
  const { data } = useResponseTimes(monitorId, "24h");
  const points = data?.points ?? [];
  const hours: { up: number; down: number }[] = [];
  for (let i = 0; i < points.length; i += 4) {
    const chunk = points.slice(i, i + 4);
    hours.push({
      up: chunk.reduce((a, p) => a + p.up, 0),
      down: chunk.reduce((a, p) => a + p.down, 0),
    });
  }
  const cells = hours.slice(-24);
  return (
    <div className="flex h-5 items-stretch gap-[2px]" aria-hidden="true">
      {(cells.length ? cells : Array.from({ length: 24 }, () => ({ up: 0, down: 0 }))).map((h, i) => {
        const total = h.up + h.down;
        const level = uptimeLevel(total ? (h.up * 100) / total : null);
        return <span key={i} className={clsx("flex-1 rounded-[2px]", stripColor[level])} />;
      })}
    </div>
  );
}

export function MonitorCard({ monitor }: { monitor: Monitor }) {
  const view = monitorStatusView(monitor.status, monitor.consecutive_failures);
  return (
    <Link
      to={`/monitors/${monitor.id}`}
      data-testid="monitor-card"
      data-monitor-name={monitor.name}
      className={clsx(
        "card group flex flex-col gap-3 p-4 transition hover:border-ink-faint/60 hover:shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand",
        view.key === "down" && "border-down/50",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <StatusDot view={view} />
          <div className="min-w-0">
            <div className="truncate font-semibold text-ink">{monitor.name}</div>
            <div className="truncate text-xs text-ink-faint">{hostOf(monitor.url)}</div>
          </div>
        </div>
        <StatusBadge view={view} />
      </div>

      <HourStrip monitorId={monitor.id} />

      <dl className="grid grid-cols-3 gap-2 text-xs">
        <div>
          <dt className="text-ink-faint">24시간 가동률</dt>
          <dd className="mt-0.5 font-semibold text-ink tabular">{formatPercent(monitor.uptime_24h)}</dd>
        </div>
        <div>
          <dt className="text-ink-faint">응답 시간</dt>
          <dd className="mt-0.5 font-semibold text-ink tabular">{formatMs(monitor.last_response_time_ms)}</dd>
        </div>
        <div>
          <dt className="text-ink-faint">마지막 검사</dt>
          <dd className="mt-0.5 font-semibold text-ink tabular">{formatRelative(monitor.last_checked_at)}</dd>
        </div>
      </dl>
      <div className="flex items-center justify-between text-[11px] text-ink-faint">
        <span>{formatInterval(monitor.interval_seconds)}마다 확인</span>
        {monitor.consecutive_failures > 0 && (
          <span className="font-medium text-ink-muted">
            연속 실패 {monitor.consecutive_failures}/{monitor.failure_threshold}
          </span>
        )}
      </div>
    </Link>
  );
}
