import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api, errorMessage } from "../api/client";
import { keys, useMonitors, useStatusPages } from "../api/hooks";
import type { Monitor, StatusPage, StatusPageInput } from "../api/types";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/Layout";
import { useToast } from "../components/Toast";
import { Banner, ConfirmDialog, EmptyState, PageLoader, Section, Spinner } from "../components/ui";

const EMPTY: StatusPageInput = {
  slug: "",
  title: "",
  description: "",
  is_published: false,
  show_uptime: true,
  show_response_times: false,
  show_incidents: true,
  items: [],
};

export function StatusPagesPage() {
  const pages = useStatusPages();
  const monitors = useMonitors();
  const [editing, setEditing] = useState<StatusPage | "new" | null>(null);

  if (pages.isLoading || monitors.isLoading) return <PageLoader />;

  if (editing) {
    return (
      <StatusPageEditor
        page={editing === "new" ? null : editing}
        monitors={monitors.data ?? []}
        onDone={() => setEditing(null)}
      />
    );
  }

  return (
    <div className="space-y-5">
      <PageHeader
        title="상태 페이지"
        description="고객에게 공개할 상태 페이지를 만듭니다. 선택한 모니터와 공개 항목만 표시되며 URL·오류 상세 등 내부 정보는 노출되지 않습니다."
        actions={
          <button type="button" className="btn-primary" onClick={() => setEditing("new")}>
            <Icon name="plus" className="h-4 w-4" />새 상태 페이지
          </button>
        }
      />
      {(pages.data ?? []).length === 0 ? (
        <EmptyState icon="globe" title="상태 페이지가 없습니다">
          서비스 상태를 외부에 공유하려면 상태 페이지를 만들고 게시하세요.
        </EmptyState>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {pages.data!.map((p) => (
            <div key={p.id} className="card flex flex-col gap-3 p-4" data-testid="status-page-card">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-semibold">{p.title}</div>
                  <div className="truncate font-mono text-xs text-ink-faint">/status/{p.slug}</div>
                </div>
                <span className={p.is_published ? "chip border-up/30 bg-up/10 text-ink" : "chip"}>
                  {p.is_published ? "게시됨" : "비공개"}
                </span>
              </div>
              <div className="text-xs text-ink-muted">
                모니터 {p.items.length}개 · {[p.show_uptime && "가동률", p.show_response_times && "응답 시간", p.show_incidents && "장애 이력"].filter(Boolean).join(" · ") || "상태만"}
              </div>
              <div className="mt-auto flex gap-2">
                <button type="button" className="btn-secondary text-xs" onClick={() => setEditing(p)}>
                  <Icon name="edit" className="h-3.5 w-3.5" />
                  편집
                </button>
                {p.is_published && (
                  <a href={`/status/${p.slug}`} target="_blank" rel="noreferrer" className="btn-ghost text-xs">
                    <Icon name="external" className="h-3.5 w-3.5" />
                    공개 페이지 열기
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusPageEditor({ page, monitors, onDone }: { page: StatusPage | null; monitors: Monitor[]; onDone: () => void }) {
  const qc = useQueryClient();
  const toast = useToast();
  const [form, setForm] = useState<StatusPageInput>(
    page
      ? {
          slug: page.slug,
          title: page.title,
          description: page.description,
          is_published: page.is_published,
          show_uptime: page.show_uptime,
          show_response_times: page.show_response_times,
          show_incidents: page.show_incidents,
          items: page.items.map((i) => ({ monitor_id: i.monitor_id, display_name: i.display_name })),
        }
      : EMPTY,
  );
  const [error, setError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const byId = new Map(monitors.map((m) => [m.id, m]));
  const available = monitors.filter((m) => !form.items.some((i) => i.monitor_id === m.id));

  const save = useMutation({
    mutationFn: (body: StatusPageInput) =>
      page ? api<StatusPage>(`/api/status-pages/${page.id}`, { method: "PUT", body }) : api<StatusPage>("/api/status-pages", { method: "POST", body }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.statusPages });
      toast("상태 페이지를 저장했습니다.");
      onDone();
    },
    onError: (err) => setError(errorMessage(err)),
  });
  const remove = useMutation({
    mutationFn: () => api(`/api/status-pages/${page!.id}`, { method: "DELETE" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.statusPages });
      toast("상태 페이지를 삭제했습니다.");
      onDone();
    },
  });

  const move = (idx: number, delta: number) => {
    const items = [...form.items];
    const [it] = items.splice(idx, 1);
    items.splice(idx + delta, 0, it);
    setForm({ ...form, items });
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!/^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$/.test(form.slug)) {
      setError("주소(slug)는 영문 소문자·숫자·하이픈 3~64자로 입력하세요.");
      return;
    }
    if (!form.title.trim()) {
      setError("제목을 입력하세요.");
      return;
    }
    if (form.items.some((i) => !i.display_name.trim())) {
      setError("모든 항목에 공개 이름을 입력하세요.");
      return;
    }
    save.mutate(form);
  };

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <button type="button" onClick={onDone} className="inline-flex items-center gap-1 text-sm text-ink-muted hover:text-ink">
        <Icon name="arrowLeft" className="h-4 w-4" />
        상태 페이지 목록
      </button>
      <PageHeader title={page ? "상태 페이지 편집" : "새 상태 페이지"} />
      <form onSubmit={submit} className="space-y-5" aria-label="상태 페이지 설정">
        {error && <Banner tone="down">{error}</Banner>}
        <Section title="기본 정보">
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="sp-title" className="label">
                  제목
                </label>
                <input id="sp-title" className="input" maxLength={100} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="예: ACME 서비스 상태" />
              </div>
              <div>
                <label htmlFor="sp-slug" className="label">
                  주소
                </label>
                <div className="flex items-center rounded-lg border border-line bg-surface-sunken focus-within:border-brand">
                  <span className="pl-3 text-sm text-ink-faint">/status/</span>
                  <input id="sp-slug" className="w-full bg-transparent px-1 py-2 font-mono text-sm outline-none" maxLength={64} value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase() })} placeholder="acme" />
                </div>
              </div>
            </div>
            <div>
              <label htmlFor="sp-desc" className="label">
                설명 <span className="font-normal text-ink-faint">(선택)</span>
              </label>
              <textarea id="sp-desc" className="input min-h-[64px]" maxLength={1000} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            </div>
          </div>
        </Section>

        <Section title="공개할 정보" description="체크한 항목만 공개 페이지에 표시됩니다.">
          <div className="space-y-2.5 text-sm">
            <Toggle label="공개 페이지 게시" hint="끄면 공개 주소로 접근할 수 없습니다(404)." checked={form.is_published} onChange={(v) => setForm({ ...form, is_published: v })} />
            <Toggle label="가동률 (24시간·7일·30일, 90일 막대)" checked={form.show_uptime} onChange={(v) => setForm({ ...form, show_uptime: v })} />
            <Toggle label="응답 시간 그래프 (24시간)" checked={form.show_response_times} onChange={(v) => setForm({ ...form, show_response_times: v })} />
            <Toggle label="최근 장애 이력 (30일)" hint="장애 시작·복구 시각과 지속 시간만 표시하고 오류 상세는 숨깁니다." checked={form.show_incidents} onChange={(v) => setForm({ ...form, show_incidents: v })} />
          </div>
        </Section>

        <Section title="표시할 모니터" description="공개 이름만 노출되며 실제 URL·내부 이름은 공개되지 않습니다.">
          {form.items.length > 0 && (
            <ul className="mb-3 space-y-2">
              {form.items.map((item, idx) => (
                <li key={item.monitor_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-line p-2.5">
                  <div className="min-w-0 flex-1">
                    <input
                      aria-label={`${byId.get(item.monitor_id)?.name ?? "모니터"} 공개 이름`}
                      className="input py-1.5"
                      maxLength={100}
                      value={item.display_name}
                      onChange={(e) => {
                        const items = [...form.items];
                        items[idx] = { ...item, display_name: e.target.value };
                        setForm({ ...form, items });
                      }}
                    />
                    <div className="mt-1 truncate text-[11px] text-ink-faint">내부: {byId.get(item.monitor_id)?.name ?? `#${item.monitor_id}`}</div>
                  </div>
                  <div className="flex gap-1">
                    <button type="button" className="btn-ghost h-8 w-8 p-0" aria-label="위로" disabled={idx === 0} onClick={() => move(idx, -1)}>
                      <Icon name="arrowUp" className="h-4 w-4" />
                    </button>
                    <button type="button" className="btn-ghost h-8 w-8 p-0" aria-label="아래로" disabled={idx === form.items.length - 1} onClick={() => move(idx, 1)}>
                      <Icon name="arrowDown" className="h-4 w-4" />
                    </button>
                    <button type="button" className="btn-ghost h-8 w-8 p-0 text-down" aria-label="제거" onClick={() => setForm({ ...form, items: form.items.filter((_, i) => i !== idx) })}>
                      <Icon name="x" className="h-4 w-4" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}
          {available.length > 0 ? (
            <select
              aria-label="모니터 추가"
              className="input"
              value=""
              onChange={(e) => {
                const m = byId.get(Number(e.target.value));
                if (m) setForm({ ...form, items: [...form.items, { monitor_id: m.id, display_name: m.name }] });
              }}
            >
              <option value="">+ 모니터 추가…</option>
              {available.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          ) : (
            <p className="text-sm text-ink-faint">{monitors.length ? "모든 모니터를 추가했습니다." : <>먼저 <Link to="/monitors/new" className="underline">모니터를 등록</Link>하세요.</>}</p>
          )}
        </Section>

        <div className="flex flex-wrap justify-between gap-2">
          {page ? (
            <button type="button" className="btn-danger" onClick={() => setConfirmDelete(true)}>
              <Icon name="trash" className="h-4 w-4" />
              삭제
            </button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <button type="button" className="btn-secondary" onClick={onDone}>
              취소
            </button>
            <button type="submit" className="btn-primary" disabled={save.isPending}>
              {save.isPending && <Spinner />}
              저장
            </button>
          </div>
        </div>
      </form>
      <ConfirmDialog
        open={confirmDelete}
        title="상태 페이지를 삭제할까요?"
        confirmLabel="삭제"
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setConfirmDelete(false)}
      >
        공개 주소가 더 이상 동작하지 않습니다. 모니터와 기록은 삭제되지 않습니다.
      </ConfirmDialog>
    </div>
  );
}

function Toggle({ label, hint, checked, onChange }: { label: string; hint?: string; checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-start gap-2">
      <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[rgb(var(--brand))]" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span>
        {label}
        {hint && <span className="block text-xs text-ink-faint">{hint}</span>}
      </span>
    </label>
  );
}
