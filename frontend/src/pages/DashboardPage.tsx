import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useDashboard, useMonitors } from "../api/hooks";
import { Icon } from "../components/Icon";
import { IncidentTimeline } from "../components/IncidentTimeline";
import { PageHeader } from "../components/Layout";
import { MonitorCard } from "../components/MonitorCard";
import { Banner, EmptyState, PageLoader, Section, Segmented, StatTile } from "../components/ui";
import { formatMs, formatPercent, formatRelative } from "../lib/format";

type Filter = "all" | "down" | "up" | "paused";

export function DashboardPage() {
  const dashboard = useDashboard();
  const monitors = useMonitors();
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (monitors.data ?? [])
      .filter((m) => filter === "all" || m.status === filter)
      .filter((m) => !q || m.name.toLowerCase().includes(q) || m.url.toLowerCase().includes(q))
      .sort((a, b) => Number(b.status === "down") - Number(a.status === "down"));
  }, [monitors.data, filter, query]);

  if (dashboard.isLoading || monitors.isLoading) return <PageLoader />;
  const d = dashboard.data;

  return (
    <div className="space-y-5">
      <PageHeader
        title="모니터링 현황"
        description="등록한 웹사이트의 실시간 상태와 가동률입니다."
        actions={
          <Link to="/monitors/new" className="btn-primary">
            <Icon name="plus" className="h-4 w-4" />새 모니터
          </Link>
        }
      />

      {d?.worker.status === "stale" && (
        <Banner tone="warn">
          <strong>검사 작업자가 응답하지 않습니다.</strong> 마지막 신호 {formatRelative(d.worker.last_seen_at)}. 그동안의 공백은
          가동률 계산에서 '정상'으로 간주되지 않으며 측정 커버리지가 낮아집니다.
        </Banner>
      )}
      {d?.worker.status === "never" && (d?.counts.total ?? 0) > 0 && (
        <Banner tone="warn">
          <strong>검사 작업자가 아직 실행되지 않았습니다.</strong> <code className="font-mono text-xs">worker</code> 서비스를 시작해야
          정기 검사가 수행됩니다.
        </Banner>
      )}

      {d && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <StatTile label="전체 모니터" value={d.counts.total} sub={`일시 정지 ${d.counts.paused} · 측정 대기 ${d.counts.pending}`} testId="stat-total" />
          <StatTile label="정상" value={d.counts.up} tone="up" testId="stat-up" />
          <StatTile label="장애" value={d.counts.down} tone="down" sub={d.incidents_24h ? `24시간 내 장애 ${d.incidents_24h}건` : "24시간 내 장애 없음"} testId="stat-down" />
          <StatTile label="24시간 가동률" value={<span className="tabular">{formatPercent(d.uptime_24h)}</span>} sub="관측한 검사 기준" />
          <StatTile label="평균 응답 시간" value={<span className="tabular">{formatMs(d.avg_response_24h)}</span>} sub="최근 24시간" />
        </div>
      )}

      {d && d.open_incidents.length > 0 && (
        <Section title="진행 중인 장애" description="복구될 때까지 이곳에 표시됩니다.">
          <IncidentTimeline incidents={d.open_incidents} showMonitor />
        </Section>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Segmented<Filter>
          label="상태 필터"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `전체 ${monitors.data?.length ?? 0}` },
            { value: "down", label: `장애 ${d?.counts.down ?? 0}` },
            { value: "up", label: `정상 ${d?.counts.up ?? 0}` },
            { value: "paused", label: `일시 정지 ${d?.counts.paused ?? 0}` },
          ]}
        />
        <div className="relative w-full sm:ml-auto sm:w-64">
          <Icon name="search" className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" />
          <input
            aria-label="모니터 검색"
            className="input pl-9"
            placeholder="이름 또는 URL 검색"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
      </div>

      {(monitors.data?.length ?? 0) === 0 ? (
        <EmptyState icon="pulse" title="아직 등록된 모니터가 없습니다">
          <p>웹사이트 주소를 등록하면 설정한 주기로 실제 HTTP 요청을 보내 상태를 확인합니다.</p>
          <Link to="/monitors/new" className="btn-primary mt-4">
            <Icon name="plus" className="h-4 w-4" />첫 모니터 추가
          </Link>
        </EmptyState>
      ) : list.length === 0 ? (
        <EmptyState icon="search" title="조건에 맞는 모니터가 없습니다" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {list.map((m) => (
            <MonitorCard key={m.id} monitor={m} />
          ))}
        </div>
      )}

      {d && !d.email.configured && (
        <p className="flex items-center gap-1.5 text-xs text-ink-faint">
          <Icon name="mail" className="h-3.5 w-3.5" />
          이메일 알림 미연동 — 대시보드 알림만 동작합니다.{" "}
          <Link to="/notifications?tab=settings" className="underline">
            설정 방법 보기
          </Link>
        </p>
      )}
    </div>
  );
}
