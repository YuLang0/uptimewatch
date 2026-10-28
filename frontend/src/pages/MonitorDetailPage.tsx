import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api, errorMessage } from "../api/client";
import {
  keys,
  useChecks,
  useDailyUptime,
  useMonitor,
  useMonitorIncidents,
  useMonitorStats,
  useResponseTimes,
  type Range,
} from "../api/hooks";
import type { Monitor } from "../api/types";
import { Icon } from "../components/Icon";
import { IncidentTimeline } from "../components/IncidentTimeline";
import { ResponseTimeChart } from "../components/ResponseTimeChart";
import { StatusBadge } from "../components/Status";
import { useToast } from "../components/Toast";
import { UptimeBars, UptimeLegend } from "../components/UptimeBars";
import { ConfirmDialog, EmptyState, PageLoader, Section, Segmented, Spinner } from "../components/ui";
import {
  daysUntil,
  errorTypeLabel,
  formatDateTime,
  formatDuration,
  formatInterval,
  formatMs,
  formatPercent,
  formatRelative,
} from "../lib/format";

const RANGE_LABEL: Record<Range, string> = { "24h": "24시간", "7d": "7일", "30d": "30일" };

export function MonitorDetailPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();
  const [waitingCheck, setWaitingCheck] = useState<string | null>(null);
  const monitor = useMonitor(id, waitingCheck !== null);
  const stats = useMonitorStats(id);
  const [range, setRange] = useState<Range>("24h");
  const series = useResponseTimes(id, range);
  const daily = useDailyUptime(id, 90);
  const incidents = useMonitorIncidents(id);
  const [checksFilter, setChecksFilter] = useState<"all" | "down">("all");
  const checks = useChecks(id, checksFilter);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: keys.monitor(id) });
    qc.invalidateQueries({ queryKey: keys.monitors });
    qc.invalidateQueries({ queryKey: keys.dashboard });
  };

  // '지금 검사' 후 결과가 기록될 때까지 빠르게 갱신
  useEffect(() => {
    if (!waitingCheck || !monitor.data) return;
    const last = monitor.data.last_checked_at;
    if (last && new Date(last).getTime() >= new Date(waitingCheck).getTime() - 1000) {
      setWaitingCheck(null);
      invalidate();
      toast(monitor.data.last_outcome === "up" ? "검사 완료: 정상 응답" : "검사 완료: 실패가 기록되었습니다", monitor.data.last_outcome === "up" ? "success" : "error");
    }
    const timer = window.setTimeout(() => setWaitingCheck(null), 45_000);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [monitor.data?.last_checked_at, waitingCheck]);

  const action = useMutation({
    mutationFn: (kind: "pause" | "resume" | "check") =>
      api<Monitor | { requested_at: string }>(`/api/monitors/${id}/${kind}`, { method: "POST" }),
    onSuccess: (data, kind) => {
      if (kind === "check") {
        setWaitingCheck((data as { requested_at: string }).requested_at);
        toast("검사를 요청했습니다. 잠시 후 결과가 표시됩니다.", "info");
      } else {
        toast(kind === "pause" ? "모니터를 일시 정지했습니다." : "모니터 검사를 재개했습니다.");
      }
      invalidate();
    },
    onError: (err) => toast(errorMessage(err), "error"),
  });

  const remove = useMutation({
    mutationFn: () => api(`/api/monitors/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.monitors });
      qc.invalidateQueries({ queryKey: keys.dashboard });
      toast("모니터를 삭제했습니다.");
      navigate("/", { replace: true });
    },
    onError: (err) => toast(errorMessage(err), "error"),
  });

  if (monitor.isLoading) return <PageLoader />;
  if (monitor.isError || !monitor.data)
    return (
      <EmptyState icon="alert" title="모니터를 찾을 수 없습니다">
        <Link to="/" className="btn-secondary mt-3">
          대시보드로
        </Link>
      </EmptyState>
    );

  const m = monitor.data;
  const s = stats.data;
  const tlsDays = daysUntil(m.tls_expires_at);
  const current = s?.[range];

  return (
    <div className="space-y-5">
      <Link to="/" className="inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink">
        <Icon name="arrowLeft" className="h-4 w-4" />
        대시보드
      </Link>

      {/* 헤더 */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2.5">
            <h1 className="truncate text-xl font-semibold tracking-tight sm:text-2xl" data-testid="monitor-title">
              {m.name}
            </h1>
            <StatusBadge status={m.status} consecutiveFailures={m.consecutive_failures} />
          </div>
          <a href={m.url} target="_blank" rel="noopener noreferrer nofollow" className="mt-1 inline-flex max-w-full items-center gap-1 break-all font-mono text-sm text-ink-muted hover:text-ink">
            {m.url}
            <Icon name="external" className="h-3.5 w-3.5 shrink-0" />
          </a>
          {m.description && <p className="mt-1 text-sm text-ink-muted">{m.description}</p>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            className="btn-secondary"
            data-waiting={waitingCheck !== null}
            disabled={!m.is_active || action.isPending || waitingCheck !== null}
            onClick={() => action.mutate("check")}
          >
            {waitingCheck ? <Spinner /> : <Icon name="refresh" className="h-4 w-4" />}
            지금 검사
          </button>
          {m.is_active ? (
            <button type="button" className="btn-secondary" onClick={() => action.mutate("pause")} disabled={action.isPending}>
              <Icon name="pause" className="h-4 w-4" />
              일시 정지
            </button>
          ) : (
            <button type="button" className="btn-primary" onClick={() => action.mutate("resume")} disabled={action.isPending}>
              <Icon name="play" className="h-4 w-4" />
              재개
            </button>
          )}
          <Link to={`/monitors/${m.id}/edit`} className="btn-secondary">
            <Icon name="edit" className="h-4 w-4" />
            수정
          </Link>
          <button type="button" className="btn-danger" onClick={() => setConfirmDelete(true)}>
            <Icon name="trash" className="h-4 w-4" />
            삭제
          </button>
        </div>
      </div>

      {/* 현재 상태 요약 */}
      <div className="card grid grid-cols-2 gap-4 p-4 sm:grid-cols-4 lg:grid-cols-6">
        <Fact label="마지막 검사" value={formatRelative(m.last_checked_at)} title={formatDateTime(m.last_checked_at)} />
        <Fact
          label="마지막 결과"
          value={
            m.last_outcome === null
              ? "—"
              : m.last_status_code
                ? `HTTP ${m.last_status_code} · ${formatMs(m.last_response_time_ms)}`
                : errorTypeLabel[m.last_error_type ?? ""] ?? "실패"
          }
        />
        <Fact label="연속 실패" value={`${m.consecutive_failures} / ${m.failure_threshold}회`} />
        <Fact label="다음 검사" value={m.is_active ? formatRelative(m.next_check_at) : "일시 정지됨"} />
        <Fact label="확인 주기" value={`${formatInterval(m.interval_seconds)} · 타임아웃 ${m.timeout_seconds}초`} />
        <Fact
          label="TLS 인증서"
          value={
            m.url.startsWith("https://")
              ? tlsDays === null
                ? "확인 전"
                : tlsDays < 0
                  ? "만료됨"
                  : `${tlsDays}일 남음`
              : "HTTP (해당 없음)"
          }
          title={m.tls_expires_at ? `만료: ${formatDateTime(m.tls_expires_at)}` : undefined}
          tone={tlsDays !== null && tlsDays < 14 ? "warn" : undefined}
        />
      </div>

      {m.last_outcome === "down" && m.last_error_message && (
        <div className="flex items-start gap-2 rounded-xl border border-down/40 bg-down/5 px-4 py-3 text-sm" role="status">
          <Icon name="alert" className="mt-0.5 h-4 w-4 shrink-0 text-down" />
          <div>
            <span className="font-medium">{errorTypeLabel[m.last_error_type ?? ""] ?? "실패"}</span>
            <span className="text-ink-muted"> — {m.last_error_message}</span>
          </div>
        </div>
      )}

      {/* 가동률 통계 */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        {(["24h", "7d", "30d"] as Range[]).map((w) => {
          const st = s?.[w];
          return (
            <div key={w} className="card p-4" data-testid={`uptime-${w}`}>
              <div className="text-xs font-medium text-ink-muted">{RANGE_LABEL[w]} 가동률</div>
              <div className="mt-1 text-2xl font-semibold tracking-tight tabular">{st ? formatPercent(st.uptime_pct, 3) : "—"}</div>
              {st && (
                <div className="mt-1 space-y-0.5 text-xs text-ink-faint tabular">
                  <div>
                    장애 {st.incidents}건 · 중단 {formatDuration(st.downtime_seconds)}
                  </div>
                  <div title="관측된 검사 수 / 설정 주기 기준 기대 검사 수. 공백은 정상으로 간주하지 않습니다.">
                    측정 커버리지 {st.coverage_pct === null ? "—" : `${st.coverage_pct}%`} · 검사 {st.up_checks + st.down_checks}회
                    {st.unknown_checks ? ` (측정 불가 ${st.unknown_checks})` : ""}
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* 응답 시간 */}
      <Section
        title="응답 시간"
        description="HTTP 응답을 받은 검사의 평균값(타임아웃·연결 실패 제외). 측정이 없는 구간은 비워 둡니다."
        actions={
          <Segmented<Range>
            label="기간"
            value={range}
            onChange={setRange}
            options={[
              { value: "24h", label: "24시간" },
              { value: "7d", label: "7일" },
              { value: "30d", label: "30일(일별)" },
            ]}
          />
        }
      >
        {current && (
          <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
            <span className="text-ink-muted">
              평균 <strong className="text-ink tabular">{formatMs(current.avg_response_ms)}</strong>
            </span>
            <span className="text-ink-muted">
              최대 <strong className="text-ink tabular">{formatMs(current.max_response_ms)}</strong>
            </span>
            <span className="text-ink-muted">
              최소 <strong className="text-ink tabular">{formatMs(current.min_response_ms)}</strong>
            </span>
            <span className="text-ink-muted">
              p95 <strong className="text-ink tabular">{formatMs(current.p95_response_ms)}</strong>
            </span>
          </div>
        )}
        <ResponseTimeChart points={series.data?.points ?? []} range={range} loading={series.isFetching && !series.data} />
      </Section>

      {/* 일별 가동률 */}
      <Section title="최근 90일 가동률" description="일 단위 관측 결과. 회색은 측정 기록이 없는 날입니다." actions={<UptimeLegend />}>
        {daily.data ? <UptimeBars days={daily.data.days} /> : <div className="h-9 animate-pulse rounded bg-surface-sunken" />}
        <div className="mt-1.5 flex justify-between text-[11px] text-ink-faint">
          <span>90일 전</span>
          <span>오늘</span>
        </div>
      </Section>

      <div className="grid gap-5 lg:grid-cols-2">
        <Section title="장애 타임라인" description="연속 실패 기준 도달 시 장애로 기록됩니다.">
          {incidents.data ? <IncidentTimeline incidents={incidents.data} /> : <PageLoader />}
        </Section>

        <Section
          title="최근 검사 결과"
          actions={
            <Segmented<"all" | "down">
              label="검사 결과 필터"
              value={checksFilter}
              onChange={setChecksFilter}
              options={[
                { value: "all", label: "전체" },
                { value: "down", label: "실패만" },
              ]}
            />
          }
        >
          <div className="max-h-[480px] overflow-auto rounded-lg border border-line">
            <table className="w-full text-left text-xs tabular" data-testid="checks-table">
              <thead className="sticky top-0 bg-surface-sunken text-ink-muted">
                <tr>
                  <th className="px-3 py-2 font-medium">시각</th>
                  <th className="px-3 py-2 font-medium">결과</th>
                  <th className="px-3 py-2 text-right font-medium">응답</th>
                </tr>
              </thead>
              <tbody>
                {(checks.data ?? []).map((c) => (
                  <tr key={c.id} className="border-t border-line align-top">
                    <td className="whitespace-nowrap px-3 py-2 text-ink-muted">
                      {formatDateTime(c.checked_at)}
                      {c.is_manual && <span className="chip ml-1 py-0 text-[10px]">수동</span>}
                    </td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1.5">
                        <span
                          className={clsx(
                            "h-2 w-2 shrink-0 rounded-full",
                            c.outcome === "up" ? "bg-up" : c.outcome === "down" ? "bg-down" : "bg-nodata",
                          )}
                        />
                        <span className="font-medium text-ink">
                          {c.outcome === "up" ? "정상" : c.outcome === "down" ? "실패" : "측정 불가"}
                          {c.status_code ? ` · ${c.status_code}` : ""}
                        </span>
                      </span>
                      {c.error_message && <div className="mt-0.5 break-words text-ink-faint">{c.error_message}</div>}
                    </td>
                    <td className="whitespace-nowrap px-3 py-2 text-right">{c.status_code ? formatMs(c.response_time_ms) : "—"}</td>
                  </tr>
                ))}
                {checks.data?.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-3 py-8 text-center text-ink-faint">
                      {checksFilter === "down" ? "실패한 검사가 없습니다." : "아직 검사 기록이 없습니다."}
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Section>
      </div>

      <dl className="grid gap-2 text-xs text-ink-faint sm:grid-cols-3">
        <div>
          기대 상태 코드 <span className="font-mono text-ink-muted">{m.expected_status}</span>
        </div>
        <div>
          요청 <span className="font-mono text-ink-muted">{m.method}</span> · 리다이렉트 {m.follow_redirects ? "따라감" : "따라가지 않음"}
        </div>
        <div>복구 기준 연속 성공 {m.recovery_threshold}회</div>
      </dl>

      <ConfirmDialog
        open={confirmDelete}
        title="모니터를 삭제할까요?"
        confirmLabel="삭제"
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setConfirmDelete(false)}
      >
        <strong className="text-ink">{m.name}</strong> 의 검사 기록·장애 기록이 모두 삭제되며 되돌릴 수 없습니다.
      </ConfirmDialog>
    </div>
  );
}

function Fact({ label, value, title, tone }: { label: string; value: string; title?: string; tone?: "warn" }) {
  return (
    <div title={title}>
      <div className="text-xs text-ink-faint">{label}</div>
      <div className={clsx("mt-0.5 text-sm font-medium tabular", tone === "warn" ? "text-ink underline decoration-warn decoration-2 underline-offset-4" : "text-ink")}>
        {value}
      </div>
    </div>
  );
}
