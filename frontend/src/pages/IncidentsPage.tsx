import { useState } from "react";
import { useIncidents } from "../api/hooks";
import { IncidentTimeline } from "../components/IncidentTimeline";
import { PageHeader } from "../components/Layout";
import { PageLoader, Section, Segmented } from "../components/ui";
import { formatDuration } from "../lib/format";

type State = "all" | "ongoing" | "resolved";

export function IncidentsPage() {
  const [state, setState] = useState<State>("all");
  const incidents = useIncidents(state);
  const list = incidents.data ?? [];
  const totalDowntime = list.reduce((a, i) => a + (i.duration_seconds ?? i.ongoing_seconds ?? 0), 0);

  return (
    <div className="space-y-5">
      <PageHeader title="장애 기록" description="모든 모니터의 장애 발생·복구 이력입니다. 장애 기록은 삭제하지 않고 보관합니다." />
      <div className="flex flex-wrap items-center gap-3">
        <Segmented<State>
          label="장애 상태"
          value={state}
          onChange={setState}
          options={[
            { value: "all", label: "전체" },
            { value: "ongoing", label: "진행 중" },
            { value: "resolved", label: "복구됨" },
          ]}
        />
        {list.length > 0 && (
          <span className="text-sm text-ink-muted">
            {list.length}건 · 누적 중단 {formatDuration(totalDowntime)}
          </span>
        )}
      </div>
      <Section title="타임라인">{incidents.isLoading ? <PageLoader /> : <IncidentTimeline incidents={list} showMonitor />}</Section>
    </div>
  );
}
