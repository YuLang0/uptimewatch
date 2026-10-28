import { useEffect, useState, type FormEvent } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { api, errorMessage } from "../api/client";
import { keys, useChannels, useDeliveries, useNotifications, useNotificationSettings } from "../api/hooks";
import type { AppNotification, DeliveryStatus, NotificationSettings, TestNotificationResult } from "../api/types";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/Layout";
import { useToast } from "../components/Toast";
import { Banner, EmptyState, PageLoader, Section, Segmented, Spinner } from "../components/ui";
import { formatDateTime, formatRelative } from "../lib/format";

type Tab = "inbox" | "deliveries" | "settings";

const kindMeta: Record<AppNotification["kind"], { label: string; dot: string }> = {
  down: { label: "장애", dot: "bg-down" },
  up: { label: "복구", dot: "bg-up" },
  reminder: { label: "재알림", dot: "bg-down" },
  tls_expiring: { label: "인증서", dot: "bg-warn" },
  test: { label: "테스트", dot: "bg-brand" },
};

const deliveryMeta: Record<DeliveryStatus, { label: string; cls: string }> = {
  pending: { label: "발송 대기", cls: "border-line bg-surface-sunken text-ink-muted" },
  sent: { label: "발송됨", cls: "border-up/30 bg-up/10 text-ink" },
  failed: { label: "실패", cls: "border-down/40 bg-down/10 text-down" },
  skipped: { label: "미연동", cls: "border-line bg-surface-sunken text-ink-muted" },
  suppressed: { label: "중복 제한", cls: "border-warn/50 bg-warn/10 text-ink" },
};

export function NotificationsPage() {
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as Tab) || "inbox";
  return (
    <div className="space-y-5">
      <PageHeader title="알림" description="장애·복구 알림과 이메일 발송 기록, 알림 설정을 관리합니다." />
      <Segmented<Tab>
        label="알림 탭"
        value={tab}
        onChange={(t) => setParams(t === "inbox" ? {} : { tab: t })}
        options={[
          { value: "inbox", label: "알림함" },
          { value: "deliveries", label: "발송 기록" },
          { value: "settings", label: "설정" },
        ]}
      />
      {tab === "inbox" && <Inbox />}
      {tab === "deliveries" && <Deliveries />}
      {tab === "settings" && <SettingsTab />}
    </div>
  );
}

function Inbox() {
  const notifications = useNotifications();
  const qc = useQueryClient();
  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.notifications });
    qc.invalidateQueries({ queryKey: keys.dashboard });
  };
  const readOne = useMutation({ mutationFn: (id: number) => api(`/api/notifications/${id}/read`, { method: "POST" }), onSuccess: refresh });
  const readAll = useMutation({ mutationFn: () => api("/api/notifications/read-all", { method: "POST" }), onSuccess: refresh });

  if (notifications.isLoading) return <PageLoader />;
  const list = notifications.data ?? [];
  const unread = list.filter((n) => !n.read_at).length;
  return (
    <Section
      title="대시보드 알림"
      description={unread ? `읽지 않은 알림 ${unread}개` : "모든 알림을 읽었습니다."}
      actions={
        unread > 0 && (
          <button type="button" className="btn-secondary text-xs" onClick={() => readAll.mutate()} disabled={readAll.isPending}>
            <Icon name="check" className="h-3.5 w-3.5" />
            모두 읽음
          </button>
        )
      }
    >
      {list.length === 0 ? (
        <EmptyState icon="bell" title="알림이 없습니다">
          장애가 감지되거나 복구되면 이곳에 표시됩니다. 같은 장애에 대해서는 한 번만 알립니다.
        </EmptyState>
      ) : (
        <ul className="divide-y divide-line" data-testid="notification-list">
          {list.map((n) => (
            <li key={n.id} className={clsx("flex gap-3 py-3", !n.read_at && "")} data-kind={n.kind}>
              <span className={clsx("mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full", kindMeta[n.kind].dot)} aria-hidden="true" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="chip">{kindMeta[n.kind].label}</span>
                  <span className={clsx("text-sm", n.read_at ? "text-ink-muted" : "font-semibold text-ink")}>{n.title}</span>
                  {!n.read_at && <span className="text-[11px] font-semibold text-brand">새 알림</span>}
                </div>
                <p className="mt-1 whitespace-pre-line break-words text-sm text-ink-muted">{n.message}</p>
                <div className="mt-1 text-xs text-ink-faint" title={formatDateTime(n.created_at)}>
                  {formatRelative(n.created_at)}
                </div>
              </div>
              {!n.read_at && (
                <button type="button" className="btn-ghost h-8 shrink-0 px-2 text-xs" onClick={() => readOne.mutate(n.id)}>
                  읽음
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

function Deliveries() {
  const [status, setStatus] = useState<string>("all");
  const deliveries = useDeliveries(status);
  return (
    <Section
      title="이메일 발송 기록"
      description="발송 성공·실패·미연동·중복 제한 결과가 모두 기록됩니다. 실패한 발송은 최대 3회 재시도합니다."
      actions={
        <Segmented<string>
          label="발송 상태"
          value={status}
          onChange={setStatus}
          options={[
            { value: "all", label: "전체" },
            { value: "failed", label: "실패" },
            { value: "sent", label: "발송됨" },
            { value: "suppressed", label: "중복 제한" },
          ]}
        />
      }
    >
      {deliveries.isLoading ? (
        <PageLoader />
      ) : (deliveries.data ?? []).length === 0 ? (
        <EmptyState icon="mail" title="발송 기록이 없습니다" />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full min-w-[560px] text-left text-xs" data-testid="delivery-table">
            <thead className="bg-surface-sunken text-ink-muted">
              <tr>
                <th className="px-3 py-2 font-medium">시각</th>
                <th className="px-3 py-2 font-medium">종류</th>
                <th className="px-3 py-2 font-medium">수신자</th>
                <th className="px-3 py-2 font-medium">상태</th>
                <th className="px-3 py-2 font-medium">상세</th>
              </tr>
            </thead>
            <tbody>
              {deliveries.data!.map((d) => (
                <tr key={d.id} className="border-t border-line align-top">
                  <td className="whitespace-nowrap px-3 py-2 text-ink-muted tabular">{formatDateTime(d.created_at)}</td>
                  <td className="px-3 py-2">{kindMeta[d.kind as AppNotification["kind"]]?.label ?? d.kind}</td>
                  <td className="px-3 py-2 text-ink-muted">{d.recipient}</td>
                  <td className="px-3 py-2">
                    <span className={clsx("inline-flex rounded-full border px-2 py-0.5 font-semibold", deliveryMeta[d.status].cls)}>
                      {deliveryMeta[d.status].label}
                    </span>
                    {d.attempts > 0 && <div className="mt-0.5 text-ink-faint">시도 {d.attempts}회</div>}
                  </td>
                  <td className="max-w-xs break-words px-3 py-2 text-ink-faint">{d.last_error ?? (d.sent_at ? `발송 ${formatDateTime(d.sent_at)}` : "—")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Section>
  );
}

function SettingsTab() {
  const channels = useChannels();
  const settings = useNotificationSettings();
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<NotificationSettings | null>(null);
  const [testResult, setTestResult] = useState<TestNotificationResult | null>(null);

  useEffect(() => {
    if (settings.data && !form) setForm(settings.data);
  }, [settings.data, form]);

  const save = useMutation({
    mutationFn: (body: NotificationSettings) => api<NotificationSettings>("/api/notifications/settings", { method: "PUT", body }),
    onSuccess: (data) => {
      setForm(data);
      qc.invalidateQueries({ queryKey: keys.notificationSettings });
      qc.invalidateQueries({ queryKey: keys.channels });
      toast("알림 설정을 저장했습니다.");
    },
    onError: (err) => toast(errorMessage(err), "error"),
  });

  const test = useMutation({
    mutationFn: () => api<TestNotificationResult>("/api/notifications/test", { method: "POST" }),
    onSuccess: (data) => {
      setTestResult(data);
      qc.invalidateQueries({ queryKey: keys.notifications });
      qc.invalidateQueries({ queryKey: keys.dashboard });
      qc.invalidateQueries({ queryKey: ["deliveries"] });
    },
    onError: (err) => toast(errorMessage(err), "error"),
  });

  if (!channels.data || !form) return <PageLoader />;
  const email = channels.data.email;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate({ ...form, email_to: form.email_to?.trim() ? form.email_to.trim() : null });
  };

  return (
    <div className="grid gap-5 lg:grid-cols-5">
      <div className="space-y-5 lg:col-span-2">
        <Section title="알림 채널">
          <ul className="space-y-3">
            <li className="flex items-center justify-between gap-3 rounded-lg border border-line p-3">
              <div className="flex items-center gap-2.5">
                <Icon name="bell" className="h-4 w-4 text-ink-muted" />
                <div>
                  <div className="text-sm font-medium">대시보드 알림</div>
                  <div className="text-xs text-ink-faint">항상 사용</div>
                </div>
              </div>
              <span className="inline-flex items-center gap-1 rounded-full border border-up/30 bg-up/10 px-2 py-0.5 text-xs font-semibold">
                <Icon name="check" className="h-3 w-3" /> 사용 중
              </span>
            </li>
            <li className="rounded-lg border border-line p-3" data-testid="email-channel" data-configured={email.configured}>
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <Icon name="mail" className="h-4 w-4 text-ink-muted" />
                  <div>
                    <div className="text-sm font-medium">이메일 (SMTP)</div>
                    <div className="text-xs text-ink-faint">{email.configured ? `발신: ${email.from}` : "SMTP 서버가 설정되지 않음"}</div>
                  </div>
                </div>
                {email.configured ? (
                  <span className="inline-flex items-center gap-1 rounded-full border border-up/30 bg-up/10 px-2 py-0.5 text-xs font-semibold">
                    <Icon name="check" className="h-3 w-3" /> 연동됨
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 rounded-full border border-line bg-surface-sunken px-2 py-0.5 text-xs font-semibold text-ink-muted">
                    <Icon name="x" className="h-3 w-3" /> 미연동
                  </span>
                )}
              </div>
              {!email.configured && (
                <div className="mt-3 rounded-md bg-surface-sunken p-3 text-xs text-ink-muted">
                  <p className="mb-2">
                    서버의 <code className="font-mono">.env</code> 에 아래 환경변수를 설정하고 <code className="font-mono">api</code>·
                    <code className="font-mono">worker</code> 를 재시작하면 이메일이 발송됩니다. 설정 전에는 발송 기록에 '미연동'으로 남습니다.
                  </p>
                  <pre className="overflow-x-auto rounded bg-surface p-2 font-mono text-[11px] leading-relaxed text-ink">
{`SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=alerts@example.com
SMTP_PASSWORD=앱 비밀번호
SMTP_FROM=UptimeWatch <alerts@example.com>
SMTP_STARTTLS=true`}
                  </pre>
                </div>
              )}
            </li>
          </ul>
        </Section>

        <Section title="테스트 알림" description="대시보드 알림을 만들고, 이메일이 연동되어 있으면 실제로 1회 발송합니다.">
          <button type="button" className="btn-secondary" onClick={() => test.mutate()} disabled={test.isPending}>
            {test.isPending ? <Spinner /> : <Icon name="bell" className="h-4 w-4" />}
            테스트 알림 보내기
          </button>
          {testResult && (
            <div className="mt-3 space-y-1.5 text-sm" data-testid="test-result">
              <div className="flex items-center gap-2">
                <Icon name="check" className="h-4 w-4 text-up" /> 대시보드 알림 생성됨
              </div>
              <div className="flex items-start gap-2">
                <Icon
                  name={testResult.email.status === "sent" ? "check" : testResult.email.status === "failed" ? "x" : "info"}
                  className={clsx("mt-0.5 h-4 w-4 shrink-0", testResult.email.status === "sent" ? "text-up" : testResult.email.status === "failed" ? "text-down" : "text-ink-faint")}
                />
                <span>
                  이메일:{" "}
                  {testResult.email.status === "sent"
                    ? `${testResult.email.recipient} 로 발송됨`
                    : testResult.email.status === "skipped"
                      ? "미연동 — 발송하지 않음"
                      : testResult.email.status === "disabled"
                        ? "이메일 알림 꺼짐"
                        : `발송 실패 — ${testResult.email.error ?? ""}`}
                </span>
              </div>
            </div>
          )}
        </Section>
      </div>

      <Section title="알림 규칙" className="lg:col-span-3">
        <form onSubmit={submit} className="space-y-4">
          {!email.configured && <Banner tone="info">이메일이 미연동 상태라 아래 이메일 설정은 SMTP 연동 후에 적용됩니다.</Banner>}
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={form.email_enabled} onChange={(e) => setForm({ ...form, email_enabled: e.target.checked })} />
            장애·복구 시 이메일 알림 받기
          </label>
          <div>
            <label htmlFor="email_to" className="label">
              수신 이메일
            </label>
            <input id="email_to" type="email" className="input" placeholder={email.recipient} value={form.email_to ?? ""} onChange={(e) => setForm({ ...form, email_to: e.target.value })} />
            <p className="hint">비워 두면 계정 이메일({email.recipient})로 보냅니다.</p>
          </div>
          <div className="grid gap-4 sm:grid-cols-3">
            <div>
              <label htmlFor="cooldown" className="label">
                중복 알림 제한(분)
              </label>
              <input id="cooldown" type="number" min={0} max={1440} className="input" value={form.email_cooldown_minutes} onChange={(e) => setForm({ ...form, email_cooldown_minutes: Number(e.target.value) })} />
              <p className="hint">같은 모니터의 같은 종류 메일을 이 시간 안에 다시 보내지 않음(장애↔복구 반복 대비).</p>
            </div>
            <div>
              <label htmlFor="reminder" className="label">
                장애 지속 재알림(분)
              </label>
              <input id="reminder" type="number" min={0} max={1440} className="input" value={form.reminder_interval_minutes} onChange={(e) => setForm({ ...form, reminder_interval_minutes: Number(e.target.value) })} />
              <p className="hint">0 이면 재알림하지 않음.</p>
            </div>
            <div>
              <label htmlFor="tls_days" className="label">
                인증서 만료 경고(일)
              </label>
              <input id="tls_days" type="number" min={0} max={90} className="input" value={form.tls_warning_days} onChange={(e) => setForm({ ...form, tls_warning_days: Number(e.target.value) })} />
              <p className="hint">만료 N일 전 한 번 알림. 0 이면 끔.</p>
            </div>
          </div>
          <div className="flex justify-end">
            <button type="submit" className="btn-primary" disabled={save.isPending}>
              {save.isPending && <Spinner />}
              설정 저장
            </button>
          </div>
        </form>
      </Section>
    </div>
  );
}
