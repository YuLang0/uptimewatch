import { useState } from "react";
import clsx from "clsx";
import type { DailyPoint } from "../api/types";
import { formatDate, formatPercent, levelLabel, uptimeLevel, type Level } from "../lib/format";

const fill: Record<Level, string> = {
  up: "bg-up",
  warn: "bg-warn",
  down: "bg-down",
  nodata: "bg-nodata",
};

/**
 * 일별 가동률 막대(UptimeRobot 스타일). 데이터가 없는 날은 회색 '데이터 없음'으로 표시하며
 * 정상(녹색)으로 칠하지 않습니다. 각 막대는 마우스/키보드 포커스 시 상세 툴팁을 보여줍니다.
 */
export function UptimeBars({ days, compact = false }: { days: DailyPoint[]; compact?: boolean }) {
  const [active, setActive] = useState<number | null>(null);
  const current = active !== null ? days[active] : null;

  return (
    <div className="relative">
      <div
        role="list"
        aria-label="일별 가동률"
        className={clsx("flex items-end gap-[2px]", compact ? "h-6" : "h-9")}
        onMouseLeave={() => setActive(null)}
      >
        {days.map((d, i) => {
          const level = uptimeLevel(d.uptime_pct);
          return (
            <div
              key={d.date}
              role="listitem"
              tabIndex={0}
              data-level={level}
              aria-label={`${formatDate(d.date)}: ${level === "nodata" ? "데이터 없음" : `가동률 ${formatPercent(d.uptime_pct)}`}${d.incidents ? `, 장애 ${d.incidents}건` : ""}`}
              onMouseEnter={() => setActive(i)}
              onFocus={() => setActive(i)}
              onBlur={() => setActive(null)}
              className="group flex h-full min-w-0 flex-1 cursor-default items-end outline-none"
            >
              <span
                className={clsx(
                  "block h-full w-full rounded-[2px] transition-opacity",
                  fill[level],
                  active !== null && active !== i ? "opacity-60" : "opacity-100",
                  "group-focus-visible:ring-2 group-focus-visible:ring-brand group-focus-visible:ring-offset-1",
                )}
              />
            </div>
          );
        })}
      </div>
      {current && active !== null && (
        <div
          role="tooltip"
          className="pointer-events-none absolute bottom-full z-20 mb-2 w-48 -translate-x-1/2 rounded-lg border border-line bg-surface p-2.5 text-xs shadow-lg"
          style={{ left: `${Math.min(88, Math.max(12, ((active + 0.5) / days.length) * 100))}%` }}
        >
          <div className="text-base font-semibold text-ink tabular">
            {current.uptime_pct === null ? "데이터 없음" : formatPercent(current.uptime_pct)}
          </div>
          <div className="text-ink-muted">{formatDate(current.date)}</div>
          <div className="mt-1.5 flex items-center gap-1.5 text-ink-muted">
            <span className={clsx("h-2 w-2 rounded-full", fill[uptimeLevel(current.uptime_pct)])} />
            {levelLabel[uptimeLevel(current.uptime_pct)]}
            {current.incidents > 0 && <span>· 장애 {current.incidents}건</span>}
          </div>
          {current.up !== undefined && (current.up ?? 0) + (current.down ?? 0) + (current.unknown ?? 0) > 0 && (
            <div className="mt-1 text-ink-faint tabular">
              정상 {current.up} · 실패 {current.down}
              {current.unknown ? ` · 측정 불가 ${current.unknown}` : ""}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function UptimeLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
      {(["up", "warn", "down", "nodata"] as Level[]).map((l) => (
        <span key={l} className="inline-flex items-center gap-1.5">
          <span className={clsx("h-2.5 w-2.5 rounded-[2px]", fill[l])} />
          {levelLabel[l]}
          {l === "up" && " (≥99.5%)"}
          {l === "warn" && " (≥95%)"}
        </span>
      ))}
    </div>
  );
}
