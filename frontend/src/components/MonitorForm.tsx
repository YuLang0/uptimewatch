import { useState, type FormEvent } from "react";
import type { MonitorInput } from "../api/types";
import { formatInterval, looksLikeSecretInUrl } from "../lib/format";
import { Icon } from "./Icon";
import { Banner, Spinner } from "./ui";

const INTERVALS = [60, 300, 600, 1800, 3600];

export const DEFAULT_MONITOR: MonitorInput = {
  name: "",
  description: "",
  url: "https://",
  method: "GET",
  interval_seconds: 300,
  timeout_seconds: 10,
  expected_status: "200-299",
  failure_threshold: 3,
  recovery_threshold: 1,
  follow_redirects: true,
  is_active: true,
};

export function validateMonitor(v: MonitorInput): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!v.name.trim()) errors.name = "이름을 입력하세요.";
  if (!/^https?:\/\/[^\s/]+/i.test(v.url.trim())) errors.url = "http:// 또는 https:// 로 시작하는 주소를 입력하세요.";
  else if (/^https?:\/\/[^/]*@/i.test(v.url.trim())) errors.url = "URL 에 사용자 이름·비밀번호를 넣을 수 없습니다.";
  if (!Number.isInteger(v.interval_seconds) || v.interval_seconds < 60) errors.interval_seconds = "확인 주기는 60초 이상이어야 합니다.";
  if (!Number.isInteger(v.timeout_seconds) || v.timeout_seconds < 1 || v.timeout_seconds > 30)
    errors.timeout_seconds = "타임아웃은 1~30초로 설정하세요.";
  else if (v.timeout_seconds >= v.interval_seconds) errors.timeout_seconds = "타임아웃은 확인 주기보다 짧아야 합니다.";
  if (!/^\s*\d{3}(\s*-\s*\d{3})?(\s*,\s*\d{3}(\s*-\s*\d{3})?)*\s*$/.test(v.expected_status))
    errors.expected_status = "예: 200, 200-299, 200-299,301";
  if (v.failure_threshold < 1 || v.failure_threshold > 10) errors.failure_threshold = "1~10 사이로 입력하세요.";
  if (v.recovery_threshold < 1 || v.recovery_threshold > 10) errors.recovery_threshold = "1~10 사이로 입력하세요.";
  return errors;
}

export function MonitorForm({
  initial,
  isEdit,
  submitting,
  serverError,
  onSubmit,
  onCancel,
}: {
  initial: MonitorInput;
  isEdit?: boolean;
  submitting?: boolean;
  serverError?: string | null;
  onSubmit: (value: MonitorInput) => void;
  onCancel: () => void;
}) {
  const [v, setV] = useState<MonitorInput>(initial);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [customInterval, setCustomInterval] = useState(!INTERVALS.includes(initial.interval_seconds));

  const set = <K extends keyof MonitorInput>(key: K, value: MonitorInput[K]) => setV((prev) => ({ ...prev, [key]: value }));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const errs = validateMonitor(v);
    setErrors(errs);
    if (Object.keys(errs).length) return;
    onSubmit({ ...v, name: v.name.trim(), url: v.url.trim(), description: v.description.trim() });
  };

  const field = (key: string) => (errors[key] ? { "aria-invalid": true, "aria-describedby": `${key}-error` } : {});
  const err = (key: string) =>
    errors[key] ? (
      <p id={`${key}-error`} className="mt-1 text-xs font-medium text-down">
        {errors[key]}
      </p>
    ) : null;

  return (
    <form onSubmit={submit} noValidate className="space-y-6" aria-label="모니터 설정">
      {serverError && <Banner tone="down">{serverError}</Banner>}

      <fieldset className="card space-y-4 p-4 sm:p-5">
        <legend className="sr-only">기본 정보</legend>
        <h2 className="text-base font-semibold">기본 정보</h2>
        <div>
          <label htmlFor="name" className="label">
            이름
          </label>
          <input id="name" className="input" value={v.name} maxLength={100} onChange={(e) => set("name", e.target.value)} {...field("name")} placeholder="예: 메인 홈페이지" />
          {err("name")}
        </div>
        <div>
          <label htmlFor="url" className="label">
            URL
          </label>
          <input
            id="url"
            className="input font-mono"
            value={v.url}
            maxLength={2048}
            inputMode="url"
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => set("url", e.target.value)}
            {...field("url")}
            placeholder="https://example.com/health"
          />
          {err("url")}
          {looksLikeSecretInUrl(v.url) && (
            <p className="mt-1 flex items-center gap-1 text-xs font-medium text-ink">
              <Icon name="alert" className="h-3.5 w-3.5 text-warn" />
              URL 쿼리에 토큰·비밀번호로 보이는 값이 있습니다. 비밀정보 대신 공개 헬스체크 주소를 사용하세요.
            </p>
          )}
          <p className="hint">
            공개 인터넷의 http/https 주소만 검사합니다. 사설·루프백·메타데이터 주소와 사용자 정의 헤더는 보안상 지원하지 않습니다.
          </p>
        </div>
        <div>
          <label htmlFor="description" className="label">
            설명 <span className="font-normal text-ink-faint">(선택)</span>
          </label>
          <textarea id="description" className="input min-h-[72px]" maxLength={500} value={v.description} onChange={(e) => set("description", e.target.value)} />
        </div>
      </fieldset>

      <fieldset className="card space-y-4 p-4 sm:p-5">
        <legend className="sr-only">검사 설정</legend>
        <h2 className="text-base font-semibold">검사 설정</h2>
        <div>
          <span className="label" id="interval-label">
            확인 주기
          </span>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-labelledby="interval-label">
            {INTERVALS.map((s) => (
              <button
                type="button"
                role="radio"
                aria-checked={!customInterval && v.interval_seconds === s}
                key={s}
                onClick={() => {
                  setCustomInterval(false);
                  set("interval_seconds", s);
                }}
                className={
                  !customInterval && v.interval_seconds === s
                    ? "btn border border-brand bg-brand/10 px-3 py-1.5 text-ink"
                    : "btn-secondary px-3 py-1.5"
                }
              >
                {formatInterval(s)}
              </button>
            ))}
            <button
              type="button"
              role="radio"
              aria-checked={customInterval}
              onClick={() => setCustomInterval(true)}
              className={customInterval ? "btn border border-brand bg-brand/10 px-3 py-1.5 text-ink" : "btn-secondary px-3 py-1.5"}
            >
              직접 입력
            </button>
          </div>
          {customInterval && (
            <div className="mt-2 flex items-center gap-2">
              <input
                aria-label="확인 주기(초)"
                type="number"
                min={60}
                step={1}
                className="input w-32"
                value={v.interval_seconds}
                onChange={(e) => set("interval_seconds", Number(e.target.value))}
                {...field("interval_seconds")}
              />
              <span className="text-sm text-ink-muted">초</span>
            </div>
          )}
          {err("interval_seconds")}
          <p className="hint">최소 1분. 대상 사이트에 부담을 주지 않도록 필요한 만큼만 자주 확인하세요.</p>
        </div>

        <div className="grid gap-4 sm:grid-cols-3">
          <div>
            <label htmlFor="timeout" className="label">
              타임아웃(초)
            </label>
            <input id="timeout" type="number" min={1} max={30} className="input" value={v.timeout_seconds} onChange={(e) => set("timeout_seconds", Number(e.target.value))} {...field("timeout_seconds")} />
            {err("timeout_seconds")}
          </div>
          <div>
            <label htmlFor="expected" className="label">
              기대 상태 코드
            </label>
            <input id="expected" className="input font-mono" value={v.expected_status} onChange={(e) => set("expected_status", e.target.value)} {...field("expected_status")} />
            {err("expected_status")}
          </div>
          <div>
            <label htmlFor="method" className="label">
              요청 방식
            </label>
            <select id="method" className="input" value={v.method} onChange={(e) => set("method", e.target.value as "GET" | "HEAD")}>
              <option value="GET">GET</option>
              <option value="HEAD">HEAD (본문 없이)</option>
            </select>
          </div>
        </div>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={v.follow_redirects} onChange={(e) => set("follow_redirects", e.target.checked)} />
          리다이렉트 따라가기 <span className="text-ink-faint">(최대 5회, 매 단계 목적지 보안 검증)</span>
        </label>
      </fieldset>

      <fieldset className="card space-y-4 p-4 sm:p-5">
        <legend className="sr-only">장애 판정</legend>
        <h2 className="text-base font-semibold">장애 판정</h2>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="failure_threshold" className="label">
              연속 실패 기준
            </label>
            <input id="failure_threshold" type="number" min={1} max={10} className="input" value={v.failure_threshold} onChange={(e) => set("failure_threshold", Number(e.target.value))} {...field("failure_threshold")} />
            {err("failure_threshold")}
            <p className="hint">이 횟수만큼 연속으로 실패해야 장애로 판정합니다. 그보다 적은 실패는 일시적 실패로만 기록됩니다.</p>
          </div>
          <div>
            <label htmlFor="recovery_threshold" className="label">
              복구 기준
            </label>
            <input id="recovery_threshold" type="number" min={1} max={10} className="input" value={v.recovery_threshold} onChange={(e) => set("recovery_threshold", Number(e.target.value))} {...field("recovery_threshold")} />
            {err("recovery_threshold")}
            <p className="hint">장애 중 이 횟수만큼 연속 성공하면 복구로 판정합니다.</p>
          </div>
        </div>
        {!isEdit && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="h-4 w-4 accent-[rgb(var(--brand))]" checked={v.is_active ?? true} onChange={(e) => set("is_active", e.target.checked)} />
            저장 후 바로 검사 시작
          </label>
        )}
      </fieldset>

      <div className="flex justify-end gap-2">
        <button type="button" className="btn-secondary" onClick={onCancel}>
          취소
        </button>
        <button type="submit" className="btn-primary" disabled={submitting}>
          {submitting && <Spinner />}
          {isEdit ? "변경 저장" : "모니터 추가"}
        </button>
      </div>
    </form>
  );
}
