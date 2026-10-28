import { useParams } from "react-router-dom";
import clsx from "clsx";
import { ApiError } from "../api/client";
import { usePublicStatus } from "../api/hooks";
import type { PublicStatusPage as PublicData } from "../api/types";
import { Icon } from "../components/Icon";
import { Logo, ThemeToggle } from "../components/Layout";
import { ResponseTimeChart } from "../components/ResponseTimeChart";
import { StatusBadge, publicStatusView } from "../components/Status";
import { UptimeBars, UptimeLegend } from "../components/UptimeBars";
import { PageLoader } from "../components/ui";
import { formatDateTime, formatDuration, formatPercent, formatRelative } from "../lib/format";

const OVERALL: Record<PublicData["overall"], { text: string; cls: string; icon: string }> = {
  operational: { text: "모든 서비스가 정상 운영 중입니다", cls: "border-up/40 bg-up/10", icon: "check" },
  partial_outage: { text: "일부 서비스에 장애가 있습니다", cls: "border-warn/50 bg-warn/10", icon: "alert" },
  major_outage: { text: "서비스 장애가 발생했습니다", cls: "border-down/50 bg-down/10", icon: "x" },
  unknown: { text: "서비스 상태를 확인하는 중입니다", cls: "border-line bg-surface-sunken", icon: "clock" },
};

/** 공개 상태 페이지: 로그인 영역과 분리된 독립 레이아웃. 공개 API 의 허용된 필드만 사용합니다. */
export function PublicStatusPage() {
  const slug = useParams().slug ?? "";
  const status = usePublicStatus(slug);

  return (
    <div className="min-h-screen">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-4 py-4">
          <span className="text-sm font-semibold text-ink-muted">상태 페이지</span>
          <ThemeToggle />
        </div>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8">
        {status.isLoading ? (
          <PageLoader />
        ) : status.isError ? (
          <div className="py-24 text-center">
            <h1 className="text-xl font-semibold">상태 페이지를 찾을 수 없습니다</h1>
            <p className="mt-2 text-sm text-ink-muted">
              {status.error instanceof ApiError && status.error.status === 429
                ? status.error.detail
                : "주소가 올바른지 확인하거나 페이지가 게시되었는지 관리자에게 문의하세요."}
            </p>
          </div>
        ) : (
          status.data && <PublicContent data={status.data} />
        )}
      </main>
      <footer className="mx-auto max-w-3xl px-4 pb-10 pt-4 text-center text-xs text-ink-faint">
        <span className="inline-flex items-center gap-1.5">
          Powered by <Logo className="text-xs [&>span]:h-5 [&>span]:w-5" />
        </span>
      </footer>
    </div>
  );
}

function PublicContent({ data }: { data: PublicData }) {
  const overall = OVERALL[data.overall];
  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl" data-testid="public-title">
          {data.title}
        </h1>
        {data.description && <p className="mt-2 text-ink-muted">{data.description}</p>}
      </div>

      <div className={clsx("flex items-center gap-3 rounded-xl border px-5 py-4", overall.cls)} data-testid="overall-status" data-overall={data.overall}>
        <Icon name={overall.icon} className="h-5 w-5 shrink-0" />
        <div>
          <div className="font-semibold">{overall.text}</div>
          <div className="text-xs text-ink-muted">마지막 업데이트 {formatDateTime(data.generated_at)}</div>
        </div>
      </div>

      <section aria-labelledby="components-heading">
        <div className="mb-3 flex flex-wrap items-end justify-between gap-2">
          <h2 id="components-heading" className="text-lg font-semibold">
            서비스
          </h2>
          {data.show_uptime && <UptimeLegend />}
        </div>
        <ul className="card divide-y divide-line">
          {data.components.map((c) => (
            <li key={c.key} className="p-4 sm:p-5" data-testid="public-component">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-medium">{c.name}</div>
                <div className="flex items-center gap-3">
                  {c.uptime && (
                    <span className="text-sm text-ink-muted tabular">
                      30일 {formatPercent(c.uptime["30d"])}
                    </span>
                  )}
                  <StatusBadge view={publicStatusView(c.status)} />
                </div>
              </div>
              {c.daily && (
                <div className="mt-3">
                  <UptimeBars days={c.daily} compact />
                  <div className="mt-1 flex justify-between text-[11px] text-ink-faint">
                    <span>90일 전</span>
                    {c.uptime && (
                      <span className="tabular">
                        24시간 {formatPercent(c.uptime["24h"])} · 7일 {formatPercent(c.uptime["7d"])}
                      </span>
                    )}
                    <span>오늘</span>
                  </div>
                </div>
              )}
              {c.response_times && (
                <div className="mt-3">
                  <div className="text-xs text-ink-faint">평균 응답 시간 (24시간)</div>
                  <ResponseTimeChart points={c.response_times} range="24h" height={140} />
                </div>
              )}
              <div className="mt-2 text-[11px] text-ink-faint">마지막 확인 {formatRelative(c.last_checked_at)}</div>
            </li>
          ))}
          {data.components.length === 0 && <li className="p-6 text-center text-sm text-ink-faint">표시할 서비스가 없습니다.</li>}
        </ul>
      </section>

      {data.show_incidents && (
        <section aria-labelledby="incidents-heading">
          <h2 id="incidents-heading" className="mb-3 text-lg font-semibold">
            최근 장애 (30일)
          </h2>
          {data.incidents.length === 0 ? (
            <div className="card p-6 text-center text-sm text-ink-muted">최근 30일간 보고된 장애가 없습니다.</div>
          ) : (
            <ul className="card divide-y divide-line" data-testid="public-incidents">
              {data.incidents.map((i, idx) => (
                <li key={idx} className="flex gap-3 p-4">
                  <span className={clsx("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", i.ongoing ? "bg-down" : "bg-up")} aria-hidden="true" />
                  <div className="min-w-0">
                    <div className="font-medium">
                      {i.component} {i.ongoing ? "장애 진행 중" : "장애 복구됨"}
                    </div>
                    <div className="mt-0.5 text-xs text-ink-muted tabular">
                      {formatDateTime(i.started_at)} 시작
                      {i.resolved_at ? ` · ${formatDateTime(i.resolved_at)} 복구 · 지속 ${formatDuration(i.duration_seconds)}` : ""}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}
