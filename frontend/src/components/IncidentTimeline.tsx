import { Link } from "react-router-dom";
import clsx from "clsx";
import type { Incident } from "../api/types";
import { errorTypeLabel, formatDateTime, formatDuration } from "../lib/format";
import { EmptyState } from "./ui";

/** 장애 타임라인: 진행 중(빨강, 맥동) / 복구됨(녹색) — 상태는 항상 텍스트 라벨과 함께 표시 */
export function IncidentTimeline({ incidents, showMonitor = false }: { incidents: Incident[]; showMonitor?: boolean }) {
  if (!incidents.length) {
    return (
      <EmptyState icon="check" title="기록된 장애가 없습니다">
        연속 실패 기준에 도달하면 장애로 기록되고 알림이 발송됩니다.
      </EmptyState>
    );
  }
  return (
    <ol className="relative" data-testid="incident-timeline">
      {incidents.map((inc, idx) => {
        const ongoing = inc.resolved_at === null;
        return (
          <li key={inc.id} className="relative flex gap-3 pb-5 last:pb-0" data-testid="incident-item" data-ongoing={ongoing}>
            {idx < incidents.length - 1 && (
              <span className="absolute left-[7px] top-5 h-[calc(100%-12px)] w-px bg-line" aria-hidden="true" />
            )}
            <span className="relative mt-1 flex h-[15px] w-[15px] shrink-0 items-center justify-center" aria-hidden="true">
              {ongoing && <span className="absolute h-full w-full rounded-full bg-down animate-pulse-ring" />}
              <span
                className={clsx(
                  "relative h-[11px] w-[11px] rounded-full ring-2 ring-surface",
                  ongoing ? "bg-down" : "bg-up",
                )}
              />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span
                  className={clsx(
                    "rounded px-1.5 py-0.5 text-[11px] font-semibold",
                    ongoing ? "bg-down/10 text-down" : "bg-up/10 text-ink",
                  )}
                >
                  {ongoing ? "진행 중" : "복구됨"}
                </span>
                {showMonitor ? (
                  <Link to={`/monitors/${inc.monitor_id}`} className="font-medium text-ink hover:underline">
                    {inc.monitor_name}
                  </Link>
                ) : (
                  <span className="font-medium text-ink">{inc.cause_type ? errorTypeLabel[inc.cause_type] ?? inc.cause_type : "장애"}</span>
                )}
                <span className="text-xs text-ink-faint tabular">
                  {ongoing ? `${formatDuration(inc.ongoing_seconds)} 경과` : `지속 ${formatDuration(inc.duration_seconds)}`}
                </span>
              </div>
              {inc.cause_message && <p className="mt-1 break-words text-sm text-ink-muted">{inc.cause_message}</p>}
              <dl className="mt-1.5 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-ink-faint tabular [&>div]:whitespace-nowrap">
                <div>
                  <dt className="inline">시작 </dt>
                  <dd className="inline text-ink-muted">{formatDateTime(inc.started_at)}</dd>
                </div>
                <div>
                  <dt className="inline">판정 </dt>
                  <dd className="inline text-ink-muted">{formatDateTime(inc.detected_at)}</dd>
                </div>
                <div>
                  <dt className="inline">복구 </dt>
                  <dd className="inline text-ink-muted">{ongoing ? "—" : formatDateTime(inc.resolved_at)}</dd>
                </div>
              </dl>
              <div className="mt-0.5 text-xs text-ink-faint">실패한 검사 {inc.failed_checks}회</div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
